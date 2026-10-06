"""AgentFox as an MCP server, so an AI client can ask the governance plane questions.

The transport is MCP stdio built on the standard library: newline-delimited JSON-RPC 2.0
on stdin/stdout, one object per line, and logs go only to stderr. The official `mcp` SDK
is deliberately not a dependency. The product has to stay installable offline with no
new core requirements, and stdio framing is small enough to own.

This exposes the observe half of the product: inventory, findings, posture, policy
validation and simulation, static analysis, a dry-run content check, and the improvement
loop's proposal inbox. Nothing here changes enforcement or stops an agent (no policy
enforce/observe, agents kill/quarantine/resume, seed, demo, db downgrade, auth
issue/revoke, --submit, and no proposal decide/apply/rollback). An assistant that can read
everything and change nothing is safe to hand to any client.

Every CLI-backed tool runs the real `agentfox` CLI in a subprocess, so an answer here is
exactly what an operator would see in a terminal. argv is built only from validated,
typed arguments: never a shell, and never a flag the caller supplied.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from agentfox import __version__
from agentfox.capabilities.compliance.catalog import FRAMEWORK_TITLES
from agentfox.improvement.contract import SCOPE_LEVELS, STATUSES

log = logging.getLogger("agentfox.mcp")

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
INSTRUCTIONS = (
    "AgentFox governs AI agents in production. These tools are observe-first: they read "
    "inventory, findings, policy, audit and compliance posture, and analyse text, actions "
    "and candidate policies. None of them changes what is enforced. State-changing "
    "actions (enforcing policy, killing or quarantining agents, issuing tokens, seeding, "
    "submitting scans, and deciding, applying or rolling back a change proposal) are "
    "deliberately not exposed. Ask a human operator to run those with the agentfox CLI. "
    "Start with agentfox_doctor."
)
CLI_TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = 100_000
SLUG = r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$"
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
_STDERR_NOISE = ("found in sys.modules after import of package", "warn(RuntimeWarning", "[alembic.")
_TAINT_FOR_SURFACE = {
    "input": "user",
    "output": "user",
    "retrieved": "retrieved",
    "tool_result": "tool_result",
}


class ToolError(Exception):
    """A genuine failure, reported to the client as an ``isError`` tool result."""


class InvalidParams(Exception):
    """Structurally bad request params, reported as JSON-RPC error -32602."""


ArgvBuilder = Callable[[dict[str, Any], Path], list[str]]


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    properties: dict[str, dict[str, Any]] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    argv: ArgvBuilder | None = None  # CLI-backed: build argv for `agentfox ...`
    run: Callable[[dict[str, Any]], dict[str, Any]] | None = None  # in-process
    json_output: bool = False
    exit_meanings: Mapping[int, str] = field(default_factory=dict)  # non-zero ≠ failure
    read_only: bool = True
    idempotent: bool = True

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.properties,
                "required": list(self.required),
                "additionalProperties": False,
            },
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": False,
                "idempotentHint": self.idempotent,
                "openWorldHint": False,
            },
        }


# --- schema + argv helpers --------------------------------------------------------


def _string(description: str, **extra: Any) -> dict[str, Any]:
    return {"type": "string", "description": description, **extra}


def _slug(description: str) -> dict[str, Any]:
    return _string(description, pattern=SLUG, maxLength=128)


def _integer(description: str, minimum: int, maximum: int) -> dict[str, Any]:
    return {"type": "integer", "description": description, "minimum": minimum, "maximum": maximum}


def _opts(args: dict[str, Any], **flags: str) -> list[str]:
    """Map validated arguments to CLI options. Flags come from here, never the caller."""
    out: list[str] = []
    for key, flag in flags.items():
        value = args.get(key)
        if value is None or value is False:
            continue
        out += [flag] if value is True else [flag, str(value)]
    return out


def _directory(args: dict[str, Any]) -> str:
    resolved = Path(args.get("path") or ".").expanduser().resolve()
    if not resolved.is_dir():
        raise ToolError(f"not a directory: {resolved}")
    return str(resolved)


_POLICY_SOURCE = {
    "path": _string("Path to a policy YAML file on this machine.", maxLength=4096),
    "yaml": _string("Policy YAML text, as an alternative to `path`.", maxLength=200_000),
}


def _policy_file(args: dict[str, Any], scratch: Path) -> str:
    path, text = args.get("path"), args.get("yaml")
    if (path is None) == (text is None):
        raise ToolError("pass exactly one of 'path' (a YAML file) or 'yaml' (inline YAML text)")
    if text is not None:
        target = scratch / "candidate-policy.yaml"
        target.write_text(text, encoding="utf-8")
        return str(target)
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ToolError(f"no such policy file: {resolved}")
    return str(resolved)


def _validate(tool: Tool, args: dict[str, Any]) -> None:
    unknown = sorted(set(args) - set(tool.properties))
    if unknown:
        accepted = ", ".join(tool.properties) or "none"
        raise ToolError(f"unknown argument(s): {', '.join(unknown)} (accepted: {accepted})")
    for key in tool.required:
        if args.get(key) is None:
            raise ToolError(f"missing required argument '{key}'")
    for key, value in args.items():
        if value is not None:
            _check(key, value, tool.properties[key])


def _check(key: str, value: Any, schema: dict[str, Any]) -> None:
    kind = schema["type"]
    type_ok = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "array": isinstance(value, list),
    }[kind]
    if not type_ok:
        raise ToolError(f"'{key}' must be a {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolError(f"'{key}' must be one of: {', '.join(map(str, schema['enum']))}")
    if kind == "string":
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", len(value)):
            raise ToolError(f"'{key}' has an invalid length")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ToolError(f"'{key}' does not match {schema['pattern']}")
    elif kind == "integer" and not schema["minimum"] <= value <= schema["maximum"]:
        raise ToolError(f"'{key}' must be between {schema['minimum']} and {schema['maximum']}")
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", len(value)):
            raise ToolError(f"'{key}' has an invalid number of items")
        for i, item in enumerate(value):
            _check(f"{key}[{i}]", item, schema["items"])


# --- in-process tools -------------------------------------------------------------


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _finding_row(finding: Any, *, detail: bool) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": finding.id,
        "type": finding.type,
        "severity": finding.severity,
        "status": finding.status,
        "title": finding.title,
        "subject": f"{finding.subject_type}:{finding.subject_id}",
        # One row per underlying problem: a recurrence counts here instead of adding a row.
        "occurrences": finding.occurrences or 1,
        "fingerprint": finding.fingerprint,
        "first_seen": _iso(finding.created_at),
        "last_seen": _iso(finding.last_seen_at or finding.created_at),
    }
    if detail:
        row.update(
            {
                "controls": finding.control_keys,
                "evidence": finding.evidence_json,
                "suppression_reason": finding.suppression_reason,
                "suppressed_by": finding.suppressed_by,
                "resolution_note": finding.resolution_note,
                "resolved_by": finding.resolved_by,
                "resolved_at": _iso(finding.resolved_at),
            }
        )
    return row


def _finding_occurrences(args: dict[str, Any]) -> dict[str, Any]:
    """Findings ranked by how often the same problem came back, or one finding in full."""
    from sqlalchemy import select

    from agentfox.core.db import session_scope
    from agentfox.core.models import Finding

    finding_id = args.get("finding_id")
    status = args.get("status") or "open"
    with contextlib.redirect_stdout(sys.stderr), session_scope() as session:
        if finding_id is not None:
            finding = session.get(Finding, finding_id)
            if finding is None:
                raise ToolError(f"unknown finding: {finding_id}")
            return {"finding": _finding_row(finding, detail=True)}
        stmt = select(Finding).where(Finding.status == status)
        if args.get("type") is not None:
            stmt = stmt.where(Finding.type == args["type"])
        if args.get("min_occurrences") is not None:
            stmt = stmt.where(Finding.occurrences >= args["min_occurrences"])
        stmt = stmt.order_by(Finding.occurrences.desc(), Finding.created_at.desc()).limit(
            args.get("limit") or 20
        )
        rows = [_finding_row(f, detail=False) for f in session.scalars(stmt)]
    return {"status": status, "count": len(rows), "findings": rows}


def _guard_text(args: dict[str, Any]) -> dict[str, Any]:
    """The check behind the gateway's POST /v1/guard/input, dry-run (persist=False)."""
    from agentfox.core.db import session_scope
    from agentfox.runtime.enforcement import Enforcer

    surface = args.get("surface") or "input"
    with contextlib.redirect_stdout(sys.stderr), session_scope() as session:
        result = Enforcer(session).check_content(
            agent_slug=args["agent"],
            content=args["text"],
            surface=surface,
            taint_source=_TAINT_FOR_SURFACE[surface],
            persist=False,
        )
    keys = ("verdict", "effective_verdict", "mode", "reason", "rules_fired", "entities")
    payload: dict[str, Any] = {"agent": args["agent"], "surface": surface}
    payload.update({key: result.get(key) for key in keys})
    if not payload["rules_fired"] and payload["entities"]:
        payload["note"] = (
            "detectors flagged this text but no policy rule matched it; check that a "
            "policy covering this agent is loaded (agentfox_policy_list)"
        )
    return payload


# --- the registry -----------------------------------------------------------------

_SEVERITIES = ["critical", "high", "medium", "low", "info"]

TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in [
        Tool(
            "agentfox_doctor",
            "Runtime health check",
            "Reports whether this deployment is configured the way you think it is: database, "
            "traffic, authentication, detectors, modes. Returns JSON rows of {check, state, "
            "detail}. Use this first, before trusting any other answer.",
            argv=lambda a, s: ["doctor", "--json"],
            json_output=True,
        ),
        Tool(
            "agentfox_findings",
            "Platform findings",
            "Returns what the platform has found (ungoverned calls, shadow agents, policy gaps) "
            "as JSON, newest first. Use this to answer 'what needs attention?'.",
            {
                "severity": _string("Only findings of this severity.", enum=_SEVERITIES),
                "limit": _integer("Maximum findings to return (default 20).", 1, 500),
            },
            argv=lambda a, s: [
                "findings",
                "--json",
                *_opts(a, severity="--severity", limit="--limit"),
            ],
            json_output=True,
        ),
        Tool(
            "agentfox_finding_occurrences",
            "Finding recurrence",
            "Findings ranked by how many times the same underlying problem has recurred, with "
            "the fingerprint that identifies it and when it was first and last seen. Pass "
            "`finding_id` to get one finding in full, including its evidence. Use this to tell "
            "a one-off apart from something that keeps coming back.",
            {
                "finding_id": _slug("One finding id; returns that finding in full."),
                "status": _string(
                    "Only findings in this state (default open).",
                    enum=["open", "suppressed", "resolved"],
                ),
                "type": _slug("Only findings of this type, e.g. guardrail_detection."),
                "min_occurrences": _integer("Only findings seen at least this often.", 1, 10_000),
                "limit": _integer("Maximum findings to return (default 20).", 1, 200),
            },
            run=_finding_occurrences,
        ),
        Tool(
            "agentfox_agents",
            "Agent inventory",
            "Returns every agent, registered or shadow, plus an inventory summary (risk tiers, "
            "environments, frameworks, tools) as JSON. Use this to find agent slugs.",
            argv=lambda a, s: ["agents", "list", "--json"],
            json_output=True,
        ),
        Tool(
            "agentfox_agent_lineage",
            "Agent blast radius",
            "Shows what an agent can reach (tools, data, other agents) up to a depth: its blast "
            "radius. Use this before approving a capability or when triaging an incident.",
            {"slug": _slug("Agent slug."), "depth": _integer("Graph depth (default 2).", 1, 6)},
            ("slug",),
            argv=lambda a, s: ["agents", "lineage", *_opts(a, depth="--depth"), "--", a["slug"]],
        ),
        Tool(
            "agentfox_policy_list",
            "Policies",
            "Lists policies with their version, enforcement mode (observe or enforce) and "
            "rule count.",
            argv=lambda a, s: ["policy", "list"],
        ),
        Tool(
            "agentfox_policy_effective",
            "Effective policy",
            "Shows the policy actually in force for a subject (agent/team/user/environment) and "
            "which layer each rule came from. Use this to explain why something was allowed or "
            "blocked.",
            {
                "agent": _slug("Agent slug."),
                "team": _slug("Team slug."),
                "user": _slug("User (e.g. email)."),
                "environment": _slug("Environment (default production)."),
            },
            argv=lambda a, s: [
                "policy",
                "effective",
                *_opts(
                    a, agent="--agent", team="--team", user="--user", environment="--environment"
                ),
            ],
        ),
        Tool(
            "agentfox_policy_validate",
            "Validate a policy",
            "Lints and compiles a candidate policy without saving it. Pass `path` or inline "
            "`yaml`. exit_code 1 means the policy is invalid, and the reason is in the text.",
            dict(_POLICY_SOURCE),
            argv=lambda a, s: ["policy", "validate", _policy_file(a, s)],
            exit_meanings={1: "policy is invalid; nothing was saved"},
        ),
        Tool(
            "agentfox_policy_simulate",
            "Simulate a policy change",
            "Replays recorded traffic against a candidate policy and reports what would newly "
            "block, escalate or allow. exit_code 1 means production traffic would newly block. "
            "Records the simulation but never changes enforcement.",
            {
                **_POLICY_SOURCE,
                "agent": _slug("Only replay this agent's traffic."),
                "since_days": _integer("Replay window in days (default 30).", 1, 365),
            },
            argv=lambda a, s: [
                "policy",
                "simulate",
                "-f",
                _policy_file(a, s),
                *_opts(a, agent="--agent", since_days="--since-days"),
            ],
            exit_meanings={1: "the candidate would newly block production traffic"},
            read_only=False,
            idempotent=False,
        ),
        Tool(
            "agentfox_policy_lint",
            "Lint policy hierarchy",
            "Lints the whole policy hierarchy for shadowed, conflicting or unreachable rules. "
            "exit_code 1 means critical or high findings, which would fail a CI build.",
            argv=lambda a, s: ["policy", "lint"],
            exit_meanings={1: "critical or high lint findings; would fail CI"},
        ),
        Tool(
            "agentfox_proposals_list",
            "Change proposals",
            "Lists the improvement loop's proposed changes to governance configuration as JSON, "
            "newest first: status, kind, direction (tightens, loosens or neutral), autonomy "
            "level, scope and title. Use this to answer 'what does the loop want to change, and "
            "what is waiting on a person?'.",
            {
                "status": _string("Only proposals in this state.", enum=list(STATUSES)),
                "kind": _slug("Only this change kind, e.g. policy.rule_min_score."),
                "scope": _string("Only this scope level.", enum=list(SCOPE_LEVELS)),
            },
            argv=lambda a, s: [
                "policy",
                "proposals",
                "list",
                "--json",
                *_opts(a, status="--status", kind="--kind", scope="--scope"),
            ],
            json_output=True,
        ),
        Tool(
            "agentfox_proposals_show",
            "One change proposal",
            "Returns one proposal in full as JSON: the diff it would make, the evidence that "
            "prompted it, the proof attached to it, the expected effect, and every decision "
            "taken on it. Read this before recommending a decision. A loosening change always "
            "needs a person, whatever the evidence says.",
            {"proposal_id": _slug("Proposal id, e.g. chp_… (from agentfox_proposals_list).")},
            ("proposal_id",),
            argv=lambda a, s: ["policy", "proposals", "show", "--json", "--", a["proposal_id"]],
            json_output=True,
        ),
        Tool(
            "agentfox_check_repo",
            "Scan a repository",
            "Statically scans a local directory for model calls, agent frameworks and "
            "ungoverned call sites, and returns JSON. It never imports or runs the code and "
            "never submits anything.",
            {
                "path": _string("Directory to scan (default: current directory).", maxLength=4096),
                "limit": _integer("Findings to include (default 15).", 1, 200),
            },
            argv=lambda a, s: [
                "scan",
                "repo",
                "--json",
                "--no-submit",
                *_opts(a, limit="--limit"),
                "--",
                _directory(a),
            ],
            json_output=True,
        ),
        Tool(
            "agentfox_analyse_action",
            "Analyse an action",
            "Works out what a SQL statement, shell command or HTTP call would actually do: "
            "operation, targets, blast radius, reversibility, risks. Deterministic and offline. "
            "exit_code 1 means a critical risk. Use this before running generated actions.",
            {
                "statement": _string("SQL, shell command, or URL.", minLength=1, maxLength=20_000),
                "kind": _string(
                    "What the statement is (default sql).", enum=["sql", "shell", "http"]
                ),
                "method": _string(
                    "HTTP method when kind=http.",
                    enum=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"],
                ),
                "dialect": _slug("SQL dialect (default postgres)."),
                "environment": _slug("Environment the action binds to (default production)."),
            },
            ("statement",),
            argv=lambda a, s: [
                "test",
                "action",
                *_opts(
                    a,
                    kind="--kind",
                    method="--method",
                    dialect="--dialect",
                    environment="--environment",
                ),
                "--",
                a["statement"],
            ],
            exit_meanings={1: "critical risk identified; do not run this unreviewed"},
        ),
        Tool(
            "agentfox_audit_verify",
            "Verify audit chain",
            "Verifies the tamper-evident audit chain, optionally over a sequence range. "
            "exit_code 1 means the chain is broken (CHAIN TAMPERED) and lists where.",
            {
                "start": _integer("First sequence number.", 0, 2**53),
                "end": _integer("Last sequence number.", 0, 2**53),
            },
            argv=lambda a, s: ["report", "verify", *_opts(a, start="--start", end="--end")],
            exit_meanings={1: "audit chain verification FAILED; the chain is broken"},
        ),
        Tool(
            "agentfox_compliance_status",
            "Compliance posture",
            "Shows control posture (effective, degraded, failing, not implemented), optionally "
            "for one framework. Mappings are engineering drafts, not legal advice.",
            {
                "framework": _string("Framework id.", enum=sorted(FRAMEWORK_TITLES)),
                "verbose": {"type": "boolean", "description": "List every control."},
            },
            argv=lambda a, s: [
                "report",
                "status",
                *_opts(a, framework="--framework", verbose="--verbose"),
            ],
        ),
        Tool(
            "agentfox_compliance_frameworks",
            "Compliance frameworks",
            "Lists supported frameworks with mapped-control coverage and review status.",
            argv=lambda a, s: ["report", "frameworks"],
        ),
        Tool(
            "agentfox_redteam_probes",
            "Red-team probe suite",
            "Lists the built-in adversarial probes (category, surface, severity, OWASP/ATLAS ids) "
            "and which wrapped runners are installed. It does not run a campaign.",
            argv=lambda a, s: ["test", "probes"],
        ),
        Tool(
            "agentfox_guardrails_catalogue",
            "Guardrail catalogue",
            "Returns every kind of guardrail the product can enforce as JSON, optionally filtered "
            "by intent. Use this to answer 'can we express this policy?'.",
            {"intent": _slug("Intent id, e.g. prevent_disclosure.")},
            argv=lambda a, s: [
                "policy",
                "rules",
                "catalogue",
                "--json",
                *_opts(a, intent="--intent"),
            ],
            json_output=True,
        ),
        Tool(
            "agentfox_guardrails_suggest",
            "Suggest guardrails",
            "Suggests which guardrail kinds a written policy instruction probably needs, with "
            "confidence. Uses deterministic matching, not a model.",
            {
                "instruction": _string(
                    "A sentence from a policy document.", minLength=1, maxLength=4000
                )
            },
            ("instruction",),
            argv=lambda a, s: ["policy", "rules", "suggest", "--", a["instruction"]],
        ),
        Tool(
            "agentfox_guardrails_explain",
            "Explain a guardrail kind",
            "Returns the parameters, inputs and a worked example for one guardrail kind. Get "
            "ids from agentfox_guardrails_catalogue.",
            {"kind_id": _slug("Guardrail kind id, e.g. pii_detection.")},
            ("kind_id",),
            argv=lambda a, s: ["policy", "rules", "explain", "--", a["kind_id"]],
        ),
        Tool(
            "agentfox_guardrails_test",
            "Try values against a rule",
            "Evaluates values against a business rule (threshold ladder) and shows the outcome "
            "and reason for each. Runs nothing.",
            {
                "key": _slug("Rule key."),
                "values": {
                    "type": "array",
                    "description": 'Values to try, as strings, e.g. ["499", "501"].',
                    "items": {"type": "string", "pattern": r"^[^,\n]{1,200}$"},
                    "minItems": 1,
                    "maxItems": 50,
                },
            },
            ("key", "values"),
            argv=lambda a, s: ["policy", "rules", "test", "--", a["key"], ",".join(a["values"])],
        ),
        Tool(
            "agentfox_guardrails_check",
            "Rule conflicts",
            "Finds business rules where two teams' thresholds disagree, as JSON. exit_code 1 "
            "means conflicts were found.",
            argv=lambda a, s: ["policy", "rules", "check", "--json"],
            json_output=True,
            exit_meanings={1: "conflicting rules found"},
        ),
        Tool(
            "agentfox_boundary_check",
            "Knowledge boundary check",
            "Says whether an agent would refuse a question under its declared knowledge "
            "boundary, and what it would say instead. Changes nothing.",
            {
                "agent": _slug("Agent slug."),
                "question": _string("A question to test.", minLength=1, maxLength=4000),
            },
            ("agent", "question"),
            argv=lambda a, s: ["test", "boundary", "--", a["agent"], a["question"]],
        ),
        Tool(
            "agentfox_sources_list",
            "Registered sources",
            "Returns every registered knowledge source with its authority tier and freshness as "
            "JSON, worst tier first.",
            argv=lambda a, s: ["declare", "list", "sources", "--json"],
            json_output=True,
        ),
        Tool(
            "agentfox_version",
            "Versions",
            "Shows every version that takes part in a decision: product, control catalogue, "
            "policy engine, default mode, fail mode, latency budget.",
            argv=lambda a, s: ["admin", "version"],
        ),
        Tool(
            "agentfox_guard_text",
            "Guard a piece of text",
            "Evaluates text for an agent on one surface (input, output, retrieved, tool_result) "
            "against the policy in force, without calling a model and without recording a "
            "decision. Returns verdict, effective_verdict, mode, reason, rules_fired, entities. "
            "Use this to ask 'would this be blocked?'.",
            {
                "agent": _slug("Agent slug (unknown slugs get org-wide policy)."),
                "text": _string("The text to evaluate.", minLength=1, maxLength=100_000),
                "surface": _string(
                    "Where the text appears (default input).", enum=list(_TAINT_FOR_SURFACE)
                ),
            },
            ("agent", "text"),
            run=_guard_text,
        ),
    ]
}


# --- tool execution ---------------------------------------------------------------


@dataclass(frozen=True)
class CliOutcome:
    exit_code: int
    stdout: str
    stderr: str


def _child_env() -> dict[str, str]:
    env = dict(os.environ)  # AGENTFOX_* (database, keys, mode) reaches the CLI unchanged
    env.update({"COLUMNS": "160", "NO_COLOR": "1", "TERM": "dumb", "PYTHONIOENCODING": "utf-8"})
    env.pop("FORCE_COLOR", None)
    # The child must run the same agentfox as this server, source checkout or installed.
    package_root = str(Path(__file__).resolve().parents[2])  # src/, above agentfox/
    env["PYTHONPATH"] = os.pathsep.join(p for p in (package_root, env.get("PYTHONPATH")) if p)
    return env


def _clean(raw: bytes) -> str:
    return _ANSI.sub("", raw.decode("utf-8", errors="replace"))[:MAX_OUTPUT_CHARS]


def run_cli(argv: list[str]) -> CliOutcome:
    command = [sys.executable, "-m", "agentfox.cli.main", *argv]
    try:
        proc = subprocess.run(  # noqa: S603 — argv built from validated arguments only
            command,
            stdin=subprocess.DEVNULL,  # never let the child read the protocol stream
            capture_output=True,
            env=_child_env(),
            timeout=CLI_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(
            f"`agentfox {' '.join(argv)}` timed out after {CLI_TIMEOUT_SECONDS}s"
        ) from exc
    except OSError as exc:
        raise ToolError(f"could not start the agentfox CLI: {exc}") from exc
    stderr = "\n".join(
        line
        for line in _clean(proc.stderr).splitlines()
        if not any(n in line for n in _STDERR_NOISE)
    )
    return CliOutcome(proc.returncode, _clean(proc.stdout), stderr)


def _tool_result(text: str, *, structured: Any = None, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if structured is not None:
        result["structuredContent"] = structured
    return result


def _cli_result(tool: Tool, argv: list[str], outcome: CliOutcome) -> dict[str, Any]:
    command = "agentfox " + " ".join(argv)
    crashed = "Traceback (most recent call last)" in outcome.stdout + outcome.stderr
    meaning = "success" if outcome.exit_code == 0 else tool.exit_meanings.get(outcome.exit_code)
    if meaning is None or crashed:
        detail = "\n".join(p for p in (outcome.stdout.strip(), outcome.stderr.strip()) if p)
        return _tool_result(
            f"{command} failed (exit_code {outcome.exit_code}).\n\n{detail or 'no output'}",
            is_error=True,
        )
    status = {"command": command, "exit_code": outcome.exit_code, "exit_meaning": meaning}
    if tool.json_output:
        with contextlib.suppress(ValueError):
            structured = {**status, "data": json.loads(outcome.stdout)}
            return _tool_result(json.dumps(structured, indent=2), structured=structured)
    body = outcome.stdout.strip() or outcome.stderr.strip() or "(no output)"
    return _tool_result(f"{body}\n\nexit_code: {outcome.exit_code} ({meaning})")


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tool = TOOLS.get(name)
    if tool is None:
        return _tool_result(
            f"Unknown tool '{name}'. Call tools/list for the available tools.", is_error=True
        )
    try:
        _validate(tool, arguments)
        if tool.run is not None:
            payload = json.loads(json.dumps(tool.run(arguments), default=str))
            return _tool_result(json.dumps(payload, indent=2), structured=payload)
        assert tool.argv is not None
        with tempfile.TemporaryDirectory(prefix="agentfox-mcp-") as scratch:
            argv = tool.argv(arguments, Path(scratch))
            return _cli_result(tool, argv, run_cli(argv))
    except ToolError as exc:
        return _tool_result(str(exc), is_error=True)
    except Exception as exc:  # a tool crash is a tool result, never a dead server
        log.exception("tool %s crashed", name)
        return _tool_result(f"{name} failed: {type(exc).__name__}: {exc}", is_error=True)


# --- JSON-RPC / MCP protocol ------------------------------------------------------


def _initialize(params: dict[str, Any]) -> dict[str, Any]:
    requested = params.get("protocolVersion")
    version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "agentfox", "title": "AgentFox", "version": __version__},
        "instructions": INSTRUCTIONS,
    }


def _tools_list(params: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(params.get("cursor", ""), str):
        raise InvalidParams("'cursor' must be a string")
    return {"tools": [tool.definition() for tool in TOOLS.values()]}  # one page: all tools


def _tools_call(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise InvalidParams("tools/call needs a string 'name'")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise InvalidParams("'arguments' must be an object")
    return call_tool(name, arguments)


METHODS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "initialize": _initialize,
    "ping": lambda params: {},
    "tools/list": _tools_list,
    "tools/call": _tools_call,
}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(message: Any) -> dict[str, Any] | None:
    """One parsed message in, at most one response out. Notifications get none."""
    if isinstance(message, list):
        return _error(None, -32600, "Invalid Request: batches are not supported")
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        msg_id = message.get("id") if isinstance(message, dict) else None
        return _error(msg_id, -32600, "Invalid Request")
    if "method" not in message or "id" not in message:
        log.debug("no response for %s", message.get("method", "a client response"))
        return None  # a notification, or a response to a request we never send
    msg_id, method = message["id"], message["method"]
    handler = METHODS.get(method) if isinstance(method, str) else None
    if handler is None:
        return _error(msg_id, -32601, f"Method not found: {method}")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _error(msg_id, -32602, "Invalid params: 'params' must be an object")
    try:
        return {"jsonrpc": "2.0", "id": msg_id, "result": handler(params)}
    except InvalidParams as exc:
        return _error(msg_id, -32602, f"Invalid params: {exc}")
    except Exception as exc:
        log.exception("%s failed", method)
        return _error(msg_id, -32603, f"Internal error: {exc}")


def _prepare() -> None:
    try:  # idempotent: findings, sources and boundary need a schema to read from
        from agentfox.core.db import init_db

        init_db()
    except Exception as exc:  # the server still answers; DB-backed tools report their own errors
        print(f"agentfox mcp: database not initialised: {exc}", file=sys.stderr)
    # After init_db, because Alembic's fileConfig disables loggers that already exist.
    log.disabled = False
    if not log.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("agentfox mcp: %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.propagate = False
    from agentfox.core.config import env

    log.setLevel((env("MCP_LOG_LEVEL") or "WARNING").upper())


def serve(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Serve MCP over stdio until EOF. Returns the process exit code."""
    stdin = stdin if stdin is not None else sys.stdin
    out = stdout if stdout is not None else sys.stdout
    with contextlib.suppress(AttributeError, ValueError):
        stdin.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    real_stdout, sys.stdout = sys.stdout, sys.stderr  # stray prints must never hit the protocol
    try:
        _prepare()
        while line := stdin.readline():
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError as exc:
                response: dict[str, Any] | None = _error(None, -32700, f"Parse error: {exc}")
            else:
                response = handle(message)
            if response is not None:
                out.write(json.dumps(response, default=str) + "\n")  # ASCII, never multi-line
                out.flush()
    except (BrokenPipeError, KeyboardInterrupt):
        pass  # the client went away; there is nobody left to answer
    finally:
        sys.stdout = real_stdout
    return 0
