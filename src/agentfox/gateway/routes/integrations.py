"""GitHub connect flow — repo scanning that proposes agents and policies for review.

The dashboard's "Sign in with GitHub" doubles as the repo-connection grant (the
OIDC/SAML seam noted on ``User.external_id``, finally wired to something): GitHub
OAuth establishes who the person is, and this module is where the resulting access
token gets used — to list an org's repos and to run ``discovery.py``'s static
scanner against one, without a real git clone or executing any of the target repo's
code (the same "static, never import, never execute" guarantee ``discovery.scan``
already makes for a local checkout).

Everything created here is inert by construction, not by convention:

* A draft agent (``status="draft", registered=False``) is invisible to enforcement
  the same way any unregistered agent is (see ``register_agent(..., draft=True)``).
* A proposed policy is created through the same ``save_policy`` every hand-authored
  policy goes through, which means it starts in ``observe`` mode — recording, never
  blocking (R3) — before a human has looked at it, and has no rules yet.

Approving a proposal therefore doesn't grant capability the platform didn't already
have; it just clears the review flag.
"""

from __future__ import annotations

import logging
import secrets
import tarfile
import tempfile
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core import ids
from agentfox.core.config import (
    PUBLISHED_SECRET_VALUES,
    get_settings,
    is_development,
)
from agentfox.core.models import (
    ApiToken,
    GithubConnection,
    Policy,
    PolicyVersion,
    ScanRun,
    User,
    utcnow,
)
from agentfox.core.tenancy import bind_session, system_scope
from agentfox.discovery.openapi import SpecFetchError, fetch_spec, scan_spec
from agentfox.discovery.repo import ScanReport
from agentfox.discovery.repo import scan as discovery_scan
from agentfox.gateway.auth import issue_token, resolve_token_record, revoke_token
from agentfox.gateway.deps import current_user, db, require
from agentfox.policy import PolicyDocument, save_policy
from agentfox.prove.audit import chain
from agentfox.registry.service import propose_from_scan, register_agent, slugify

log = logging.getLogger(__name__)

router = APIRouter(tags=["integrations"])

_GITHUB_API = "https://api.github.com"
#: Above this, extraction stops — a resource-exhaustion guard on server-supplied
#: archive content, not a code-execution one (nothing here ever imports the repo).
_MAX_EXTRACTED_BYTES = 80 * 1024 * 1024
_MAX_MEMBER_BYTES = 8 * 1024 * 1024


# ---------------------------------------------------------------------------
# Token encryption — a connected GitHub account's access token, at rest.
# ---------------------------------------------------------------------------


def _fernet() -> Fernet:
    key = get_settings().token_encryption_key
    if not key:
        raise HTTPException(
            503,
            "GitHub connect is not configured on this deployment "
            "(NOMETRIA_TOKEN_ENCRYPTION_KEY is unset) — fails closed rather than "
            "storing an access token unencrypted.",
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def _encrypt(raw: str) -> str:
    return _fernet().encrypt(raw.encode()).decode()


def _decrypt(blob: str) -> str:
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(500, "stored GitHub token could not be decrypted") from exc


# ---------------------------------------------------------------------------
# Provisioning — the one privileged call. Made server-to-server by the
# dashboard's OAuth callback, before any user token exists to authenticate with.
# ---------------------------------------------------------------------------


class ProvisionIn(BaseModel):
    github_user_id: str
    github_login: str
    email: str
    name: str = ""


#: How many GitHub sign-in sessions one person may hold at once. Each sign-in mints
#: a token (the raw value is never stored, so an old one cannot be handed back), and
#: before this cap every sign-in added another 365-day credential that nothing ever
#: retired. Past the cap the oldest are revoked: a browser that has not signed in for
#: a while is signed out, and the set of live login tokens stays small and known.
MAX_LOGIN_SESSIONS = 5
LOGIN_TOKEN_NAME = "github-login"


def _require_service_secret(
    x_nometria_service_secret: Annotated[str | None, Header()] = None,
) -> None:
    settings = get_settings()
    expected = settings.service_auth_secret
    if not is_development(settings) and expected in PUBLISHED_SECRET_VALUES:
        # create_app() already refuses to start like this; this is the same rule at
        # the one route it protects, so a process that got past startup some other
        # way (settings changed underneath it) still cannot be talked into minting
        # an owner token with a value printed in the source.
        raise HTTPException(
            503,
            "GitHub sign-in is disabled: AGENTFOX_SERVICE_AUTH_SECRET is still a "
            "published value on a non-development deployment.",
        )
    if not x_nometria_service_secret or not secrets.compare_digest(
        x_nometria_service_secret, expected
    ):
        raise HTTPException(401, "invalid or missing service secret")


@router.post("/api/auth/github/provision", dependencies=[Depends(_require_service_secret)])
def provision(payload: ProvisionIn, session: Session = Depends(db)) -> dict[str, Any]:
    """Find-or-create the user behind a GitHub identity, and mint them a token.

    **Trust model.** This route believes the GitHub identity in the body because of
    who is allowed to send it, not because of anything in the body. The only holder
    of ``service_auth_secret`` is the dashboard's OAuth callback, which calls here
    only after it has completed GitHub's OAuth exchange itself (state cookie checked,
    code exchanged for a token, ``/user`` read with that token) — so
    ``github_user_id`` is GitHub's own answer to "who signed in", relayed by a party
    that holds the deployment's secret. Under that model:

    * The secret is equivalent to "sign in as any GitHub-linked user of this
      deployment". It must be random, shared only between the gateway and the
      dashboard, and never the published default — `create_app()` refuses to start
      outside development with the default, and :func:`_require_service_secret`
      refuses this route on its own as well.
    * Find-or-create keys on ``github_user_id`` and nothing else: GitHub's numeric
      id is immutable, unlike a login (renameable, then claimable by someone else)
      or an email (the body's email is whatever GitHub reported, and keying on it
      would let any GitHub account that lists an address take over the user who
      owns that address here). An existing user is therefore only ever returned to
      a sign-in that GitHub attested as that same account.
    * A deactivated user is refused rather than handed a token that every other
      route would then reject.

    Runs in system scope for the lookup because — like every credential resolution
    in auth.py — we cannot know the tenant until we know who this is. A first-time
    GitHub login gets a brand new org: there is no invite flow yet, so "new GitHub
    identity" and "new tenant" are the same event.

    Each sign-in mints a fresh token (the raw value of an old one is not stored, so
    it cannot be reused) and retires all but the newest ``MAX_LOGIN_SESSIONS`` login
    tokens; signing out revokes the session's own token (``POST /api/auth/logout``).
    """
    is_new_org = False
    with system_scope("resolving a GitHub identity for provisioning", routine=True):
        user = session.scalar(select(User).where(User.external_id == payload.github_user_id))
        if user is not None and not user.active:
            raise HTTPException(403, "this account has been deactivated")
        if user is None:
            user = User(
                email=payload.email or f"{payload.github_login}@users.noreply.github.com",
                name=payload.name or payload.github_login,
                external_id=payload.github_user_id,
                org_id=ids.new_id("org"),
                # First (and, absent an invite flow, only) member of a brand-new org —
                # "developer" (the model default) can't issue credentials, bind policy
                # to enforce, or manage users, which would make a fresh signup unable
                # to finish governing anything they just registered.
                role="owner",
            )
            session.add(user)
            session.flush()
            is_new_org = True
    bind_session(session, user.org_id)
    if is_new_org:
        # Control/FrameworkMapping/Obligation are tenant-scoped like every mapped
        # class (assert_tenant_safe), so the shared reference catalog has to be
        # synced into each new org rather than assumed to exist — otherwise
        # Compliance shows 0 controls until someone finds the manual sync action.
        from agentfox.prove.compliance.catalog import sync_catalog, sync_obligations

        sync_catalog(session)
        sync_obligations(session)
    token, raw = issue_token(
        session,
        user,
        name=LOGIN_TOKEN_NAME,
        actor=user.email or user.id,
        reason="GitHub OAuth sign-in",
    )
    _retire_old_login_tokens(session, user, keep=token.id)
    session.commit()
    return {
        "token": raw,
        "user": {"id": user.id, "email": user.email, "org_id": user.org_id},
    }


def _retire_old_login_tokens(session: Session, user: User, *, keep: str) -> None:
    """Revoke all but the newest MAX_LOGIN_SESSIONS live GitHub-login tokens."""
    live = [
        t
        for t in session.scalars(
            select(ApiToken)
            .where(
                ApiToken.user_id == user.id,
                ApiToken.name == LOGIN_TOKEN_NAME,
                ApiToken.revoked_at.is_(None),
            )
            .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
        )
        if t.id != keep
    ]
    for stale in live[MAX_LOGIN_SESSIONS - 1 :]:
        revoke_token(
            session,
            stale.id,
            actor=user.email or user.id,
            reason=f"GitHub sign-in: more than {MAX_LOGIN_SESSIONS} live login sessions",
        )


@router.post("/api/auth/logout")
def logout(
    session: Session = Depends(db),
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Revoke the bearer token this request presents — the dashboard's Sign Out.

    Deleting the cookie alone left the token valid for the rest of its 365 days, so
    a copied cookie outlived the sign-out. Idempotent: an already-revoked, expired or
    unknown token is reported as not revoked, never as an error, so a browser whose
    session already ended can still sign out cleanly.
    """
    raw = ""
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1].strip()
    token = resolve_token_record(session, raw) if raw else None
    if token is None:
        return {"revoked": False}
    with system_scope("signing out: revoking the presented token", routine=True):
        user = session.get(User, token.user_id)
    if user is not None:
        bind_session(session, user.org_id)
    revoke_token(
        session,
        token.id,
        actor=(user.email or user.id) if user else token.user_id,
        reason="signed out",
    )
    session.commit()
    return {"revoked": True}


# ---------------------------------------------------------------------------
# Connection — storing the GitHub access token itself, org-scoped.
# ---------------------------------------------------------------------------


class ConnectIn(BaseModel):
    access_token: str


def _get_connection(session: Session) -> GithubConnection | None:
    return session.scalar(select(GithubConnection).order_by(GithubConnection.created_at.desc()))


@router.post("/api/integrations/github/connect")
def connect(
    payload: ConnectIn, session: Session = Depends(db), user: User = Depends(current_user)
) -> dict[str, Any]:
    try:
        resp = httpx.get(
            f"{_GITHUB_API}/user",
            headers={
                "Authorization": f"Bearer {payload.access_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"could not verify the GitHub access token: {exc}") from exc
    profile = resp.json()

    conn = _get_connection(session)
    if conn is None:
        conn = GithubConnection(connected_by_user_id=user.id)
        session.add(conn)
    conn.github_user_id = str(profile.get("id"))
    conn.github_login = profile.get("login", "")
    conn.access_token_encrypted = _encrypt(payload.access_token)
    session.flush()
    chain.append(
        session,
        "integration.github.connected",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="github_connection",
        subject_id=conn.id,
        payload={"github_login": conn.github_login},
    )
    session.commit()
    return {"connected": True, "github_login": conn.github_login}


@router.get("/api/integrations/github/repos")
def list_repos(
    session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    conn = _get_connection(session)
    if conn is None:
        raise HTTPException(404, "no GitHub account connected")
    token = _decrypt(conn.access_token_encrypted)
    try:
        resp = httpx.get(
            f"{_GITHUB_API}/user/repos",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            params={"per_page": 100, "sort": "updated"},
            timeout=20.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"GitHub repo list failed: {exc}") from exc

    already_scanned = set(session.scalars(select(ScanRun.repo_full_name)))
    repos = [
        {
            "full_name": r["full_name"],
            "private": r["private"],
            "default_branch": r["default_branch"],
            "description": r.get("description") or "",
            "updated_at": r.get("updated_at"),
            # "User" (someone's personal account) vs "Organization" (a company/team
            # account) — a non-technical reader can't otherwise tell which of a long
            # list is their company's code vs a personal project.
            "owner_type": (r.get("owner") or {}).get("type", "User"),
            "scanned": r["full_name"] in already_scanned,
        }
        for r in resp.json()
    ]
    return {"github_login": conn.github_login, "repos": repos}


# ---------------------------------------------------------------------------
# Scanning — download a tarball server-side, run the existing static scanner
# against it exactly as `agentfox scan` would against a local checkout, and
# propose (never create live) agents and policies from what it finds.
# ---------------------------------------------------------------------------


class ScanIn(BaseModel):
    repo_full_name: str
    ref: str = ""


def _download_and_extract(repo_full_name: str, ref: str, token: str, dest: Path) -> Path:
    url = f"{_GITHUB_API}/repos/{repo_full_name}/tarball"
    if ref:
        url = f"{url}/{ref}"
    with httpx.stream(
        "GET",
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        follow_redirects=True,
        timeout=60.0,
    ) as resp:
        resp.raise_for_status()
        archive = dest / "repo.tar.gz"
        total = 0
        with archive.open("wb") as f:
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > _MAX_EXTRACTED_BYTES:
                    raise HTTPException(413, "repository archive is too large to scan")
                f.write(chunk)

    extracted = dest / "src"
    extracted.mkdir()
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if member.size > _MAX_MEMBER_BYTES or not member.isfile() and not member.isdir():
                continue
            # GitHub's archive nests everything under one `{owner}-{repo}-{sha}/`
            # directory — strip it so scanned paths read as real repo-relative paths.
            parts = Path(member.name).parts
            if len(parts) < 2:
                continue
            member.name = str(Path(*parts[1:]))
            tar.extract(member, extracted, filter="data")
    archive.unlink()
    return extracted


@router.post("/api/integrations/github/scan")
def trigger_scan(
    payload: ScanIn, session: Session = Depends(db), user: User = Depends(require("registry"))
) -> dict[str, Any]:
    conn = _get_connection(session)
    if conn is None:
        raise HTTPException(404, "no GitHub account connected")
    token = _decrypt(conn.access_token_encrypted)

    run = ScanRun(
        connection_id=conn.id,
        repo_full_name=payload.repo_full_name,
        ref=payload.ref,
        status="running",
    )
    session.add(run)
    session.flush()

    with tempfile.TemporaryDirectory(prefix="agentfox-scan-") as tmp:
        try:
            root = _download_and_extract(payload.repo_full_name, payload.ref, token, Path(tmp))
            report = discovery_scan(root)
        except HTTPException:
            run.status = "failed"
            run.completed_at = utcnow()
            session.commit()
            raise
        except Exception as exc:  # noqa: BLE001 - reported on the run, not swallowed
            run.status = "failed"
            run.completed_at = utcnow()
            run.summary_json = {"error": str(exc)[:500]}
            session.commit()
            raise HTTPException(500, f"scan failed: {exc}") from exc

    def _top_dir(rel_path: str) -> str:
        parts = Path(rel_path).parts
        return parts[0] if parts else "root"

    created_agents, created_policies = propose_from_scan(
        session,
        run_id=run.id,
        repo_slug_base=payload.repo_full_name.split("/")[-1],
        repo_display_name=payload.repo_full_name,
        frameworks=report.frameworks,
        sites=[
            {"kind": s.kind, "top_dir": _top_dir(s.file), "provider": s.provider}
            for s in report.sites
            if s.kind in ("agent_definition", "tool", "model_call", "lethal_trifecta")
        ],
        author=user.email or user.id,
    )

    run.status = "completed"
    run.completed_at = utcnow()
    run.summary_json = {
        "files_scanned": report.files_scanned,
        # A repository this scanner cannot read produces an empty `sites` that looks
        # exactly like a clean one. These two say which it was: `code_files_scanned`
        # is how much source was actually examined, and `inconclusive` is true when
        # that was none — see discovery.ScanReport.inconclusive.
        "code_files_scanned": report.code_files_scanned,
        "inconclusive": report.inconclusive,
        "next_step": report.next_step(),
        "frameworks": report.frameworks,
        "sites": report.by_kind(),
        "agents_proposed": created_agents,
        "policies_proposed": created_policies,
    }
    session.flush()
    chain.append(
        session,
        "integration.github.scanned",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="scan_run",
        subject_id=run.id,
        payload={"repo": payload.repo_full_name, **run.summary_json},
    )
    session.commit()
    return {"scan_run_id": run.id, "status": run.status, "summary": run.summary_json}


@router.get("/api/integrations/github/scans/{scan_id}")
def get_scan(
    scan_id: str, session: Session = Depends(db), _user: User = Depends(current_user)
) -> dict[str, Any]:
    run = session.get(ScanRun, scan_id)
    if run is None:
        raise HTTPException(404, "unknown scan")
    return {
        "id": run.id,
        "repo_full_name": run.repo_full_name,
        "ref": run.ref,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "summary": run.summary_json,
    }


# ---------------------------------------------------------------------------
# Hosted-API connect — the second onboarding path, for a team whose AI system is a
# live endpoint they call rather than code they'd hand over. No source access and
# no stored credential: we fetch the *spec document* once (never an operation on
# the live API — the same "never execute" guarantee discovery.scan makes for a
# repo) and propose from that. Nothing to hold between calls, so unlike GitHub
# there's no separate "connection" — connect and scan collapse into one request.
# ---------------------------------------------------------------------------


class HostedApiScanIn(BaseModel):
    endpoint_url: str
    docs_url: str | None = None
    openapi_spec_url: str | None = None
    purpose: str = ""


@router.post("/api/integrations/hosted-api/scan")
def scan_hosted_api(
    payload: HostedApiScanIn,
    session: Session = Depends(db),
    user: User = Depends(require("registry")),
) -> dict[str, Any]:
    host = urlparse(payload.endpoint_url).hostname or payload.endpoint_url

    run = ScanRun(
        source_kind="hosted_api",
        target_url=payload.openapi_spec_url or payload.endpoint_url,
        status="running",
    )
    session.add(run)
    session.flush()

    if payload.openapi_spec_url:
        try:
            spec = fetch_spec(payload.openapi_spec_url)
            report = scan_spec(spec, source_label=host)
        except SpecFetchError as exc:
            run.status = "failed"
            run.completed_at = utcnow()
            run.summary_json = {"error": str(exc)}
            session.commit()
            raise HTTPException(422, str(exc)) from exc
    else:
        # No spec given — still register the endpoint for review rather than
        # refusing outright. There's nothing to enumerate, so no sites are
        # proposed and the reviewer sees an agent with zero known operations.
        report = ScanReport(root=host)

    slug = slugify(host)
    agent = register_agent(
        session,
        slug=slug,
        name=host,
        purpose=payload.purpose,
        framework="hosted_api",
        draft=True,
        source_scan_run_id=run.id,
    )
    agent.endpoint_url = payload.endpoint_url
    agent.docs_url = payload.docs_url
    agent.openapi_spec_url = payload.openapi_spec_url
    session.flush()

    created_policies: list[str] = []
    if report.sites:
        doc = PolicyDocument(
            key=f"scan-{run.id}-hosted-api",
            name="Hosted API guardrails",
            description=(
                f"Detects unsafe tool actions against {host} — prompt injection, "
                f"PII/secret leaks, and unsafe tool actions."
            ),
            mode="observe",
            scope={"agents": [slug]},
            rules=[],
        )
        policy, _version = save_policy(
            session,
            doc,
            author=user.email or user.id,
            notes=f"Proposed by scan {run.id}",
            bind_mode="observe",
        )
        policy.proposed = True
        policy.source_scan_run_id = run.id
        created_policies.append(policy.key)

    run.status = "completed"
    run.completed_at = utcnow()
    run.summary_json = {
        "endpoint_url": payload.endpoint_url,
        "sites": report.by_kind(),
        "agents_proposed": [agent.slug],
        "policies_proposed": created_policies,
    }
    session.flush()
    chain.append(
        session,
        "integration.hosted_api.scanned",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="scan_run",
        subject_id=run.id,
        payload={"endpoint": payload.endpoint_url, **run.summary_json},
    )
    session.commit()
    return {
        "scan_run_id": run.id,
        "status": run.status,
        "summary": run.summary_json,
        "agent": agent.slug,
    }


# ---------------------------------------------------------------------------
# Review — approve promotes a draft to live; reject discards it. Neither
# re-runs registration/policy logic, they only flip the review state.
# ---------------------------------------------------------------------------


@router.post("/api/agents/{agent_id}/approve")
def approve_agent(
    agent_id: str, session: Session = Depends(db), user: User = Depends(require("registry"))
) -> dict[str, Any]:
    from agentfox.core.models import Agent

    agent = session.get(Agent, agent_id)
    if agent is None or agent.status != "draft":
        raise HTTPException(404, "no draft agent with that id")
    agent.status = "active"
    agent.registered = True
    session.flush()
    chain.append(
        session,
        "agent.draft.approved",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="agent",
        subject_id=agent.id,
    )
    session.commit()
    return {"id": agent.id, "status": agent.status}


@router.post("/api/agents/{agent_id}/reject")
def reject_agent(
    agent_id: str, session: Session = Depends(db), user: User = Depends(require("registry"))
) -> dict[str, Any]:
    from agentfox.core.models import Agent

    agent = session.get(Agent, agent_id)
    if agent is None or agent.status != "draft":
        raise HTTPException(404, "no draft agent with that id")
    agent.status = "rejected"
    session.flush()
    chain.append(
        session,
        "agent.draft.rejected",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="agent",
        subject_id=agent.id,
    )
    session.commit()
    return {"id": agent.id, "status": agent.status}


@router.post("/api/policies/{policy_id}/approve")
def approve_policy(
    policy_id: str, session: Session = Depends(db), user: User = Depends(require("policy"))
) -> dict[str, Any]:
    policy = session.get(Policy, policy_id)
    if policy is None or not policy.proposed:
        raise HTTPException(404, "no proposed policy with that id")
    policy.proposed = False
    session.flush()
    chain.append(
        session,
        "policy.draft.approved",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="policy",
        subject_id=policy.id,
    )
    session.commit()
    return {"id": policy.id, "proposed": policy.proposed}


@router.post("/api/policies/{policy_id}/reject")
def reject_policy(
    policy_id: str, session: Session = Depends(db), user: User = Depends(require("policy"))
) -> dict[str, Any]:
    from agentfox.core.models import PolicyBinding

    policy = session.get(Policy, policy_id)
    if policy is None or not policy.proposed:
        raise HTTPException(404, "no proposed policy with that id")
    version_ids = [
        v.id
        for v in session.scalars(select(PolicyVersion).where(PolicyVersion.policy_id == policy.id))
    ]
    if version_ids:
        for binding in session.scalars(
            select(PolicyBinding).where(PolicyBinding.policy_version_id.in_(version_ids))
        ):
            session.delete(binding)
        for version in session.scalars(
            select(PolicyVersion).where(PolicyVersion.policy_id == policy.id)
        ):
            session.delete(version)
        # `PolicyVersion.policy_id` is a bare FK column with no ORM relationship() to
        # Policy, so the unit-of-work has no dependency edge telling it to delete
        # versions before the policy — it isn't ordered automatically the way a
        # declared relationship() would be. Flushing here forces the order explicitly.
        session.flush()
    session.delete(policy)
    session.flush()
    chain.append(
        session,
        "policy.draft.rejected",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="policy",
        subject_id=policy_id,
    )
    session.commit()
    return {"id": policy_id, "status": "rejected"}
