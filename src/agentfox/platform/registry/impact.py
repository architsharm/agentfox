"""A tool's impact: declared where someone said it, otherwise inferred from its name.

Containment reasons over `Tool.impact` (``read``, ``write``, ``high_impact``,
``irreversible``), so every place that has to put a number on a tool it has not been
told about asks :func:`infer_impact`: the MCP governor registering a server's tools,
`auto()` registering a tool the model called, the learned-permissions loop suggesting a
declaration, the exposure scan, `agentfox init`'s map, and the coding-agent hooks
declaring a harness's built-in tools.

A name is read as words (:func:`tokens`), never as a substring: "pay" is not in
``display_seat_map``, "send" is not in ``get_sender``, "ship" is not in
``get_membership_status``. Words are read as verb phrases (:func:`actions`): after a
read verb, a word that is also a noun is what is read (``get_refund_status`` reads a
refund, ``get_post`` reads a post), and ``and`` / ``then`` start a new phrase
(``list_and_refund`` lists, then refunds).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def tokens(name: str) -> list[str]:
    """`readCustomerRecord` / `read-customer.record` -> [read, customer, record]."""
    return [t for t in _TOKEN_SPLIT.split(_CAMEL.sub("_", name or "").lower()) if t]


#: Verbs that read. A phrase they start reads; the nouns after them are what it reads.
READ_VERBS = frozenset(
    {
        "read", "get", "list", "search", "lookup", "look", "find", "query", "load",
        "retrieve", "view", "show", "fetch", "export", "open", "cat", "describe",
        "check", "count", "browse", "inspect", "display", "track", "verify", "validate",
        "preview", "summarize", "summarise", "calculate", "estimate", "compare", "is",
        "has", "can",
    }
)  # fmt: skip

#: Words that are verbs at the head of a phrase and nouns after a read verb
#: (``issue_refund`` issues; ``get_issue`` reads an issue).
NOUN_VERBS = frozenset(
    {
        "post", "issue", "message", "email", "mail", "note", "order", "book", "return",
        "transfer", "charge", "refund", "payment", "pay", "update", "set", "run", "record",
        "schedule", "change", "share", "reply", "comment", "draft", "notice", "close",
        "cancel", "start", "credit", "wire", "payout", "request", "submit", "booking",
        "reservation", "invite", "sms", "notify", "publish", "upload", "deploy",
        "transaction", "withdraw", "compensation", "reimbursement", "voucher",
    }
)  # fmt: skip

#: Words that join two phrases.
JOINERS = frozenset({"and", "then"})

#: Verbs that change something. Everything else defaults to read, and an operator can
#: override per tool in the registry — this is a starting classification, not a claim
#: to understand every server's semantics.
WRITE_VERBS = frozenset(
    {
        "create", "update", "delete", "write", "send", "post", "put", "execute", "exec",
        "run", "insert", "edit", "modify", "set", "add", "save", "patch", "upload",
        "submit", "cancel", "book", "reserve", "assign", "approve", "grant", "reset",
        "change", "move", "place", "apply", "schedule", "enroll", "register", "remove",
        "close", "resolve", "reopen", "archive", "merge", "rename", "publish", "notify",
        "reply", "forward", "share", "invite", "refund", "pay", "charge", "transfer",
        "wire", "issue", "start", "drop", "purge", "truncate", "destroy", "wipe",
        "revoke", "deploy", "replace", "append", "upsert", "escalate", "handoff",
        "purchase", "buy", "order", "withdraw", "payout", "compensate", "reimburse",
        "credit", "process", "initiate", "trigger", "mark", "tag", "label", "lock",
        "unlock", "reject", "rebook", "swap", "upgrade", "downgrade", "unsubscribe",
        "subscribe", "sms", "email", "mail", "message", "dm", "tweet", "push",
    }
)  # fmt: skip

#: Of those, the ones that cannot be taken back.
_IRREVERSIBLE_HINTS = frozenset(
    {"delete", "drop", "purge", "send", "transfer", "deploy", "revoke", "destroy",
     "truncate", "wipe"}
)  # fmt: skip

#: Words the hints above do not treat as irreversible but a person would: money moves
#: and messages leave. Only the cautious reading uses them (`auto()`, the
#: learned-permissions suggestion, `agentfox init`), not the MCP governor's registration.
_IRREVERSIBLE_WORDS = frozenset(
    {
        "refund", "pay", "charge", "transfer", "wire", "email", "sms", "message",
        "notify", "publish", "cancel", "close", "payout", "withdraw", "purchase", "buy",
        "compensate", "reimburse",
    }
)  # fmt: skip

#: Verbs a description may use that say the tool changes something. Only words that
#: are never nouns: "the latest update" or "a blog post" describe what is read.
_DESCRIBED = frozenset(
    {"create", "delete", "write", "send", "execute", "insert", "modify", "upload",
     "remove", "drop", "purge", "overwrite", "deploy", "revoke"}
)  # fmt: skip

#: Who a conversation is handed to. ``transfer_to_human`` hands a chat over; it moves
#: no money.
PEOPLE = frozenset(
    {
        "human", "humans", "agent", "agents", "person", "operator", "specialist",
        "representative", "rep", "team", "support", "staff", "teammate", "live",
        "manager", "supervisor", "call", "chat", "conversation", "department", "desk",
    }
)  # fmt: skip


def handoff(toks: list[str]) -> bool:
    """``transfer_to_human`` / ``escalate_to_agent``: the conversation goes to a person."""
    tset = set(toks)
    return bool(tset & {"transfer", "escalate", "handoff", "hand"}) and bool(tset & PEOPLE)


def actions(toks: list[str]) -> list[str]:
    """The words of ``toks`` that act, read as verb phrases.

    A word in :data:`NOUN_VERBS` acts only where it is not the object of a read verb:
    ``get_refund_status`` acts on nothing, ``list_and_refund`` refunds. Every other
    word in :data:`WRITE_VERBS` acts wherever it is (``tickets_close``)."""
    out: list[str] = []
    reading = False
    for t in toks:
        if t in JOINERS:
            reading = False
            continue
        if t in READ_VERBS:
            reading = True
            continue
        if t in WRITE_VERBS and not (reading and t in NOUN_VERBS):
            out.append(t)
            reading = False
    return out


def infer_impact(
    name: str,
    descriptor: dict[str, Any] | None = None,
    *,
    declared: Mapping[str, str] | None = None,
    cautious: bool = False,
) -> str:
    """The impact of the tool called ``name``.

    ``declared`` is a table of known impacts (a harness's built-in tools, say); a name
    in it gets its declared value. Otherwise the impact is guessed from the name and
    the descriptor's description. ``cautious`` also treats a name whose last path
    segment moves money or sends a message as irreversible, the reading for a guess
    that is never confirmed before it is used.
    """
    if declared is not None and name in declared:
        return declared[name]
    toks = tokens(name)
    acts = set(actions(toks))
    # A description's own words count only where they can only be a verb.
    desc = set(tokens(str((descriptor or {}).get("description") or ""))) & _DESCRIBED
    passing = handoff(toks)
    if passing:
        # A chat handed to a person: it changes who answers, nothing irreversible.
        acts = (acts - {"transfer"}) | {"handoff"}
    if (acts | desc) & _IRREVERSIBLE_HINTS:
        return "irreversible"
    if cautious:
        last = set(actions(tokens(name.rsplit("/", 1)[-1])))
        if passing:
            last -= {"transfer"}
        if last & _IRREVERSIBLE_WORDS:
            return "irreversible"
    if acts or desc:
        return "write"
    return "read"


def declare_impact(tool_key: str, impact: str) -> None:
    """Record an impact declared in code (`@fox.tool(impact=...)`) for this process."""
    _DECLARED[tool_key] = impact


def declared_impact(tool_key: str) -> str | None:
    """The impact code in this process declared for ``tool_key``, if any."""
    return _DECLARED.get(tool_key)


#: Tool key -> impact, for every `@fox.tool(key, impact=...)` declared in this
#: process. The decorator also writes the row, but it runs at import time, which can
#: be before the database exists; this is what `auto()` consults when it registers a
#: tool the model called, so a declaration made in code beats a guess from the name
#: even when that write could not happen yet.
_DECLARED: dict[str, str] = {}


__all__ = [
    "NOUN_VERBS",
    "PEOPLE",
    "READ_VERBS",
    "WRITE_VERBS",
    "actions",
    "declare_impact",
    "declared_impact",
    "handoff",
    "infer_impact",
    "tokens",
]
