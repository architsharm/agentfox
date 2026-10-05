#!/usr/bin/env python3
"""PreToolUse hook: make the agent ask before an agentfox command changes what is blocked.

The product's own safety stance is "observe first; enforcement is an explicit human act".
An agent driving the CLI must not quietly break that, so every command below is turned
into a permission prompt with a plain-language reason. Anything else passes through
untouched. Stdlib only; never blocks outright; a parse failure lets the call through.
"""

from __future__ import annotations

import json
import re
import sys

# An agentfox invocation at *command position* only — so a commit message or a filename
# that merely mentions "policy enforce" is not mistaken for running it.
#   agentfox …  |  uv run [--project X] agentfox …  |  python -m agentfox.cli.main …
#   …/scripts/agentfox.sh …   (optionally preceded by VAR=value assignments)
# `nometria` is still matched as well: the console script keeps it as a compatibility
# alias, so a blocking command must prompt whichever of the two names an agent types.
_PREFIX = (
    r"^(?:\w+=\S*\s+)*"
    r"(?:(?:uv\s+run(?:\s+--\S+(?:\s+(?!agentfox\b|nometria\b)\S+)?)*\s+)"
    r"|(?:\S*python[\d.]*\s+-m\s+))?"
    r"(?:\S*/)?(?:agentfox|nometria)(?:\.cli\.main|\.sh)?\s+"
)
_END = r"(?=\s|$)"

# Each rule matches the current name and the pre-consolidation one (`proposals apply`
# and `policy proposals apply` are the same command — see src/agentfox/cli/layout.py).
CLI_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        r"policy\s+enforce" + _END,
        "promotes a policy to ENFORCE — matching production traffic starts being blocked.",
    ),
    (
        r"policy\s+observe" + _END,
        "demotes a policy to OBSERVE — traffic it was blocking will be let through.",
    ),
    (r"agents\s+(?:kill|quarantine)" + _END, "stops a production agent (kill switch)."),
    (
        r"(?:policy\s+)?proposals\s+apply" + _END,
        "applies a proposed change to live governance configuration (directly, or to a "
        "canary cohort).",
    ),
    (
        r"(?:policy\s+)?proposals\s+rollback" + _END,
        "undoes an applied change, which loosens a control if the change tightened one.",
    ),
    (
        # Plain `verify` only records the outcome; `--failed` rolls the change back, so it
        # is the same blocking action under a different name.
        r"(?:policy\s+)?proposals\s+verify\b[^|;&]*--failed" + _END,
        "records a failed verification and rolls the applied change back.",
    ),
    (r"agents\s+resume" + _END, "restarts a stopped agent."),
    (
        r"demo" + _END,
        "runs the demo, which writes demo agents and data and briefly enforces `baseline` "
        "in whatever DB NOMETRIA_DATABASE_URL points at. Use a scratch DB.",
    ),
    (
        r"(?:admin\s+)?seed" + _END,
        "seeds demo agents, policies and keys into the configured DB "
        "(with --show-keys, raw keys are printed).",
    ),
    (
        r"(?:admin\s+)?db\s+downgrade" + _END,
        "rolls back database migrations (can drop columns and data).",
    ),
    (
        r"(?:guardrails\s+apply|policy\s+rules\s+apply|boundary\s+set|escalation\s+set"
        r"|declare\s+(?:boundary|escalation))\s.*--mode[\s=]+enforce" + _END,
        "turns a guardrail/boundary/escalation rule on in ENFORCE mode.",
    ),
    (
        r"(?:admin\s+)?auth\s+(?:issue|revoke)" + _END,
        "mints or revokes an API token (a minted token is shown once, in this transcript).",
    ),
    (
        r"(?:check|quickscan|scan)\s.*--submit" + _END,
        "uploads a redacted scan summary to a remote AgentFox API.",
    ),
]
CLI_RULES = [(re.compile(_PREFIX + pat), why) for pat, why in CLI_RULES]  # type: ignore[misc]

CURL_RULE = (
    re.compile(
        r"^(?:\w+=\S*\s+)*curl\b.*(?:/api/policies/[^/\s]+/mode|/api/agents/[^/\s]+/(?:kill|quarantine|resume)|/api/approvals/[^/\s]+/(?:approve|deny)|/api/proposals/[^/\s]+/(?:apply|rollback|verify))"
    ),
    "calls a control-plane endpoint that changes enforcement, stops an agent, "
    "decides an approval, or applies or undoes a change proposal.",
)

_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\||\n|\$\(|`|\()\s*")


def reasons_for(command: str) -> list[str]:
    reasons: list[str] = []
    for segment in _SPLIT.split(command):
        segment = segment.strip()
        for pattern, why in [*CLI_RULES, CURL_RULE]:
            if pattern.search(segment) and why not in reasons:
                reasons.append(why)
    return reasons


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        command = payload.get("tool_input", {}).get("command", "") or ""
    except Exception:
        return 0  # never break the session because of the hook itself
    reasons = reasons_for(command)
    if not reasons:
        return 0
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": "AgentFox harness: this command "
                + " Also: ".join(reasons)
                + " Confirm the user asked for exactly this.",
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
