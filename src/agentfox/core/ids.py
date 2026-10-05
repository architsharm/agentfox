"""Prefixed, lexicographically-sortable identifiers.

Sortable ids matter more here than usual: the audit chain (P5-2) and trace
reconstruction both rely on stable ordering, and a prefix makes an id
self-describing in an evidence package an auditor reads by hand.
"""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford base32, no ambiguous chars


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def new_id(prefix: str) -> str:
    """ULID-ish: 48-bit millisecond timestamp + 40 bits of randomness."""
    ts = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(5), "big")
    return f"{prefix}_{_encode(ts, 10)}{_encode(rand, 8)}"


# Convenience helpers, one per aggregate. Keeps prefixes consistent and greppable.
agent_id = lambda: new_id("agt")  # noqa: E731
tool_id = lambda: new_id("tol")  # noqa: E731
mcp_id = lambda: new_id("mcp")  # noqa: E731
identity_id = lambda: new_id("idn")  # noqa: E731
credential_id = lambda: new_id("crd")  # noqa: E731
capability_id = lambda: new_id("cap")  # noqa: E731
approval_id = lambda: new_id("apr")  # noqa: E731
trace_id = lambda: new_id("trc")  # noqa: E731
span_id = lambda: new_id("spn")  # noqa: E731
decision_id = lambda: new_id("dec")  # noqa: E731
detector_run_id = lambda: new_id("drn")  # noqa: E731
finding_id = lambda: new_id("fnd")  # noqa: E731
policy_id = lambda: new_id("pol")  # noqa: E731
policy_version_id = lambda: new_id("pvr")  # noqa: E731
eval_id = lambda: new_id("evl")  # noqa: E731
run_id = lambda: new_id("run")  # noqa: E731
evidence_id = lambda: new_id("evd")  # noqa: E731
user_id = lambda: new_id("usr")  # noqa: E731
trace_link_id = lambda: new_id("lnk")  # noqa: E731
memory_entry_id = lambda: new_id("mem")  # noqa: E731
agent_signing_key_id = lambda: new_id("ask")  # noqa: E731
agent_message_id = lambda: new_id("amg")  # noqa: E731
policy_canary_id = lambda: new_id("cny")  # noqa: E731
job_id = lambda: new_id("job")  # noqa: E731
waitlist_signup_id = lambda: new_id("wlt")  # noqa: E731
generic_id = new_id
