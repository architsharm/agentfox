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
  blocking — before a human has looked at it, and has no rules yet.

Approving a proposal therefore doesn't grant capability the platform didn't already
have; it just clears the review flag.
"""

from __future__ import annotations

import json
import logging
import secrets
import tempfile
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db, require
from agentfox.capabilities.discovery.openapi import SpecFetchError, fetch_spec, scan_spec
from agentfox.capabilities.discovery.repo import ScanReport
from agentfox.capabilities.discovery.repo import scan as discovery_scan
from agentfox.capabilities.monitoring import github as gh
from agentfox.capabilities.monitoring.service import request_run, safe_ensure_monitor
from agentfox.capabilities.monitoring.snapshots import api_snapshot, repo_snapshot
from agentfox.core import ids
from agentfox.core.config import (
    PUBLISHED_SECRET_VALUES,
    get_settings,
    is_development,
)
from agentfox.core.crypto import EncryptionNotConfigured, decrypt_secret, encrypt_secret
from agentfox.core.models import (
    ApiToken,
    GithubConnection,
    Monitor,
    Policy,
    PolicyVersion,
    ScanRun,
    User,
    utcnow,
)
from agentfox.core.tenancy import bind_session, system_scope
from agentfox.platform.identity.operators import issue_token, resolve_token_record, revoke_token
from agentfox.platform.ledger import chain
from agentfox.platform.policy import PolicyDocument, save_policy
from agentfox.platform.registry.service import propose_from_scan, register_agent, slugify

log = logging.getLogger(__name__)

router = APIRouter(tags=["integrations"])

_GITHUB_API = gh.GITHUB_API


# ---------------------------------------------------------------------------
# Token encryption — a connected GitHub account's access token, at rest.
# ---------------------------------------------------------------------------


def _fernet() -> Fernet:
    key = get_settings().token_encryption_key
    if not key:
        raise HTTPException(
            503,
            "GitHub connect is not configured on this deployment "
            "(AGENTFOX_TOKEN_ENCRYPTION_KEY is unset) — fails closed rather than "
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
#: a token (the raw value is never stored, so an old one cannot be handed back); without
#: a cap every sign-in would add another 365-day credential that nothing ever
#: retires. Past the cap the oldest are revoked: a browser that has not signed in for
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
        from agentfox.capabilities.compliance.catalog import sync_catalog, sync_obligations

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
    """Download and unpack a repository (`monitoring.github`, shared with the
    `github_repo` monitor so a scheduled rescan reads it the way this scan did)."""
    try:
        return gh.download_and_extract(repo_full_name, ref, token, dest)
    except gh.RepoFetchError as exc:
        if exc.too_large:
            raise HTTPException(413, str(exc)) from exc
        raise HTTPException(502, str(exc)) from exc


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

    # From now on this repository is re-scanned on a schedule (and on push, once the
    # webhook is registered), diffed against what this scan saw.
    monitor = None
    if not report.inconclusive:
        monitor = safe_ensure_monitor(
            session,
            kind="github_repo",
            target=payload.repo_full_name,
            config={"connection_id": conn.id, **({"ref": payload.ref} if payload.ref else {})},
            baseline=repo_snapshot(report),
            created_by=user.email or user.id,
        )

    run.status = "completed"
    run.completed_at = utcnow()
    run.summary_json = {
        "monitor_id": monitor.id if monitor else None,
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
# Push webhook — a push to a monitored repository's default branch queues an
# immediate rescan of exactly that commit, instead of waiting for the schedule.
# ---------------------------------------------------------------------------

#: GitHub caps a delivery at 25 MB; a push payload is far smaller. Past this the body
#: is refused before it is parsed.
_MAX_WEBHOOK_BYTES = 5 * 1024 * 1024


async def _raw_body(request: Request) -> bytes:
    return await request.body()


def _connection_secret(session: Session, org_id: str, connection_id: str | None) -> str | None:
    """The webhook secret of the tenant's connection, read inside the caller's system
    scope (so filtered by org explicitly)."""
    query = select(GithubConnection).where(GithubConnection.org_id == org_id)
    if connection_id:
        query = query.where(GithubConnection.id == connection_id)
    conn = session.scalar(query.order_by(GithubConnection.created_at.desc()))
    if conn is None or not conn.webhook_secret_encrypted:
        return None
    try:
        return decrypt_secret(conn.webhook_secret_encrypted)
    except Exception:  # noqa: BLE001 - an unreadable secret verifies nothing
        log.warning("github webhook: connection %s secret could not be decrypted", conn.id)
        return None


def _run_queued_job(job_id: str, org_id: str) -> None:
    """Run a queued rescan after the response is sent. Best effort: on a platform that
    freezes the process after responding, the cron runner picks the job up instead."""
    from agentfox.core.db import session_scope
    from agentfox.core.models import Job
    from agentfox.platform.jobs import store as jobs_db

    try:
        with session_scope() as background:
            bind_session(background, org_id)
            job = background.get(Job, job_id)
            if job is not None:
                jobs_db.run_job(background, job)
    except Exception:  # noqa: BLE001 - the job row records its own failure
        log.warning("github webhook: rescan job %s could not run inline", job_id, exc_info=True)


@router.post("/api/integrations/github/webhook", status_code=202)
def github_webhook(
    background: BackgroundTasks,
    body: bytes = Depends(_raw_body),
    session: Session = Depends(db),
    x_github_event: Annotated[str | None, Header()] = None,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """GitHub push webhook: a signed push to a monitored repository queues a rescan.

    ``X-Hub-Signature-256`` is verified first; then each monitor of the pushed
    repository whose tenant's secret signed the delivery gets a rescan of the commit.

    Register it on the repository (or organisation) with payload URL
    ``https://<api host>/api/integrations/github/webhook``, content type
    ``application/json``, the ``push`` event, and as secret either the deployment's
    ``AGENTFOX_GITHUB_WEBHOOK_SECRET`` or the one ``POST
    /api/integrations/github/webhook-secret`` returned for the connection. A delivery
    is acted on only for the tenants whose secret signed it.
    """
    if len(body) > _MAX_WEBHOOK_BYTES:
        raise HTTPException(413, "webhook payload too large")
    try:
        event = json.loads(body or b"{}")
    except ValueError as exc:
        raise HTTPException(400, "webhook body is not JSON") from exc
    if not isinstance(event, dict):
        raise HTTPException(400, "webhook body is not a JSON object")
    repository = event.get("repository") if isinstance(event.get("repository"), dict) else {}
    full_name = str(repository.get("full_name") or "")

    global_secret = get_settings().github_webhook_secret or ""
    global_ok = gh.verify_signature(global_secret, body, x_hub_signature_256)
    verified: list[Monitor] = []
    any_secret = bool(global_secret)
    with system_scope("github webhook: finding the monitors of a pushed repository", routine=True):
        candidates = (
            list(
                session.scalars(
                    select(Monitor).where(
                        Monitor.kind == "github_repo",
                        func.lower(Monitor.target) == full_name.lower(),
                    )
                )
            )
            if full_name
            else []
        )
        for monitor in candidates:
            secret = _connection_secret(
                session, monitor.org_id, (monitor.config_json or {}).get("connection_id")
            )
            any_secret = any_secret or bool(secret)
            if global_ok or (secret and gh.verify_signature(secret, body, x_hub_signature_256)):
                verified.append(monitor)
    if not any_secret:
        raise HTTPException(
            503,
            "no GitHub webhook secret is configured (AGENTFOX_GITHUB_WEBHOOK_SECRET, or "
            "POST /api/integrations/github/webhook-secret) — deliveries are refused",
        )
    if not global_ok and not verified:
        raise HTTPException(401, "invalid or missing X-Hub-Signature-256")

    kind = (x_github_event or "").lower()
    if kind == "ping":
        return {"accepted": True, "event": "ping", "monitors": len(verified)}
    if kind != "push":
        return {"accepted": False, "event": kind, "reason": "only push events trigger a rescan"}
    if event.get("deleted"):
        return {"accepted": False, "event": kind, "reason": "a branch deletion is not a change"}

    pushed_branch = str(event.get("ref") or "").removeprefix("refs/heads/")
    default_branch = str(repository.get("default_branch") or "")
    commit = str(event.get("after") or "") or None
    queued: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for monitor in verified:
        bind_session(session, monitor.org_id)
        config = monitor.config_json or {}
        watched = str(config.get("branch") or config.get("ref") or default_branch)
        if not monitor.enabled:
            skipped.append({"monitor_id": monitor.id, "reason": "paused"})
            continue
        if pushed_branch != watched:
            skipped.append(
                {
                    "monitor_id": monitor.id,
                    "reason": f"push to '{pushed_branch}', watching '{watched}'",
                }
            )
            continue
        job = request_run(session, monitor, trigger="push", ref=commit, requested_by="github:push")
        queued.append({"monitor_id": monitor.id, "job_id": job.id, "org_id": monitor.org_id})
    session.commit()
    for item in queued:
        background.add_task(_run_queued_job, item["job_id"], item["org_id"])
    return {
        "accepted": bool(queued),
        "event": kind,
        "commit": commit,
        "queued": [{"monitor_id": q["monitor_id"], "job_id": q["job_id"]} for q in queued],
        "skipped": skipped,
    }


@router.post("/api/integrations/github/webhook-secret")
def rotate_webhook_secret(
    session: Session = Depends(db), user: User = Depends(require("registry"))
) -> dict[str, Any]:
    """Create or replace the GitHub connection's push-webhook secret (shown once).

    Paste it into the GitHub webhook's "Secret" field."""
    conn = _get_connection(session)
    if conn is None:
        raise HTTPException(404, "no GitHub account connected")
    raw = secrets.token_urlsafe(32)
    try:
        conn.webhook_secret_encrypted = encrypt_secret(raw)
    except EncryptionNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    session.flush()
    chain.append(
        session,
        "integration.github.webhook_secret_rotated",
        actor_type="user",
        actor_id=user.email or user.id,
        subject_type="github_connection",
        subject_id=conn.id,
    )
    session.commit()
    return {
        "secret": raw,
        "payload_path": "/api/integrations/github/webhook",
        "content_type": "application/json",
        "events": ["push"],
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

    spec: dict[str, Any] | None = None
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

    monitor = None
    if payload.openapi_spec_url and isinstance(spec, dict):
        monitor = safe_ensure_monitor(
            session,
            kind="hosted_api",
            target=payload.openapi_spec_url,
            name=host,
            config={"endpoint_url": payload.endpoint_url, "agent": slug},
            baseline=api_snapshot(spec),
            created_by=user.email or user.id,
        )

    run.status = "completed"
    run.completed_at = utcnow()
    run.summary_json = {
        "monitor_id": monitor.id if monitor else None,
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
