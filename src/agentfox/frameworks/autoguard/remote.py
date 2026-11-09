"""`agentfox.auto()` reporting to an AgentFox account instead of a local database.

The Sentry model: a key that belongs to an account, in the environment. When one is
configured, every check `auto()` makes goes to that account's gateway over the same
routes the SDK and the platform hooks use (`/v1/guard/input`, `/v1/guard/output`,
`/v1/guard/tool_call`), so the calls show up on the account's dashboard. Without one,
nothing changes: `auto()` enforces in this process against the local database.

Where the key comes from, first match wins:

* ``auto(server=..., key=...)``;
* ``AGENTFOX_URL`` (or ``AGENTFOX_API_URL``) and ``AGENTFOX_API_KEY`` (or
  ``AGENTFOX_API_TOKEN``) in the environment;
* ``.agentfox/agentfox.env`` in the working directory, which ``agentfox init`` writes
  once the repository is connected to an account.

The key is a workspace API key (``nom_api_…``) or an agent key (``nom_agt_…``).

What the gateway decides is applied here exactly as a local decision is: the same
`_raises` rule per mode, the same no-grants carve-out for tool calls (the gateway
applies it when asked, ``waive_ungranted``), and escalations held for a person.
What a remote check does not do that a local one does: budget charging and the
conversation-window check, which the gateway does not expose on these routes.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from agentfox.core.jsonable import jsonable
from agentfox.runtime.enforcement import EnforcementResult

log = logging.getLogger(__name__)

ENV_FILE = Path(".agentfox") / "agentfox.env"

#: How long `auto()` waits at start to learn whether the account accepts the key.
CHECK_TIMEOUT = 3.0


class KeyRejected(RuntimeError):
    """The account refused the key. The message is the one line a person needs: what
    happened and how to fix it, never the HTTP library's text."""


def rejected_message(url: str, status: int) -> str:
    return (
        f"agentfox: {url} rejected your AgentFox key ({status}): it is wrong, revoked "
        "or expired. Make a new one in the dashboard (Get started → Create a key) and "
        "put it in AGENTFOX_API_KEY or .agentfox/agentfox.env (`agentfox login`)."
    )


@dataclass
class Remote:
    url: str
    key: str
    timeout: float = 15.0

    def __post_init__(self) -> None:
        self.url = self.url.rstrip("/")
        self._client = httpx.Client(timeout=self.timeout)
        self._told = False

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        # Tool arguments and the conversation carry the framework's own objects (a
        # LangGraph tool's state holds `HumanMessage`s): sent as the JSON they mean.
        response = self._client.post(
            f"{self.url}{path}",
            json=jsonable(body),
            headers={"Authorization": f"Bearer {self.key}"},
        )
        if response.status_code in (401, 403):
            message = rejected_message(self.url, response.status_code)
            if not getattr(self, "_told", False):
                # Once, in plain words: the failure handler that catches this logs
                # it per call, and a raw 401 with a documentation URL helped nobody.
                self._told = True
                print(message, file=sys.stderr)  # noqa: T201 - the point is to be seen
            raise KeyRejected(message)
        response.raise_for_status()
        return response.json()

    def check(self) -> str | None:
        """Whether the account will take this key, asked once at start: None when it
        does (or cannot be told), else the problem in one line. An agent key
        (``nom_agt_``) only reaches the guard routes, so it is not asked about."""
        if self.key.startswith("nom_agt_"):
            return None
        try:
            response = self._client.get(
                f"{self.url}/api/me",
                headers={"Authorization": f"Bearer {self.key}"},
                timeout=CHECK_TIMEOUT,
            )
        except httpx.TransportError as exc:
            return (
                f"agentfox: could not reach your AgentFox account at {self.url} "
                f"({type(exc).__name__}); calls follow fail_mode until it answers."
            )
        except Exception:  # noqa: BLE001 - a check, never a reason to stop the app
            return None
        if response.status_code in (401, 403):
            return rejected_message(self.url, response.status_code)
        return None


def _env_file(root: Path | None = None) -> dict[str, str]:
    path = (root or Path.cwd()) / ENV_FILE
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.removeprefix("export ").strip()] = value.strip().strip("'\"")
    return values


def configured(server: str | None = None, key: str | None = None) -> Remote | None:
    """The account to report to, or None to enforce locally."""
    file = _env_file()

    def pick(*names: str) -> str | None:
        for source in (os.environ, file):
            for name in names:
                if source.get(name):
                    return source[name]
        return None

    url = server or pick("AGENTFOX_URL", "AGENTFOX_API_URL")
    secret = key or pick("AGENTFOX_API_KEY", "AGENTFOX_API_TOKEN")
    if not (url and secret):
        return None
    return Remote(url=url, key=secret)


def result(body: dict[str, Any]) -> EnforcementResult:
    """A gateway decision as the local enforcer's result type."""
    return EnforcementResult(
        verdict=body.get("verdict", "allow"),
        effective_verdict=body.get("effective_verdict") or body.get("verdict", "allow"),
        mode=body.get("mode", "observe"),
        decision_id=body.get("decision_id"),
        trace_id=body.get("trace_id"),
        approval_id=body.get("approval_id"),
        rules_fired=body.get("rules_fired") or [],
        entities=body.get("entities") or [],
        findings=body.get("findings") or [],
        reason=body.get("reason", ""),
        content=body.get("content"),
        user_message=body.get("user_message") or "",
    )
