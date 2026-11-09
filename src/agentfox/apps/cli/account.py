"""Which store a CLI command reads and writes: your AgentFox account, or this machine.

One key everywhere (the Sentry model): with ``AGENTFOX_URL`` and ``AGENTFOX_API_KEY``
in the environment, or the ``.agentfox/agentfox.env`` that ``agentfox init --key``,
``agentfox up`` and ``agentfox login`` write, ``agentfox.auto()`` reports to the
account, and so do the CLI commands that read or change what the dashboard shows
(``findings``, ``agents list``, ``permit``, ``declare``, ``policy``, ``report``,
``test suites``). They go through the gateway's own API routes with that key, the
same routes the dashboard uses, so the CLI and the UI never disagree.

Without a key they use this machine's database, as before. An explicit
``AGENTFOX_DATABASE_URL`` (a self-hosted team pointing the CLI straight at its
Postgres) also keeps the direct database path: that is the same data the gateway
reads, so there is nothing to route.

Each such command prints one line saying which it is using, so "No open findings"
on a laptop is never mistaken for the account's answer. The line goes to stderr and
is left out of ``--json`` output, so scripts read clean JSON.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.markup import escape

from agentfox.apps.cli.wizard.backend import BackendError, Remote

#: Where the line saying which store a command uses goes: never into stdout, which a
#: script may be parsing.
_status = Console(stderr=True)

#: Set to 1 to make the CLI use this machine's database although a key is configured.
LOCAL_ENV_VAR = "AGENTFOX_LOCAL"

#: The page a key is made on. Cloud's dashboard is `wizard.targets.CLOUD_APP_URL`.
KEY_STEP = "Get started → Create a key"


class AccountError(Exception):
    """The account could not answer. The message is one line, for a person."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def keys_page(server: str) -> str:
    """Where a key for ``server`` is made, as a sentence fragment."""
    from agentfox.apps.cli.commands._shared import dashboard_url
    from agentfox.apps.cli.wizard.targets import CLOUD_APP_URL

    site = dashboard_url()
    if not site and "useagentfox.com" in server:
        site = CLOUD_APP_URL
    where = f" ({site}/app/start)" if site else " in the AgentFox dashboard"
    return f"{KEY_STEP}{where}"


def key_rejected(server: str, status: int = 401) -> str:
    """The one line for a key the server refused."""
    return (
        f"{server} rejected your AgentFox key ({status}): it is wrong, revoked or expired. "
        f"Make a new one on {keys_page(server)}, then run `agentfox login`."
    )


@dataclass
class Account:
    """An AgentFox account reached over its gateway with a workspace key."""

    url: str
    key: str
    #: Where the key came from, for `doctor`: "environment" or the env file's path.
    origin: str = "environment"
    _me: dict[str, Any] | None = field(default=None, repr=False)
    _remote: Remote | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.url = self.url.rstrip("/")

    @property
    def remote(self) -> Remote:
        if self._remote is None:
            self._remote = Remote(self.url, self.key)
        return self._remote

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.remote._client.request(
                method, f"{self.url}{path}", headers=self.remote._headers, **kwargs
            )
        except httpx.HTTPError as exc:
            raise AccountError(
                f"could not reach your AgentFox account at {self.url} "
                f"({type(exc).__name__}). Check AGENTFOX_URL and your network."
            ) from None
        if response.status_code == 401:
            raise AccountError(key_rejected(self.url), 401)
        if response.status_code >= 400:
            raise AccountError(_detail(response), response.status_code)
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"text": response.text}

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None})

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, json=body or {})

    def patch(self, path: str, body: dict[str, Any]) -> Any:
        return self.request("PATCH", path, json=body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    def me(self) -> dict[str, Any]:
        """Who the key belongs to (``GET /api/me``): email, role, workspace."""
        if self._me is None:
            self._me = self.get("/api/me")
        return self._me

    @property
    def label(self) -> str:
        me = self.me()
        return f"Account: {self.url} (workspace {me.get('workspace') or me.get('org_id')})"


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):  # FastAPI validation errors
        detail = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("detail") or str(detail)
    return str(detail or f"the account answered {response.status_code}")


def configured(root: Path | None = None) -> Account | None:
    """The account this command should use, or None for the local database.

    The key is found where `agentfox.auto()` finds it (`frameworks.autoguard.remote`):
    the environment first, then ``.agentfox/agentfox.env`` here. An explicit
    ``AGENTFOX_DATABASE_URL`` in the environment wins over both: the CLI then uses
    that database directly, which is how a self-hosted team already shares one.
    ``AGENTFOX_LOCAL=1`` says the same for this machine's database: what the
    coding-agent hooks record, in a project that is connected to an account.
    """
    if os.environ.get("AGENTFOX_DATABASE_URL") or _local_forced():
        return None
    from agentfox.frameworks.autoguard import remote

    file = remote._env_file(root)

    def pick(*names: str) -> tuple[str | None, str]:
        for source, origin in ((os.environ, "environment"), (file, str(remote.ENV_FILE))):
            for name in names:
                if source.get(name):
                    return source[name], origin
        return None, ""

    url, _ = pick("AGENTFOX_URL", "AGENTFOX_API_URL")
    key, origin = pick("AGENTFOX_API_KEY", "AGENTFOX_API_TOKEN")
    if not (url and key):
        return None
    return Account(url=url, key=key, origin=origin)


def _local_forced() -> bool:
    return os.environ.get(LOCAL_ENV_VAR, "").strip().lower() in ("1", "true", "yes", "on")


def local_label() -> str:
    """The database a local command uses, for people (password hidden)."""
    from agentfox.core.config import get_settings

    raw = get_settings().database_url
    if raw.startswith("sqlite:///"):
        path = Path(raw.removeprefix("sqlite:///"))
        try:
            shown = "~/" + str(path.relative_to(Path.home()))
        except ValueError:
            shown = str(path)
        return f"Local: {shown}"
    try:
        from sqlalchemy.engine import make_url

        raw = make_url(raw).render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001 - only a label
        raw = raw.split("@")[-1]
    return f"Database: {raw}"


def fail(console: Console, exc: AccountError) -> None:
    """Print the account's one-line answer and stop with exit code 1."""
    console.print(f"[red]{escape(str(exc))}[/]")
    raise typer.Exit(1)


def use(console: Console | None = None, *, quiet: bool = False) -> Account | None:
    """The account a command should use, after saying which store it is (unless
    ``quiet``, for ``--json``). Verifies the key on the way: a rejected key stops
    the command with one line naming the fix, never a traceback."""
    account = configured()
    console = console or Console()
    if account is None:
        if not quiet:
            hint = (
                ""
                if os.environ.get("AGENTFOX_DATABASE_URL") or _local_forced()
                else " (`agentfox login` to use your account)"
            )
            _status.print(f"[dim]{escape(local_label())}{hint}[/]", soft_wrap=True)
        return None
    try:
        label = account.label
    except AccountError as exc:
        fail(console, exc)
    if not quiet:
        _status.print(f"[dim]{escape(label)}[/]", soft_wrap=True)
    return account


__all__ = [
    "Account",
    "AccountError",
    "BackendError",
    "configured",
    "fail",
    "key_rejected",
    "keys_page",
    "local_label",
    "use",
]
