"""Where AgentFox runs: this machine, a server you host, or AgentFox Cloud.

The first question `agentfox up` asks, because every later step depends on it.
Each target ends in a `Backend` the steps write through, plus the addresses the
integrations need (the gateway for model traffic, the dashboard for people).

* **local** — this machine. SQLite unless `AGENTFOX_DATABASE_URL` says otherwise;
  nothing leaves it. The open core, plus AgentFox Enterprise if it is installed.
* **self-hosted** — your own infrastructure. Either `up` starts the published images
  here with Docker Compose (Postgres, gateway, dashboard) and creates the first
  operator, or it connects to one already running with an API key.
* **cloud** — AgentFox Cloud. An API key from the workspace's Settings page; the
  Enterprise features (compliance, evidence, monitoring) come with it.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from rich.console import Console

from agentfox.apps.cli.wizard.backend import Backend, BackendError, Local, Remote
from agentfox.apps.cli.wizard.detect import STATE_DIR, Context, git_ignore, read_env
from agentfox.apps.cli.wizard.prompt import Choice, Prompter

#: AgentFox Cloud's web app. Overridable for a staging workspace.
CLOUD_APP_URL = os.environ.get("AGENTFOX_CLOUD_URL", "https://useagentfox.com").rstrip("/")
LOCAL_API_URL = "http://127.0.0.1:8080"
SELFHOST_API_URL = "http://localhost:8080"
SELFHOST_DASHBOARD_URL = "http://localhost:3000"

TARGETS = (
    Choice(
        "local",
        "This machine",
        "SQLite, nothing leaves it. Best for trying it and for one developer.",
    ),
    Choice(
        "self-hosted",
        "Self-hosted",
        "Your own server: Postgres, gateway and dashboard with Docker, or one already running.",
    ),
    Choice(
        "cloud",
        "AgentFox Cloud",
        "Hosted. Compliance, evidence and monitoring included. Needs an API key.",
    ),
)


@dataclass
class Target:
    key: str
    backend: Backend
    #: Where model traffic and `/v1/guard/*` go.
    api_url: str
    #: The dashboard's site root (pages are under /app); empty when there is no web UI.
    dashboard_url: str = ""
    #: Values for `.agentfox/agentfox.env`.
    env: dict[str, str] = field(default_factory=dict)
    #: Said once in the summary.
    notes: list[str] = field(default_factory=list)

    @property
    def remote(self) -> bool:
        return self.backend.kind == "remote"


class TargetError(Exception):
    pass


def choose(
    ctx: Context,
    prompter: Prompter,
    console: Console,
    *,
    target: str | None,
    api_url: str | None,
    api_token: str | None,
    email: str | None,
    start: bool,
) -> Target:
    saved = ctx.saved
    key = target or prompter.select(
        "Where will AgentFox run?", TARGETS, saved.get("target", "local")
    )
    if key == "local":
        return Target("local", Local(), LOCAL_API_URL)
    if key == "cloud":
        return _cloud(ctx, prompter, console, api_url=api_url, api_token=api_token)
    if key == "self-hosted":
        return _self_hosted(
            ctx, prompter, console, api_url=api_url, api_token=api_token, email=email, start=start
        )
    raise TargetError(f"unknown target {key!r}: choose local, self-hosted or cloud")


def _saved_token(ctx: Context) -> str:
    return read_env(ctx.root).get("AGENTFOX_API_TOKEN") or os.environ.get("AGENTFOX_API_TOKEN", "")


def _connect(url: str, token: str, console: Console) -> Remote:
    if not url or not token:
        raise TargetError(
            "connecting needs the gateway address and an API key: answer both, or pass "
            "--api-url and --api-token"
        )
    backend = Remote(url, token)
    try:
        me = backend.whoami()
    except BackendError as exc:
        raise TargetError(str(exc)) from exc
    console.print(
        f"  [green]✓[/] connected to [bold]{backend.where}[/] as {me.get('email') or me.get('id')}"
        f" [dim]({me.get('role')}, workspace {me.get('workspace')})[/]"
    )
    return backend


def _cloud(
    ctx: Context,
    prompter: Prompter,
    console: Console,
    *,
    api_url: str | None,
    api_token: str | None,
) -> Target:
    keys_page = f"{CLOUD_APP_URL}/app/start?tab=tokens"
    console.print(
        f"\n  Create an API key at [link={keys_page}]{keys_page}[/link] — the same page shows "
        "your workspace's gateway address."
    )
    url = api_url or prompter.text(
        "Gateway address",
        ctx.saved.get("api_url") or os.environ.get("AGENTFOX_API_URL", ""),
    )
    token = api_token or prompter.text("API key", _saved_token(ctx), secret=True)
    backend = _connect(url, token, console)
    return Target(
        "cloud",
        backend,
        backend.where,
        dashboard_url=CLOUD_APP_URL,
        env={"AGENTFOX_API_URL": backend.where, "AGENTFOX_API_TOKEN": token},
    )


_SELFHOST_MODES = (
    Choice(
        "docker", "Start it here with Docker", "Postgres, gateway and dashboard, published images."
    ),
    Choice("connect", "Connect to one that is running", "Needs its URL and an API key."),
)


def _self_hosted(
    ctx: Context,
    prompter: Prompter,
    console: Console,
    *,
    api_url: str | None,
    api_token: str | None,
    email: str | None,
    start: bool,
) -> Target:
    default = "connect" if (api_url or ctx.saved.get("api_url")) else "docker"
    if not ctx.docker and not api_url:
        default = "connect"
    how = (
        "connect"
        if api_url
        else prompter.select("Is it already running?", _SELFHOST_MODES, default)
    )
    if how == "connect":
        url = api_url or prompter.text(
            "Gateway address", ctx.saved.get("api_url") or os.environ.get("AGENTFOX_API_URL", "")
        )
        token = api_token or prompter.text(
            "API key (agentfox admin auth issue <email> on that server)",
            _saved_token(ctx),
            secret=True,
        )
        backend = _connect(url, token, console)
        dashboard = prompter.text(
            "Dashboard address, if your team runs one (Enter to skip)",
            ctx.saved.get("dashboard_url") or "",
        )
        return Target(
            "self-hosted",
            backend,
            backend.where,
            dashboard_url=dashboard.rstrip("/"),
            env={"AGENTFOX_API_URL": backend.where, "AGENTFOX_API_TOKEN": token},
        )

    if not ctx.docker:
        raise TargetError(
            "Docker is not on this machine's PATH. Install Docker, or choose "
            "“Connect to one that is running”."
        )
    operator = email or prompter.text(
        "Email for the first operator (the owner account)",
        ctx.saved.get("email") or os.environ.get("AGENTFOX_ADMIN_EMAIL", "admin@example.com"),
    )
    compose = write_compose(ctx.root)
    console.print(
        f"  [green]✓[/] wrote {compose.relative_to(ctx.root)} and its secrets (.env, 0600)"
    )
    if not start:
        raise TargetError(
            f"--no-start: run `docker compose -f {compose} up -d` and then `agentfox up` "
            "again to connect"
        )
    token = _compose_up(compose, operator, console, prompter)
    backend = _connect(SELFHOST_API_URL, token, console)
    return Target(
        "self-hosted",
        backend,
        backend.where,
        dashboard_url=SELFHOST_DASHBOARD_URL,
        env={"AGENTFOX_API_URL": backend.where, "AGENTFOX_API_TOKEN": token},
        notes=[
            f"Sign in to the dashboard at {SELFHOST_DASHBOARD_URL}/login with the API key "
            "in .agentfox/agentfox.env (“Self-hosted? Sign in with an API token”).",
            f"Stop it: docker compose -f {compose.relative_to(ctx.root)} down",
        ],
    )


# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------

#: The self-hosted stack, trimmed from deploy/docker-compose.yml to what runs from the
#: published images: no build contexts (a pip install has no source tree), no OPA.
COMPOSE = """\
# Written by `agentfox up`. The full, commented version is deploy/docker-compose.yml
# in the AgentFox repository. Secrets are in .env beside this file.
name: agentfox

services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: agentfox
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?}
      POSTGRES_DB: agentfox
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agentfox"]
      interval: 5s
      timeout: 3s
      retries: 20

  gateway:
    image: ghcr.io/architsharm/agentfox/gateway:latest
    environment:
      AGENTFOX_DATABASE_URL: postgresql+psycopg://agentfox:${POSTGRES_PASSWORD}@db:5432/agentfox
      AGENTFOX_ORG_ID: org_default
      AGENTFOX_ENVIRONMENT: production
      AGENTFOX_ALLOW_EGRESS: "false"
      AGENTFOX_DEFAULT_PROVIDER: echo
      AGENTFOX_DEFAULT_POLICY_MODE: observe
      AGENTFOX_FAIL_MODE: open
      AGENTFOX_AUDIT_SIGNING_KEY: ${AGENTFOX_AUDIT_SIGNING_KEY:?}
      AGENTFOX_SERVICE_AUTH_SECRET: ${AGENTFOX_SERVICE_AUTH_SECRET:?}
      AGENTFOX_EVIDENCE_DIR: /var/agentfox/evidence
      AGENTFOX_PLAYGROUND_CORS_ORIGIN: http://localhost:3000
    ports:
      - "8080:8080"
    volumes:
      - evidence:/var/agentfox/evidence
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request;urllib.request.urlopen('http://localhost:8080/api/health')"]
      interval: 10s
      timeout: 5s
      retries: 10

  dashboard:
    image: ghcr.io/architsharm/agentfox/dashboard:latest
    environment:
      AGENTFOX_API_URL: http://gateway:8080
      AGENTFOX_SERVICE_AUTH_SECRET: ${AGENTFOX_SERVICE_AUTH_SECRET:?}
      AGENTFOX_PLAYGROUND_API_URL: http://localhost:8080
      GITHUB_CLIENT_ID: ${GITHUB_CLIENT_ID:-}
      GITHUB_CLIENT_SECRET: ${GITHUB_CLIENT_SECRET:-}
    ports:
      - "3000:3000"
    depends_on:
      gateway:
        condition: service_healthy

volumes:
  db-data:
  evidence:
"""

#: Creates the first operator (or reuses them) and prints a fresh token as JSON. Run
#: inside the gateway container, so it uses that deployment's database and settings.
_FIRST_OPERATOR = """
import json, sys
from sqlalchemy import select
from agentfox.core.db import init_db, session_scope
from agentfox.core.models import User
from agentfox.core.tenancy import bind_session, system_scope
from agentfox.platform.identity.operators import create_operator, issue_token

init_db()
email = sys.argv[1]
with system_scope("agentfox up: first operator"), session_scope() as session:
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = create_operator(session, email, role="owner")
    bind_session(session, user.org_id)
    _record, raw = issue_token(session, user, name="agentfox-up")
print(json.dumps({"token": raw}))
"""


def write_compose(root: Path) -> Path:
    directory = root / STATE_DIR / "selfhost"
    directory.mkdir(parents=True, exist_ok=True)
    compose = directory / "docker-compose.yml"
    compose.write_text(COMPOSE)
    env = directory / ".env"
    if not env.exists():  # regenerating would orphan the database and the audit chain
        body = "\n".join(
            [
                "# Generated by `agentfox up`. Keep a copy of the signing key: it is what",
                "# makes the audit chain verifiable.",
                f"POSTGRES_PASSWORD={secrets.token_hex(16)}",
                f"AGENTFOX_AUDIT_SIGNING_KEY={secrets.token_hex(32)}",
                f"AGENTFOX_SERVICE_AUTH_SECRET={secrets.token_hex(32)}",
                "",
            ]
        )
        fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(body)
    git_ignore(root, f"{STATE_DIR}/selfhost/.env")
    return compose


GATEWAY_IMAGE = "ghcr.io/architsharm/agentfox/gateway:latest"
#: The published gateway image carries the detector models' weights, so the first start
#: downloads this much. Said before it starts, not discovered halfway through.
GATEWAY_IMAGE_SIZE = "about 14 GB"


def _port_taken(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _stack_running(base: list[str]) -> bool:
    """This compose project's gateway is already up (a second `agentfox up`)."""
    out = subprocess.run(
        [*base, "ps", "--status", "running", "--services"], capture_output=True, text=True
    )
    return "gateway" in out.stdout.split()


def _compose_up(compose: Path, email: str, console: Console, prompter: Prompter) -> str:
    base = ["docker", "compose", "-f", str(compose)]
    down = f"docker compose -f {compose} down"
    if not _stack_running(base):
        for port, what in ((8080, "gateway"), (3000, "dashboard")):
            if _port_taken(port):
                raise TargetError(
                    f"port {port} (the {what}) is already in use on this machine. A local "
                    "`agentfox serve` from an earlier `agentfox up` (its pid is in "
                    ".agentfox/serve.pid) is the usual one: stop it, or choose “Connect to "
                    "one that is running” to use what is listening there."
                )
        pulled = (
            subprocess.run(
                ["docker", "image", "inspect", GATEWAY_IMAGE], capture_output=True
            ).returncode
            == 0
        )
        if not pulled:
            console.print(
                f"  [yellow]The first start downloads the gateway image, {GATEWAY_IMAGE_SIZE}[/] "
                "[dim](it carries the detector models, so nothing is fetched at runtime).[/]"
            )
            if not prompter.confirm("Download it now?", default=True):
                raise TargetError(
                    f"not started. `docker compose -f {compose} pull` downloads it whenever "
                    "you like; then run `agentfox up` again."
                )
    console.print("  [dim]starting Postgres, the gateway and the dashboard…[/]")
    result = subprocess.run([*base, "up", "-d"], capture_output=True, text=True)
    if result.returncode != 0:
        raise TargetError(
            f"docker compose up failed:\n{result.stderr.strip()[-800:]}\n"
            f"Clean up what started with `{down}`."
        )
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{SELFHOST_API_URL}/api/health", timeout=3).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(3)
    else:
        raise TargetError(
            "the gateway did not become healthy in 5 minutes — "
            f"`docker compose -f {compose} logs gateway`"
        )
    console.print(f"  [green]✓[/] gateway healthy at {SELFHOST_API_URL}")
    # The image only serves: the control catalog and the shipped policy packs are loaded
    # by `init`, which is idempotent, so a restarted or re-run stack is left as it is.
    loaded = subprocess.run(
        [
            *base,
            "exec",
            "-T",
            "gateway",
            "agentfox",
            "init",
            "--env",
            "production",
            "--path",
            "/tmp",
        ],
        capture_output=True,
        text=True,
    )
    if loaded.returncode != 0:
        raise TargetError(
            "could not load the policy packs into the gateway:\n"
            + (loaded.stderr or loaded.stdout).strip()[-800:]
        )
    console.print("  [green]✓[/] control catalog and policy packs loaded")
    minted = subprocess.run(
        [*base, "exec", "-T", "gateway", "python", "-", email],
        input=_FIRST_OPERATOR,
        capture_output=True,
        text=True,
    )
    try:
        token = json.loads(minted.stdout.strip().splitlines()[-1])["token"]
    except (IndexError, KeyError, ValueError):
        raise TargetError(
            "could not create the first operator:\n"
            + (minted.stderr or minted.stdout).strip()[-800:]
        ) from None
    console.print(f"  [green]✓[/] first operator {email} (owner) with an API key")
    return token
