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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from agentfox.core.jsonable import jsonable
from agentfox.runtime.enforcement import EnforcementResult

log = logging.getLogger(__name__)

ENV_FILE = Path(".agentfox") / "agentfox.env"


@dataclass
class Remote:
    url: str
    key: str
    timeout: float = 15.0

    def __post_init__(self) -> None:
        self.url = self.url.rstrip("/")
        self._client = httpx.Client(timeout=self.timeout)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        # Tool arguments and the conversation carry the framework's own objects (a
        # LangGraph tool's state holds `HumanMessage`s): sent as the JSON they mean.
        response = self._client.post(
            f"{self.url}{path}",
            json=jsonable(body),
            headers={"Authorization": f"Bearer {self.key}"},
        )
        response.raise_for_status()
        return response.json()


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
