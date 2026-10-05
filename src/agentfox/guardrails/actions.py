"""P9 — action assurance: what the generated artefact will actually do.

Everything else in this system governs the *call*: is this agent allowed to use
`db.query`, and is the argument tainted? That containment is real and it is not
enough, because an agent holding a legitimate `db.query` capability can pass
``DROP TABLE users`` as a perfectly well-formed string argument and every
argument-level check will pass it. An AI coding agent connected to production instead
of staging wiped 1.9M rows this way — "flawlessly, from a technical standpoint".

Three design commitments, all of them from the incident literature rather than from
what is convenient to build:

* **Deterministic parsing, never a model.** An LLM asked "is this SQL dangerous?" is a
  probabilistic control on a deterministic question, and it will be wrong on exactly
  the adversarial input that matters. We parse to an AST with sqlglot (MIT,
  zero-dependency, 31 dialects) and reason over the tree.
* **Fail closed on unparseable.** A statement we cannot parse is a statement we cannot
  govern. Passing it through because analysis failed inverts the control.
* **Comments are the parser's problem, not a regex's.** ``SELECT * FROM users --
  ; DROP TABLE users`` defeats keyword matching and is harmless to an AST; the reverse
  case — a `DROP` hidden past a comment the regex stopped at — is why keyword matching
  cannot be the mechanism.

The target is **zero false negatives on destructive operations**. A false positive
here costs an engineer a policy exception; a false negative costs a table.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..finding import RiskFinding
from .normalize import normalize

log = logging.getLogger(__name__)

try:  # sqlglot is an optional extra so `pip install agentfox` stays offline-light
    import sqlglot
    from sqlglot import exp

    SQLGLOT_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only where sqlglot is absent
    sqlglot = None  # type: ignore[assignment]
    exp = None  # type: ignore[assignment]
    SQLGLOT_AVAILABLE = False


# Operation classes, ordered by how hard the damage is to undo.
READ = "read"
WRITE = "write"
DESTRUCTIVE = "destructive"
ADMIN = "admin"
UNKNOWN = "unknown"

CLASS_RANK = {READ: 0, WRITE: 1, ADMIN: 2, DESTRUCTIVE: 3, UNKNOWN: 4}

#: Statement types that destroy data or schema. TRUNCATE is here rather than under
#: write because it is typically non-transactional and non-recoverable.
_DESTRUCTIVE_NODES = ("Drop", "TruncateTable")
#: ALTER is destructive only when it drops or renames — ADD COLUMN is not, and
#: blocking it would be the kind of false positive that gets the control switched off.
#: sqlglot gives a table-level rename (RENAME TO) and a column-level rename (RENAME
#: COLUMN ... TO ...) distinct node types — AlterRename and RenameColumn respectively.
_DESTRUCTIVE_ALTER_ACTIONS = ("Drop", "AlterRename", "RenameColumn")
_WRITE_NODES = ("Insert", "Update", "Delete", "Merge")
_ADMIN_NODES = ("Grant", "Revoke", "Create", "Set", "Command", "Alter")

#: Environments where an irreversible statement is a production incident rather than
#: a test. Bound to the agent's declared environment (P9-6).
PRODUCTION_ENVIRONMENTS = ("production", "prod")


ActionRisk = RiskFinding


@dataclass
class ActionAnalysis:
    """The full verdict on one generated artefact."""

    dialect: str
    parsed: bool
    operation: str = UNKNOWN
    statements: int = 0
    targets: list[str] = field(default_factory=list)
    risks: list[ActionRisk] = field(default_factory=list)
    blast_radius: str = "unknown"  # none | bounded | unbounded | catastrophic
    reversible: bool = True
    normalised: list[str] = field(default_factory=list)
    parse_error: str | None = None

    @property
    def severity(self) -> str:
        order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        return max((r.severity for r in self.risks), key=lambda s: order.get(s, 0), default="low")

    @property
    def blocked(self) -> bool:
        return any(r.severity == "critical" for r in self.risks)

    def to_json(self) -> dict[str, Any]:
        return {
            "dialect": self.dialect,
            "parsed": self.parsed,
            "operation": self.operation,
            "statements": self.statements,
            "targets": self.targets,
            "blast_radius": self.blast_radius,
            "reversible": self.reversible,
            "severity": self.severity,
            "risks": [r.to_json() for r in self.risks],
            "normalised": self.normalised,
            "parse_error": self.parse_error,
        }


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------


def _alter_is_destructive(node: Any) -> bool:
    actions = node.args.get("actions") or []
    return any(type(a).__name__ in _DESTRUCTIVE_ALTER_ACTIONS for a in actions)


def _is_unparsed_alter_rename(node: Any) -> bool:
    """A multi-column ``RENAME COLUMN a TO x, b TO y`` in one statement isn't valid
    Postgres grammar, so sqlglot can't build a structured `Alter` node for it and
    falls back to a generic `Command` — which `_node_class` would otherwise classify
    as an ordinary admin action with no risk at all, silently bypassing the
    destructive-ALTER check entirely.

    Scoped narrowly to the rename case specifically, not to every Command fallback:
    a `CREATE OR REPLACE VIEW` can hit the same sqlglot fallback path for unrelated
    dialect-support reasons and is not destructive, so treating every unparsed
    Command as critical would flag legitimate DDL this check has no business
    touching. Only `Command` nodes whose captured leading keyword is `ALTER` and
    whose (unparsed) remainder mentions `RENAME COLUMN` qualify.
    """
    if type(node).__name__ != "Command":
        return False
    if node.args.get("this") != "ALTER":
        return False
    remainder = node.args.get("expression") or ""
    return "RENAME COLUMN" in remainder.upper()


def _is_destructive(node: Any) -> bool:
    name = type(node).__name__
    if name in _DESTRUCTIVE_NODES:
        return True
    if name == "Alter":
        return _alter_is_destructive(node)
    return _is_unparsed_alter_rename(node)


def _node_class(node: Any) -> str:
    name = type(node).__name__
    if _is_destructive(node):
        return DESTRUCTIVE
    if name in _WRITE_NODES:
        return WRITE
    if name in _ADMIN_NODES:
        return ADMIN
    if name in ("Select", "Union", "With", "Describe", "Show"):
        return READ
    return UNKNOWN


def _predicate_always_true(node: Any) -> bool:
    """Is this expression true regardless of the row?

    Takes the expression itself rather than the WHERE wrapper, because unwrapping
    ``.this`` recursively would descend into the left operand of a comparison and
    quietly mis-answer ``id = 5 OR 1 = 1``.
    """
    if node is None or exp is None:
        return False
    if isinstance(node, exp.Paren):
        return _predicate_always_true(node.this)
    if isinstance(node, exp.Boolean):
        return bool(node.this)
    if isinstance(node, exp.EQ):
        left, right = node.this, node.expression
        if isinstance(left, exp.Literal) and isinstance(right, exp.Literal):
            return str(left.this) == str(right.this)
        if isinstance(left, exp.Column) and isinstance(right, exp.Column):
            return left.sql() == right.sql()
        return False
    if isinstance(node, exp.Or):
        # An OR is unbounded if *either* side is — the bounded side is irrelevant.
        return _predicate_always_true(node.this) or _predicate_always_true(node.expression)
    if isinstance(node, exp.And):
        return _predicate_always_true(node.this) and _predicate_always_true(node.expression)
    return False


def _is_tautology(where: Any) -> bool:
    """``WHERE 1=1`` and friends: syntactically bounded, semantically unbounded.

    This is the shape that gets past a "does it have a WHERE clause?" check, which is
    why the check has to look at what the predicate actually says.
    """
    if where is None:
        return False
    return _predicate_always_true(where.this if hasattr(where, "this") else where)


def analyse_sql(statement: str, *, dialect: str = "postgres") -> ActionAnalysis:
    """Parse and classify a SQL artefact. P9-1…P9-5, P9-9."""
    analysis = ActionAnalysis(dialect=dialect, parsed=False)
    if not SQLGLOT_AVAILABLE:
        analysis.risks.append(
            ActionRisk(
                code="analysis.unavailable",
                severity="critical",
                detail="sqlglot is not installed, so this statement cannot be analysed. "
                "Install agentfox[sql] or the action is refused — an unanalysable "
                "statement is not a safe statement.",
            )
        )
        return analysis

    try:
        trees = [t for t in sqlglot.parse(statement, read=dialect) if t is not None]
    except Exception as exc:
        # P9-1: fail closed. Passing through what we could not parse would invert the
        # control — the adversarial input is precisely the one that fails to parse.
        analysis.parse_error = f"{type(exc).__name__}: {exc}"
        analysis.risks.append(
            ActionRisk(
                code="sql.unparseable",
                severity="critical",
                detail="statement could not be parsed, and an unparseable statement "
                "cannot be governed",
                evidence={"error": analysis.parse_error},
            )
        )
        analysis.blast_radius = "unknown"
        return analysis

    analysis.parsed = True
    analysis.statements = len(trees)
    analysis.normalised = [t.sql(dialect=dialect) for t in trees]

    targets: list[str] = []
    operation = READ
    for tree in trees:
        klass = _node_class(tree)
        if CLASS_RANK[klass] > CLASS_RANK[operation]:
            operation = klass
        for table in tree.find_all(exp.Table):
            # comments=False: sqlglot attaches trailing comments to the node, and a
            # target called "users /* ; DROP TABLE users */" is unreadable in a policy
            # or an audit entry.
            name = table.sql(dialect=dialect, comments=False)
            if name not in targets:
                targets.append(name)
    analysis.operation = operation
    analysis.targets = targets

    # P9-3: stacked statements. A single "query" that is really two is the classic
    # injection shape, and no legitimate parameterised call needs it.
    if len(trees) > 1:
        analysis.risks.append(
            ActionRisk(
                code="sql.stacked_statements",
                severity="critical",
                detail=f"{len(trees)} statements in one call: "
                + "; ".join(type(t).__name__ for t in trees),
                evidence={"statements": analysis.normalised},
            )
        )

    for tree in trees:
        name = type(tree).__name__
        if _is_destructive(tree):
            analysis.reversible = False
            analysis.blast_radius = "catastrophic"
            analysis.risks.append(
                ActionRisk(
                    code="sql.destructive_ddl",
                    severity="critical",
                    detail=f"{name} destroys data or schema and cannot be rolled back after commit",
                    evidence={"statement": tree.sql(dialect=dialect)},
                )
            )
            continue

        if name in ("Delete", "Update"):
            where = tree.args.get("where")
            # P9-4: the unbounded mutation. This is the 1.9M-row shape.
            if where is None:
                analysis.reversible = False
                analysis.blast_radius = "unbounded"
                analysis.risks.append(
                    ActionRisk(
                        code="sql.unbounded_mutation",
                        severity="critical",
                        detail=f"{name.upper()} with no WHERE clause affects every row in "
                        f"{', '.join(targets) or 'the target table'}",
                        evidence={"statement": tree.sql(dialect=dialect)},
                    )
                )
            elif _is_tautology(where):
                analysis.reversible = False
                analysis.blast_radius = "unbounded"
                analysis.risks.append(
                    ActionRisk(
                        code="sql.tautological_predicate",
                        severity="critical",
                        detail=f"{name.upper()} predicate is always true, so it is unbounded "
                        "despite having a WHERE clause",
                        evidence={"predicate": where.sql(dialect=dialect)},
                    )
                )
            else:
                if analysis.blast_radius in ("unknown", "none"):
                    analysis.blast_radius = "bounded"

        if name in ("Grant", "Revoke"):
            # P9-9: an agent that can widen its own grants can defeat every other
            # control here, so privilege change is never merely a write.
            analysis.risks.append(
                ActionRisk(
                    code="sql.privilege_change",
                    severity="high",
                    detail=f"{name.upper()} alters access control, which can compose into "
                    "privileges the agent was never granted",
                    evidence={"statement": tree.sql(dialect=dialect)},
                )
            )

    if analysis.blast_radius == "unknown":
        analysis.blast_radius = "none" if operation == READ else "bounded"
    return analysis


# ---------------------------------------------------------------------------
# Non-SQL artefacts
# ---------------------------------------------------------------------------

#: Shell fragments that turn AgentFox's own enforcement off.
#:
#: An agent that can pause enforcement can switch off every other rule in this
#: file, so this is the one control the rest depend on. Nothing stopped it: a
#: governed agent with shell access could run `agentfox policy observe baseline`
#: and drop every content policy out of enforce mode, edit the config, or delete
#: the database, and the only trace would be the decision record it had just
#: disabled.
#:
#: Narrow on purpose, in the same spirit as the destructive list below. Read-only
#: commands are not here — `agentfox policy list`, `findings`, `doctor` and the
#: rest are how an agent is *supposed* to inspect its own governance, and
#: blocking them would teach people to turn this off. Only the verbs that change
#: what is enforced, plus writes to the three things that hold that state.
#:
#: The CLI may be reached as `agentfox`, `python -m agentfox`, or through `uv
#: run`/`uvx`, so the binary is matched loosely and the subcommand strictly.
_AGENTFOX_CLI = r"(?:agentfox|python[\d.]*\s+-m\s+agentfox|uvx?\s+(?:run\s+)?agentfox)"

_SHELL_CONTROL_PLANE = [
    (
        re.compile(rf"\b{_AGENTFOX_CLI}\s+policy\s+(?:observe|disable|delete)\b", re.I),
        "putting a policy back into observe mode",
    ),
    (
        # `permit` is the same command as `capability` since the CLI consolidation;
        # every renamed spelling below has to stay covered or the rename is the hole.
        re.compile(rf"\b{_AGENTFOX_CLI}\s+(?:capability|permit)\s+(?:revoke|grant)\b", re.I),
        "changing its own capability grants",
    ),
    (
        re.compile(rf"\b{_AGENTFOX_CLI}\s+agents\s+(?:resume|quarantine)\b", re.I),
        "changing an agent's control state",
    ),
    (
        re.compile(rf"\b{_AGENTFOX_CLI}\s+(?:admin\s+)?db\s+downgrade\b", re.I),
        "rolling the schema back",
    ),
    (
        re.compile(rf"\b{_AGENTFOX_CLI}\s+(?:admin\s+)?auth\s+(?:issue|revoke)\b", re.I),
        "minting or revoking an operator token",
    ),
    # The config file and the state it points at. A write is enough — reading
    # `agentfox.toml` is ordinary, overwriting it is how enforcement is turned
    # off without running the CLI at all.
    (
        re.compile(r"(?:>|>>|\btee\b|\brm\b|\bmv\b|\btruncate\b)[^|;&]*\bagentfox\.toml\b", re.I),
        "writing to or removing the AgentFox config file",
    ),
    (
        re.compile(r"\b(?:rm|mv|truncate|shred)\b[^|;&]*\bagentfox\.db\b", re.I),
        "removing the AgentFox database",
    ),
    (
        re.compile(r"\b(?:rm|mv|chmod|chown)\b[^|;&]*(?:/\.agentfox|\$AGENTFOX_STATE_DIR)\b", re.I),
        "tampering with the AgentFox state directory",
    ),
    # Re-pointing the deployment at an empty database is the same outcome as
    # deleting this one, and reads as ordinary configuration.
    (
        re.compile(
            r"\b(?:export\s+|unset\s+)?AGENTFOX_(?:DATABASE_URL|STATE_DIR|CONFIG)\s*=", re.I
        ),
        "re-pointing AgentFox at different state",
    ),
]

#: Shell shapes that are high-impact without being destructive to *data*.
#:
#: `_SHELL_DESTRUCTIVE` below answers "does this wreck something". These answer
#: the questions a destructive-only list misses: does this run code nobody
#: reviewed, read a credential, publish something the world can install, change
#: live infrastructure, or destroy history. Each carries its own code and
#: severity rather than being folded into `shell.destructive`, because a policy
#: that cannot tell `terraform apply` from `rm -rf /` cannot be tuned.
#:
#: Read verbs are deliberately absent throughout. `kubectl get`, `aws s3 ls`,
#: `terraform plan` and `git log` are how an agent is supposed to find out what
#: is going on, and a rule that fires on those gets switched off.
#: Shapes that only exist BETWEEN sub-commands, so they cannot be matched per
#: segment: `_shell_segments` splits on `|` precisely because a pipe is a
#: command boundary, which leaves `curl … | sh` as two innocent halves. These
#: run against the whole command string instead.
_SHELL_WHOLE_COMMAND: list[tuple[re.Pattern[str], str, str, str]] = [
    (
        re.compile(r"\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:ba|z|k|da)?sh\b", re.I),
        "remote-code-execution",
        "critical",
        "pipes a downloaded script straight into a shell",
    ),
    (
        re.compile(
            r"\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:python[\d.]*|node|ruby|perl)\b", re.I
        ),
        "remote-code-execution",
        "critical",
        "pipes a download into an interpreter",
    ),
]

_SHELL_HIGH_IMPACT: list[tuple[re.Pattern[str], str, str, str]] = [
    # --- credentials at rest ---------------------------------------------
    # Matched on the *file*, not the command, so `cat`, `less`, `head`, `xxd`
    # and a bare redirect all land. Writes are the worse half and are caught by
    # the same pattern, which is why the code does not say "read".
    (
        re.compile(
            r"(?:^|[\s/=])(?:\.env(?:\.[\w.-]+)?|id_[re]sa|id_ed25519|\.netrc|\.npmrc|\.pypirc"
            r"|credentials|kubeconfig|\.kube/config|service[-_]account\.json)\b",
            re.I,
        ),
        "credential-file-access",
        "high",
        "touches a file that holds credentials",
    ),
    # --- things the world can then install --------------------------------
    (
        re.compile(
            r"\b(?:npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b|\bcargo\s+publish\b"
            r"|\bgem\s+push\b|\bdocker\s+push\b|\bpoetry\s+publish\b",
            re.I,
        ),
        "supply-chain-publish",
        "high",
        "publishes a package or image others will install",
    ),
    # --- live infrastructure ---------------------------------------------
    # `terraform destroy` and `kubectl delete ns` are already catastrophic in
    # the destructive list; these are the merely-irreversible verbs beside them.
    (
        re.compile(
            r"\bterraform\s+apply\b|\bkubectl\s+(?:apply|delete|scale|patch|replace|drain|cordon)\b"
            r"|\bhelm\s+(?:install|upgrade|uninstall|rollback)\b",
            re.I,
        ),
        "infrastructure-mutation",
        "high",
        "changes live infrastructure",
    ),
    (
        re.compile(
            r"\b(?:aws|az|gcloud)\s+[\w -]*\b(?:delete|terminate|remove|rm|destroy|put|create"
            r"|update|modify|deploy|set-iam-policy|attach-user-policy)\b",
            re.I,
        ),
        "infrastructure-mutation",
        "high",
        "changes cloud resources through a provider CLI",
    ),
    # --- history, which is not recoverable from a backup ------------------
    (
        re.compile(
            r"\bgit\s+reset\s+--hard\b|\bgit\s+clean\s+-[a-z]*[fd]|\bgit\s+stash\s+(?:drop|clear)\b"
            r"|\bgit\s+branch\s+-D\b|\bgit\s+rebase\b.*--force|\bgit\s+filter-branch\b",
            re.I,
        ),
        "history-rewrite",
        "medium",
        "destroys local history that is not in any backup",
    ),
]

#: Shell fragments that are destructive regardless of context. Deliberately narrow:
#: shell has no equivalent of sqlglot, so this is a high-confidence deny-list rather
#: than a claim to analyse shell semantics, and it is documented as such.
_SHELL_DESTRUCTIVE = [
    (re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rf]", re.I), "recursive or forced delete"),
    (re.compile(r"\bmkfs(\.\w+)?\b", re.I), "filesystem format"),
    (re.compile(r"\bdd\s+.*\bof=/dev/", re.I), "raw device write"),
    (re.compile(r">\s*/dev/sd[a-z]", re.I), "raw device write"),
    (re.compile(r"\bdrop\s+database\b", re.I), "database drop"),
    (re.compile(r":\(\)\s*\{.*\};\s*:", re.S), "fork bomb"),
    (re.compile(r"\bchmod\s+(-R\s+)?777\s+/", re.I), "world-writable root"),
    (re.compile(r"\bgit\s+push\s+.*--force", re.I), "force push"),
    (re.compile(r"\bkubectl\s+delete\s+(ns|namespace|all)\b", re.I), "cluster-scope delete"),
    (re.compile(r"\bterraform\s+destroy\b", re.I), "infrastructure destroy"),
    # `kill -9 -1` sends SIGKILL to every process the caller can signal; `kill -9 1`
    # targets init specifically. Both are well-known "kill everything" idioms, not
    # ordinary process management — an unqualified `kill`/`pkill` on a named process
    # is deliberately not matched here, since that's routine and would cost real
    # false positives for a shape that isn't unambiguously catastrophic.
    (re.compile(r"\bkill\s+(-9|-(?:sig)?kill)\s+(-1|1)\b", re.I), "kill-all or kill-init signal"),
    (
        re.compile(r"\busermod\s+.*-a?g\s+(sudo|wheel|admin)\b", re.I),
        "granting sudo/wheel group membership",
    ),
    (re.compile(r">>?\s*/etc/sudoers\b", re.I), "direct write to /etc/sudoers"),
    (re.compile(r"\biptables\s+(-f|--flush)\b", re.I), "firewall rule flush"),
    (re.compile(r"\bufw\s+disable\b", re.I), "firewall disabled"),
    (
        re.compile(r"\b(apt(-get)?|yum|dnf)\s+(purge|remove)\b", re.I),
        "installed package removal",
    ),
]

_UNSAFE_METHODS = {"DELETE", "PUT", "PATCH", "POST"}


def _shell_segments(command: str) -> list[str]:
    """Split a command line into its constituent sub-commands on unquoted `;`,
    `&&`, `||`, `|` — the shape a single whole-string `.search()` treats as one
    blob rather than the several distinct commands it actually is. Quote-aware:
    an operator character sitting inside a quoted string (`echo "a; b"`) is not a
    real segment boundary, so it does not fracture a pattern the un-split string
    would have matched. Falls back to a single segment (the original string) for
    a plain command with no operators at all, which is the common case and keeps
    that path byte-for-byte identical to the pre-tokenization behavior.
    """
    segments: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    i, n = 0, len(command)
    while i < n:
        ch = command[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            i += 1
            continue
        if not in_single and not in_double:
            if command[i : i + 2] in ("&&", "||"):
                segments.append("".join(current))
                current = []
                i += 2
                continue
            if ch in (";", "|"):
                segments.append("".join(current))
                current = []
                i += 1
                continue
        current.append(ch)
        i += 1
    segments.append("".join(current))
    return [s.strip() for s in segments if s.strip()]


def analyse_shell(command: str) -> ActionAnalysis:
    """Deny-list analysis of a shell command.

    Honest about its limits: there is no sqlglot for shell, so this catches known
    catastrophic shapes and makes no claim to understand arbitrary commands. It is a
    backstop, not a sandbox — the primary control for shell remains not granting the
    capability.

    Matched per sub-command (`_shell_segments`), not once over the whole string —
    a single `.search()` over `"echo hi; rm -rf /"` still finds `rm -rf` today (it
    is not anchored to the start), so this is not about missed chained commands;
    it is about the deny-list reasoning over the actual command boundaries a shell
    would use, including not letting an operator inside a quoted string fracture a
    match that spans it.
    """
    analysis = ActionAnalysis(dialect="shell", parsed=True, operation=UNKNOWN)
    analysis.normalised = [command.strip()]
    for pattern, code, severity, label in _SHELL_WHOLE_COMMAND:
        if pattern.search(command):
            analysis.reversible = False
            analysis.blast_radius = "unbounded"
            analysis.risks.append(
                ActionRisk(
                    code=code,
                    severity=severity,
                    detail=f"command {label}",
                    evidence={"pattern": pattern.pattern, "segment": command.strip()},
                )
            )
    for segment in _shell_segments(command):
        for pattern, label in _SHELL_CONTROL_PLANE:
            if pattern.search(segment):
                # Not folded into the destructive list because it is not the same
                # claim. A destructive command harms the business; this one harms
                # the ability to see that it happened, which is why it is called
                # out separately and why the rule matching it cannot be disabled
                # (see policies_data/tool-containment.yaml).
                analysis.operation = DESTRUCTIVE
                analysis.reversible = False
                analysis.blast_radius = "catastrophic"
                analysis.risks.append(
                    ActionRisk(
                        code="control-plane-tamper",
                        severity="critical",
                        detail=f"command disables AgentFox's own enforcement by {label}",
                        evidence={"pattern": pattern.pattern, "segment": segment},
                    )
                )
        for pattern, code, severity, label in _SHELL_HIGH_IMPACT:
            if pattern.search(segment):
                # Not DESTRUCTIVE: these change the world without wrecking data,
                # and calling them destructive would make `action_operation`
                # useless for telling the two apart.
                analysis.reversible = False
                if analysis.blast_radius in (None, "", "none", "unknown"):
                    analysis.blast_radius = "unbounded"
                analysis.risks.append(
                    ActionRisk(
                        code=code,
                        severity=severity,
                        detail=f"command {label}",
                        evidence={"pattern": pattern.pattern, "segment": segment},
                    )
                )
        for pattern, label in _SHELL_DESTRUCTIVE:
            if pattern.search(segment):
                analysis.operation = DESTRUCTIVE
                analysis.reversible = False
                analysis.blast_radius = "catastrophic"
                analysis.risks.append(
                    ActionRisk(
                        code="shell.destructive",
                        severity="critical",
                        detail=f"command performs a {label}",
                        evidence={"pattern": pattern.pattern, "segment": segment},
                    )
                )
    if not analysis.risks:
        analysis.blast_radius = "unknown"
    return analysis


def analyse_http(method: str, url: str, body: Any = None) -> ActionAnalysis:
    """Classify an HTTP action by method and target shape."""
    method = (method or "GET").upper()
    analysis = ActionAnalysis(dialect="http", parsed=True)
    analysis.targets = [url]
    analysis.normalised = [f"{method} {url}"]
    if method in ("GET", "HEAD", "OPTIONS"):
        analysis.operation = READ
        analysis.blast_radius = "none"
        return analysis

    analysis.operation = DESTRUCTIVE if method == "DELETE" else WRITE
    analysis.reversible = method != "DELETE"
    analysis.blast_radius = "bounded"

    # A collection-level unsafe method is the HTTP shape of an unbounded mutation:
    # DELETE /users is not the same class of act as DELETE /users/42.
    path = url.split("?", 1)[0].rstrip("/")
    last = path.rsplit("/", 1)[-1] if "/" in path else path
    collection_like = bool(last) and not re.search(r"[0-9]|[0-9a-f]{8}-[0-9a-f]{4}", last)
    if method in _UNSAFE_METHODS and collection_like and method != "POST":
        analysis.blast_radius = "unbounded"
        analysis.risks.append(
            ActionRisk(
                code="http.collection_mutation",
                severity="critical" if method == "DELETE" else "high",
                detail=f"{method} against a collection endpoint affects every member, "
                "not one record",
                evidence={"url": url},
            )
        )
    return analysis


# ---------------------------------------------------------------------------
# Generic parameter scope anomalies (Tier C — over-privilege via ordinary params)
# ---------------------------------------------------------------------------

#: A benign-sounding request ("show me my order details") can still get translated
#: into an over-broad tool call (`look_up_order(order_id="*")`) — the danger sits in
#: an *ordinary-named* argument the three keyed analysers above never look at,
#: because nothing about the key name ("order_id") suggests it needs SQL/shell/URL
#: scrutiny. This runs on every string argument regardless of key, the same way
#: `injection.heuristic` runs on every message regardless of who's talking.
#: A wildcard/unbounded-scope value where a specific identifier was expected — the
#: whole-collection-instead-of-one-record shape, expressed as a parameter value
#: instead of an HTTP method (that shape is already covered by `analyse_http`).
_WILDCARD_VALUES = {"*", "%", "%%", "all", "any", "everything"}
#: SQL-injection-shaped content arriving in a field nobody declared as SQL. If a
#: caller names their field `sql`/`query`, `analyse_sql` already gives it a real
#: parse; this is the backstop for the field that was never expected to carry SQL
#: at all, e.g. an `order_id` argument holding `1 OR 1=1`. Context-free signals only
#: — every alternative here is a shape no ordinary argument value has an innocent
#: reason to contain, regardless of what else surrounds it. The comment-marker
#: (`--`/`#`/`/*`) is deliberately *not* here — see `_QUOTE_THEN_COMMENT_RE` below
#: for why that one needs context to avoid flagging ordinary prose.
_SQLI_FRAGMENT_RE = re.compile(
    r"(\b(?:OR|AND)\b\s+[\w'\"]+\s*=\s*[\w'\"]+"
    r"|;\s*(?:DROP|DELETE|UPDATE|INSERT)\b"
    r"|\bUNION\b\s+\bSELECT\b"
    r"|\b(?:SLEEP|BENCHMARK|PG_SLEEP)\s*\("
    r"|\bWAITFOR\s+DELAY\b)",
    re.IGNORECASE,
)
#: A SQL line/block comment marker (`--`, `#`, `/*`) is only a strong signal when a
#: quote character appears earlier in the same value — that's the shape a real
#: injection takes (break out of a string literal, then comment out whatever
#: followed in the original query: `' OR 1=1 --`, `admin'--`). A bare `--`/`#` with
#: no quote in sight is at least as often an ASCII em-dash or a hashtag in ordinary
#: prose ("Fragile -- please handle with care"), and treating it as unconditionally
#: suspicious produced real, measured false positives on ordinary argument values
#: (see benchmarks/action_safety/README.md, Dataset 4) — gating on a preceding quote
#: fixes that without giving up recall, since every payload this exists to catch has
#: one. Matches end-of-string too (`admin'--` has nothing after the marker), not
#: just a marker followed by whitespace. `/*` has no such trailing requirement —
#: two literal comment-open characters right after a quote has no innocent reading
#: on its own, regardless of what follows.
_QUOTE_THEN_COMMENT_RE = re.compile(
    r"['\"][^\n]*?(?:(?:--|\#)(?:\s|$)|/\*)",
    re.IGNORECASE,
)
#: `/**/` used as a whitespace substitute (`'/**/OR/**/1=1--`) is a standard filter
#: -evasion technique — a regex expecting `\s` between keywords never sees it.
#: Replacing each block comment with a single space before matching is normalization,
#: not detection: it doesn't decide anything by itself, it just gives the two regexes
#: above the same shot at the de-obfuscated text they'd have had without the evasion.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
#: Path traversal in a value that isn't a declared URL/path argument either.
_PATH_TRAVERSAL_RE = re.compile(r"\.\.[/\\]")


#: A positive list of genuine top-level statement types, not a negative list of
#: trivial ones to exclude — tried the exclusion approach first and it kept finding
#: new trivial-but-not-excluded node types: a hyphenated order number like
#: `ORD-2026-004471` parses as `Sub` (sqlglot reads the hyphens as arithmetic
#: subtraction between a column reference and two numeric literals — a bare
#: expression, not a statement), and a bare Command fallback fires for *any* text
#: sqlglot can't structure, ordinary English included (`Call the office` parses as
#: `Command` exactly like `EXEC xp_cmdshell` does — recognising a leading word as a
#: keyword isn't the same as the text being SQL). Enumerating every real statement
#: shape sqlglot can produce is a stable, closed set in a way "everything trivial"
#: never is. The honest cost: statements only `Command` can represent (`EXEC ...`,
#: `ATTACH ...`) aren't caught by this specific check — see
#: benchmarks/action_safety/README.md, Dataset 4 for why extending into that
#: territory (matching on `Command`'s captured keyword) traded away more than it
#: gained once real English collisions (`Call`, `Attach`) showed up in testing.
_REAL_STATEMENT_NODE_TYPES = frozenset(
    {
        "Select",
        "Insert",
        "Update",
        "Delete",
        "Drop",
        "Alter",
        "Create",
        "Grant",
        "Revoke",
        "Merge",
        "TruncateTable",
        "Union",
        "With",
    }
)


def _parses_as_real_sql_statement(value: str) -> bool:
    if not SQLGLOT_AVAILABLE:
        return False
    try:
        trees = [t for t in sqlglot.parse(value, read="postgres") if t is not None]
    except Exception:
        return False
    if not trees:
        return False
    return all(type(t).__name__ in _REAL_STATEMENT_NODE_TYPES for t in trees)


def _sqli_shaped(value: str) -> str | None:
    """Checks `value` for SQL-injection shape across every reading worth checking:
    the raw text, `normalize()`'s decoded views (catches percent-encoding evasion
    like `'OR%0a1=1--` for free, via the same normalisation `injection.*` already
    relies on), and a `/**/`-as-whitespace-collapsed variant. Returns the risk code
    for the first match found, or `None`.

    Deliberately layered rather than one giant regex: `_SQLI_FRAGMENT_RE`'s
    alternatives need no context, `_QUOTE_THEN_COMMENT_RE` needs a quote earlier in
    the same text, and `_parses_as_real_sql_statement` (a full statement pasted
    whole, e.g. `SELECT table_name FROM information_schema.tables`) needs the value
    to actually parse as one — folding all three into a single check would lose
    that per-check context.
    """
    candidates = [value]
    for view in normalize(value).views:
        if view.text not in candidates:
            candidates.append(view.text)
    decommented = _BLOCK_COMMENT_RE.sub(" ", value)
    if decommented not in candidates:
        candidates.append(decommented)

    for text in candidates:
        if _SQLI_FRAGMENT_RE.search(text):
            return "scope.sql_fragment_in_value"
        if _QUOTE_THEN_COMMENT_RE.search(text):
            return "scope.sql_fragment_in_value"
    if _parses_as_real_sql_statement(value):
        return "scope.sql_statement_in_value"
    return None


def analyse_scope(key: str, value: str) -> ActionAnalysis | None:
    """One ordinary argument, checked for over-broad-scope or injected-value
    shapes. Returns `None` when nothing is found — most arguments, most of the
    time — rather than an empty-but-present analysis."""
    stripped = value.strip()
    if not stripped:
        return None
    analysis = ActionAnalysis(dialect="scope", parsed=True, operation=UNKNOWN)
    analysis.normalised = [stripped]
    analysis.targets = [key]

    if stripped.lower() in _WILDCARD_VALUES:
        analysis.operation = DESTRUCTIVE
        analysis.blast_radius = "unbounded"
        analysis.reversible = False
        analysis.risks.append(
            ActionRisk(
                code="scope.wildcard_value",
                # "critical", not "high": a legitimate identifier argument is never
                # literally the string "*"/"all"/"any" — this is as unambiguous as
                # `sql.destructive_ddl`, so it gets the same automatic-block
                # treatment (enforcement.py's P9 "a critical action risk stands on
                # its own" rule) rather than depending on an operator to author a
                # policy rule for it first.
                severity="critical",
                detail=f"argument '{key}' is a wildcard/unbounded-scope value ('{stripped}') "
                "where a specific identifier was expected — this widens the call from "
                "one record to every record the underlying tool can reach",
                evidence={"key": key, "value": stripped},
            )
        )
    elif (sqli_code := _sqli_shaped(value)) is not None:
        analysis.operation = ADMIN
        analysis.blast_radius = "unbounded"
        analysis.reversible = False
        detail = (
            "contains a full SQL statement"
            if sqli_code == "scope.sql_statement_in_value"
            else "contains a SQL-injection-shaped fragment"
        )
        analysis.risks.append(
            ActionRisk(
                code=sqli_code,
                severity="critical",
                detail=f"argument '{key}' {detail} though it was never declared as a SQL parameter",
                evidence={"key": key},
            )
        )
    elif _PATH_TRAVERSAL_RE.search(value):
        analysis.operation = WRITE
        analysis.blast_radius = "unbounded"
        analysis.risks.append(
            ActionRisk(
                code="scope.path_traversal",
                severity="high",
                detail=f"argument '{key}' contains a path-traversal sequence",
                evidence={"key": key},
            )
        )
    else:
        return None
    return analysis


# ---------------------------------------------------------------------------
# Dispatch and policy shaping
# ---------------------------------------------------------------------------

#: Argument names that conventionally carry an executable artefact. Matching is on the
#: name because that is what the tool's own schema declares.
#: `sql`/`statement`/`command_text` are unambiguous — nothing legitimate names a
#: field that and puts free text in it. `query` is not: it's at least as often a
#: generic search/filter parameter (`search_emails(query=...)`,
#: `search_calendar_events(query=...)`) as it is a raw SQL string, and unlike the
#: other three, ordinary search text can accidentally *succeed* at parsing as SQL
#: (sqlglot reads a bare two-word phrase like "vacation plans" as a column alias)
#: or *fail* to parse for reasons that have nothing to do with risk (three-plus-word
#: phrases usually don't fit any SQL grammar) — so treating every `query` value as
#: SQL doesn't just risk false positives, it produces essentially arbitrary
#: behaviour uncorrelated with actual danger. `_looks_like_sql` gates it: a `query`
#: value is only sent to `analyse_sql` if it actually starts with a SQL verb;
#: otherwise it falls through to the same generic scope backstop an unnamed
#: argument gets.
_SQL_KEYS_UNCONDITIONAL = ("sql", "statement", "command_text")
_SQL_KEYS_AMBIGUOUS = ("query",)
_SQL_LEADING_VERBS = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "MERGE",
    "WITH",
    "EXPLAIN",
    "SHOW",
    "DESCRIBE",
)
_SHELL_KEYS = ("command", "cmd", "script", "shell")
_URL_KEYS = ("url", "endpoint", "path")


def _looks_like_sql(value: str) -> bool:
    first_word = value.strip().split(None, 1)[0].upper() if value.strip() else ""
    return first_word in _SQL_LEADING_VERBS


def _is_sql_argument(key: str, value: Any) -> bool:
    """The exact SQL-detection heuristic `analyse_arguments` uses inline, factored
    out so P18's data-access scoping (`find_sql_argument`, below) can share it
    rather than re-implementing SQL-string detection a second time."""
    if not isinstance(value, str) or not value.strip():
        return False
    lowered = str(key).lower()
    return lowered in _SQL_KEYS_UNCONDITIONAL or (
        lowered in _SQL_KEYS_AMBIGUOUS and _looks_like_sql(value)
    )


#: Nested structures are walked, but not without limit: a tool call is not a document, and
#: an unbounded walk is a latency and memory problem inside a 300ms budget.
_MAX_ARGUMENT_DEPTH = 6
_MAX_ARGUMENT_LEAVES = 256


def walk_arguments(
    arguments: Any, _prefix: str = "", _depth: int = 0, _budget: list[int] | None = None
) -> Any:
    """Yield ``(leaf_key, path, value)`` for every scalar in a tool call, nested included.

    Taint tracking already flattens nested arguments (`guardrails/taint.py::_flatten`), so a
    value buried at `params.sql` carried its provenance correctly — but action assurance
    only ever looked at the top level. The result was a blind spot exactly where a real
    integration puts things: `{"sql": "DELETE FROM customers"}` was blocked, while
    `{"params": {"sql": "DELETE FROM customers"}}` was not analysed at all. Found by the
    adaptive red-team engine's `argument_shape.nested` operator, which flipped a verdict
    from block to allow by doing nothing but re-nesting the same payload.

    The leaf key is yielded alongside the full path because every heuristic here keys off
    the *field name* (`query`, `cmd`, `url`), which is the leaf, while the path is what a
    reader needs to locate the value in the original call.
    """
    budget = _budget if _budget is not None else [_MAX_ARGUMENT_LEAVES]
    if _depth > _MAX_ARGUMENT_DEPTH or budget[0] <= 0:
        return
    if isinstance(arguments, dict):
        for key, value in arguments.items():
            path = f"{_prefix}.{key}" if _prefix else str(key)
            if isinstance(value, (dict, list)):
                yield from walk_arguments(value, path, _depth + 1, budget)
            else:
                budget[0] -= 1
                if budget[0] < 0:
                    return
                yield str(key), path, value
    elif isinstance(arguments, list):
        leaf = _prefix.rsplit(".", 1)[-1] if _prefix else ""
        for index, value in enumerate(arguments):
            path = f"{_prefix}[{index}]"
            if isinstance(value, (dict, list)):
                yield from walk_arguments(value, path, _depth + 1, budget)
            else:
                budget[0] -= 1
                if budget[0] < 0:
                    return
                yield leaf, path, value


def find_sql_argument(arguments: dict[str, Any]) -> str | None:
    """The first argument that looks like a SQL statement, or None.

    Shares `_is_sql_argument`'s detection with `analyse_arguments` so the two never
    drift — a caller wanting the raw statement (P18's `analyse_access`) rather than
    an `ActionAnalysis` uses this instead of duplicating the key/verb heuristics.
    """
    for key, _path, value in walk_arguments(arguments):
        if _is_sql_argument(key, value):
            return value
    return None


def analyse_arguments(
    arguments: dict[str, Any], *, dialect: str = "postgres"
) -> list[ActionAnalysis]:
    """Find and analyse every executable artefact in a tool call's arguments."""
    out: list[ActionAnalysis] = []
    for key, _path, value in walk_arguments(arguments):
        lowered = str(key).lower()
        if isinstance(value, str) and value.strip():
            if _is_sql_argument(key, value):
                out.append(analyse_sql(value, dialect=dialect))
            elif lowered in _SHELL_KEYS:
                out.append(analyse_shell(value))
            elif lowered in _URL_KEYS:
                method = str(arguments.get("method") or arguments.get("http_method") or "GET")
                out.append(analyse_http(method, value, arguments.get("body")))
            else:
                # Not a declared SQL/shell/URL field — still worth a lightweight
                # generic check, since the over-privilege shape (`order_id="*"`)
                # lives in ordinary-named parameters the three checks above never
                # look at at all.
                scope = analyse_scope(key, value)
                if scope is not None:
                    out.append(scope)
    return out


def environment_risk(analysis: ActionAnalysis, environment: str) -> ActionRisk | None:
    """P9-6 — the same statement is a test in staging and an incident in production.

    The 1.9M-row incident was not an unusual statement. It was an ordinary statement
    pointed at the wrong database, which is why the environment has to be part of the
    verdict rather than an operator's assumption.
    """
    if environment.lower() not in PRODUCTION_ENVIRONMENTS:
        return None
    if analysis.reversible and analysis.blast_radius not in ("unbounded", "catastrophic"):
        return None
    return ActionRisk(
        code="action.production_irreversible",
        severity="critical",
        # "bound to environment 'production'" reads as a claim about a live system.
        # In the public sandbox it is not one: the agent fixture simply carries the
        # default value of its own `environment` column, and an anonymous visitor
        # was left wondering whose production this was. The check is unchanged; the
        # sentence now says where the value came from.
        detail=f"irreversible {analysis.operation} action with {analysis.blast_radius} blast "
        f"radius, and the calling agent declares environment '{environment}'",
        evidence={"targets": analysis.targets, "blast_radius": analysis.blast_radius},
    )


def summarise(analyses: list[ActionAnalysis], environment: str = "production") -> dict[str, Any]:
    """Collapse per-argument analyses into the shape the policy engine reasons over."""
    if not analyses:
        return {}
    risks: list[dict[str, Any]] = []
    for analysis in analyses:
        risks.extend(r.to_json() for r in analysis.risks)
        env_risk = environment_risk(analysis, environment)
        if env_risk is not None:
            risks.append(env_risk.to_json())
    operation = max((a.operation for a in analyses), key=lambda o: CLASS_RANK[o])
    radius_rank = {"none": 0, "bounded": 1, "unknown": 2, "unbounded": 3, "catastrophic": 4}
    blast = max((a.blast_radius for a in analyses), key=lambda b: radius_rank.get(b, 2))
    return {
        "operation": operation,
        "blast_radius": blast,
        "reversible": all(a.reversible for a in analyses),
        "parsed": all(a.parsed for a in analyses),
        "targets": sorted({t for a in analyses for t in a.targets}),
        "risks": risks,
        "critical": [r for r in risks if r["severity"] == "critical"],
        "analyses": [a.to_json() for a in analyses],
    }
