"""AgentFox for Hermes Agent: check every tool call against AgentFox before it runs.

Hermes calls ``pre_tool_call`` before each tool, built-in or plugin. This plugin sends the
call to an AgentFox gateway's ``POST /v1/guard/tool_call`` and turns the applied verdict
into Hermes's own directive: nothing (run it), ``block`` with the rule's message, or, for a
held call, a block that points at the approver in AgentFox (or Hermes's own approval gate
with ``AGENTFOX_APPROVALS=hermes``).

Provenance: ``pre_tool_call`` does not see the conversation, so ``post_tool_call`` keeps
the last few tool results of each conversation and they go along as ``messages``. The
gateway then finds an argument's value in them, so a command or address copied out of a
fetched page is treated as untrusted, not as the user's.

Settings come from the environment (Hermes loads ``~/.hermes/.env``):

  AGENTFOX_URL          the gateway, e.g. http://localhost:8080 (required)
  AGENTFOX_AGENT_KEY    an agent key (nom_agt_...); without one, calls are unregistered traffic
  AGENTFOX_AGENT        the agent's slug in AgentFox (default ``hermes``)
  AGENTFOX_FAIL_MODE    ``closed`` (default) blocks a call AgentFox cannot check; ``open`` runs it
  AGENTFOX_APPROVALS    ``agentfox`` (default) or ``hermes`` (Hermes's own approval gate)
  AGENTFOX_TIMEOUT      seconds to wait for AgentFox (default 10; Hermes allows a hook 30)
"""

from __future__ import annotations

import json
import os
from collections import OrderedDict
from typing import Any

#: Verdicts that stop a call, as the gateway defines them.
STOPPING = {"block", "escalate", "abstain"}
#: Cap on one remembered tool result, so a large page cannot balloon every request.
MAX_RESULT_CHARS = 8_000
#: Conversations remembered at once; the oldest is dropped first.
MAX_SESSIONS = 500


class Guard:
    def __init__(
        self,
        url: str,
        key: str = "",
        *,
        agent: str = "hermes",
        fail_mode: str = "closed",
        approvals: str = "agentfox",
        timeout: float = 10.0,
        results_kept: int = 20,
        remote: Any = None,
    ) -> None:
        if remote is None:
            if not url:
                raise ValueError("agentfox: set AGENTFOX_URL to your AgentFox gateway")
            from agentfox.frameworks.autoguard.remote import Remote

            # A non-nom_agt_ key reads as "no key" to the gateway: unregistered traffic.
            remote = Remote(url, key or "unregistered", timeout=timeout)
        self.remote = remote
        self.agent = agent
        self.fail_open = fail_mode == "open"
        self.approvals = approvals
        self.kept = max(0, results_kept)
        self.results: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()

    @classmethod
    def from_env(cls) -> Guard:
        env = os.environ.get
        return cls(
            env("AGENTFOX_URL", ""),
            env("AGENTFOX_AGENT_KEY") or env("AGENTFOX_API_KEY", ""),
            agent=env("AGENTFOX_AGENT") or "hermes",
            fail_mode=env("AGENTFOX_FAIL_MODE") or "closed",
            approvals=env("AGENTFOX_APPROVALS") or "agentfox",
            timeout=float(env("AGENTFOX_TIMEOUT") or 10),
        )

    @staticmethod
    def _session(kw: dict[str, Any]) -> str | None:
        # conversation_id survives compression and is shared with delegated subagents.
        return kw.get("conversation_id") or kw.get("session_id") or kw.get("task_id") or None

    def pre_tool_call(self, tool_name: str = "", args: Any = None, **kw: Any) -> dict | None:
        session = self._session(kw)
        body = {
            "agent": self.agent,
            "tool": tool_name,
            "arguments": args if isinstance(args, dict) else {"_value": args},
            "provenance": {},
            # Register a tool the first time AgentFox sees it, instead of holding it as unknown.
            "declare": {"name": tool_name},
            # Hermes cannot carry an approval id back on a retry: a call an approver
            # granted in AgentFox runs once when retried unchanged.
            "redeem_approved": self.approvals == "agentfox",
            "in_process": "enforced",
        }
        if session:
            body["session_id"] = session
            if self.results.get(session):
                body["messages"] = self.results[session]
        try:
            decision = self.remote.post("/v1/guard/tool_call", body)
        except Exception as exc:  # noqa: BLE001 - any failure to check is a failure to check
            if self.fail_open:
                return None
            return _block(f"AgentFox could not check this call, so it did not run ({exc}).")

        # Gate on the applied verdict: a rule still in Watch mode records what it would do.
        verdict = decision.get("verdict") or decision.get("applied_verdict") or "allow"
        if verdict not in STOPPING:
            return None
        said = (
            decision.get("user_message")
            or decision.get("reason")
            or f"AgentFox stopped {tool_name}"
        ).strip()
        why = said if said[-1:] in ".!?" else f"{said}."
        if verdict != "escalate":
            return _block(why)
        if self.approvals == "hermes":
            return {
                "action": "approve",
                "message": f"AgentFox: {why}",
                "rule_key": f"agentfox:{tool_name}",
            }
        where = (
            f" Review it: {decision['explain_url']}."
            if decision.get("explain_url")
            else " Review it in AgentFox under Approvals."
        )
        return _block(
            f"{why} This call is waiting for an approver in AgentFox.{where} "
            "Once it is approved, ask me to try again and it will run once."
        )

    def post_tool_call(self, tool_name: str = "", result: Any = None, **kw: Any) -> None:
        """Remember a finished call's result, so later arguments can be traced to it."""
        session = self._session(kw)
        if not session or self.kept == 0 or result is None:
            return
        raw = result if isinstance(result, str) else _json(result)
        if not raw:
            return
        entries = self.results.pop(session, [])  # re-inserted below as the newest
        entries.append(
            {
                "role": "tool",
                "tool_call_id": kw.get("tool_call_id") or f"{tool_name}-{len(entries)}",
                "name": tool_name,
                "content": raw[:MAX_RESULT_CHARS],
            }
        )
        del entries[: -self.kept]
        self.results[session] = entries
        if len(self.results) > MAX_SESSIONS:
            self.results.popitem(last=False)


def _block(message: str) -> dict[str, str]:
    return {"action": "block", "message": message}


def _json(value: Any) -> str:
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return ""


def register(ctx: Any) -> None:
    guard = Guard.from_env()
    ctx.register_hook("pre_tool_call", guard.pre_tool_call)
    ctx.register_hook("post_tool_call", guard.post_tool_call)
