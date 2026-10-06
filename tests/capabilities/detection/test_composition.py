"""F3.8 — composed privilege escalation (P9-11).

A read tool's output, chained into a write tool's argument, is a composition
neither tool's own scope permits alone — see `guardrails/composition.py`'s
module docstring for the full failure-mode description and why it needed the
taint tracker's existing `propagated_from` provenance rather than a new
tracking mechanism.
"""

from __future__ import annotations

from agentfox.capabilities.detection.composition import (
    check_composed_escalation,
    tool_key_from_origin,
)
from agentfox.core.models import Agent
from agentfox.integrations.mcp import McpGovernor, tool_key
from agentfox.platform.identity import ensure_identity, grant_capability

SERVER = "patient-records"
TOOLS = [
    {
        "name": "search_patients",
        "description": "Look up a patient record by name.",
        "inputSchema": {"type": "object"},
    },
    {
        "name": "transfer_records",
        "description": "Transfer a patient's records to another provider.",
        "inputSchema": {"type": "object"},
    },
]


def _governor(seeded):
    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    identity = ensure_identity(seeded, agent)
    for tool in TOOLS:
        grant_capability(seeded, identity, tool_key(SERVER, tool["name"]), max_taint="tool_result")
    gov = McpGovernor(session=seeded, agent_slug="support-triage", server_name=SERVER)
    gov.register_tools(TOOLS)
    return gov


# ---------------------------------------------------------------------------
# Pure-function unit tests
# ---------------------------------------------------------------------------


def test_tool_key_is_recovered_from_the_mcp_path_convention():
    """The taint mark's path (`mcp.<server>.<tool>`) and the tool's actual
    *registered* key (`integrations.mcp.tool_key()`'s `mcp:<server>/<tool>`) are
    different formats in the same module — this must reconstruct the registered
    one, or the DB lookup in enforcement.py silently misses every time."""
    assert (
        tool_key_from_origin("mcp.patient-records.search_patients")
        == "mcp:patient-records/search_patients"
    )


def test_a_dotted_tool_key_survives_the_mcp_path_split():
    """A tool key with its own dots (e.g. `db.query`) must not be truncated by the
    `mcp.<server>.<tool>` path's own dot-delimiting."""
    assert tool_key_from_origin("mcp.myserver.db.query") == "mcp:myserver/db.query"


def test_tool_key_is_recovered_from_the_sdk_path_convention():
    assert tool_key_from_origin("tool:crm.lookup#3") == "crm.lookup"


def test_an_unidentified_path_names_no_tool():
    """`$.content`, `$.messages[i].content`, an untagged `$.tool_result[...]` — none
    of these identify a producing tool, and a composed-escalation check has nothing
    to compare against, so it must not guess."""
    assert tool_key_from_origin("$.content") is None
    assert tool_key_from_origin("$.tool_result[2]") is None


def test_a_read_tools_output_flowing_into_a_write_tool_is_flagged():
    origin_key = "mcp:patient-records/search_patients"
    findings = check_composed_escalation(
        consuming_tool_key="mcp:patient-records/transfer_records",
        consuming_tool_impact="irreversible",
        argument_propagated_from={"patient_id": "mcp.patient-records.search_patients"},
        tool_impact_lookup=lambda key: {origin_key: "read"}.get(key),
    )
    assert len(findings) == 1
    assert findings[0].origin_tool == origin_key
    assert findings[0].origin_impact == "read"
    assert findings[0].consuming_tool == "mcp:patient-records/transfer_records"
    assert origin_key in findings[0].reason
    assert "transfer_records" in findings[0].reason


def test_a_tools_own_prior_output_feeding_its_own_next_call_is_not_flagged():
    """Pagination — a tool consuming its own earlier page token — is not a
    cross-tool composition and must not be flagged as one."""
    origin_key = "mcp:patient-records/search_patients"
    findings = check_composed_escalation(
        consuming_tool_key=origin_key,
        consuming_tool_impact="read",
        argument_propagated_from={"page_token": "mcp.patient-records.search_patients"},
        tool_impact_lookup=lambda key: {origin_key: "read"}.get(key),
    )
    assert findings == []


def test_read_tool_output_flowing_into_another_read_tool_is_not_flagged():
    """No impact delta, no escalation — a read chained into a read is ordinary
    multi-step retrieval, not a privilege composition."""
    origin_key = "mcp:patient-records/search_patients"
    findings = check_composed_escalation(
        consuming_tool_key="mcp:patient-records/search_records_v2",
        consuming_tool_impact="read",
        argument_propagated_from={"id": "mcp.patient-records.search_patients"},
        tool_impact_lookup=lambda key: {origin_key: "read"}.get(key),
    )
    assert findings == []


def test_an_unregistered_origin_tool_is_skipped_not_assumed():
    """A tool the lookup doesn't recognise can't be scope-compared either way —
    skipped rather than treated as automatically safe or automatically dangerous."""
    findings = check_composed_escalation(
        consuming_tool_key="transfer_records",
        consuming_tool_impact="irreversible",
        argument_propagated_from={"patient_id": "mcp.other-server.unknown_tool"},
        tool_impact_lookup=lambda key: None,
    )
    assert findings == []


def test_caller_declared_provenance_is_not_a_silent_composition():
    """`argument_propagated_from` only carries *inferred* provenance
    (`TaintMark.propagated_from`) — a value the caller explicitly declared the
    source of was never silent in the first place, and enforcement.py never
    populates this dict from a declared mark. Documented here as the contract,
    not exercised against the DB-backed path (covered by the integration test
    below instead)."""
    findings = check_composed_escalation(
        consuming_tool_key="transfer_records",
        consuming_tool_impact="irreversible",
        argument_propagated_from={},  # nothing inferred -> nothing to flag
        tool_impact_lookup=lambda key: "read",
    )
    assert findings == []


# ---------------------------------------------------------------------------
# End-to-end through the live enforcement path
# ---------------------------------------------------------------------------


def test_an_internal_id_surfaced_by_a_read_tool_and_reused_by_a_write_tool_is_blocked(seeded):
    gov = _governor(seeded)
    read = gov.call(
        "search_patients",
        {"name": "Jane Doe"},
        transport=lambda tool, args: {"patient_internal_id": "PT-9182734-INTERNAL"},
    )
    assert read.allowed

    write = gov.call(
        "transfer_records",
        {"patient_id": "PT-9182734-INTERNAL", "destination": "external-clinic"},
        transport=lambda tool, args: {"status": "transferred"},
    )
    assert not write.allowed
    reasons = " ".join(r.get("reason", "") for r in write.pre_decision.rules_fired)
    assert "search_patients" in reasons
    assert "transfer_records" in reasons


def test_a_write_call_with_independently_supplied_arguments_is_not_blocked_for_composition(seeded):
    """The negative control: the same write tool, called with a value that never
    appeared in any prior tool result, must not be flagged by this check — proving
    the block above is about provenance, not about the tool being write-scoped."""
    gov = _governor(seeded)
    read = gov.call(
        "search_patients",
        {"name": "Jane Doe"},
        transport=lambda tool, args: {"patient_internal_id": "PT-9182734-INTERNAL"},
    )
    assert read.allowed

    write = gov.call(
        "transfer_records",
        {"patient_id": "PT-USER-SUPPLIED-0001", "destination": "external-clinic"},
        transport=lambda tool, args: {"status": "transferred"},
    )
    rule_ids = {r.get("rule_id") for r in write.pre_decision.rules_fired}
    assert "composition.escalation" not in rule_ids
