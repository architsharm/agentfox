"""What counts as a change: pure snapshot diffs, no database."""

from __future__ import annotations

from agentfox.capabilities.discovery.repo import ScanReport, Site
from agentfox.capabilities.monitoring import snapshots as snap


def _report(*sites: Site) -> ScanReport:
    report = ScanReport(root="r", files_scanned=3, code_files_scanned=3)
    report.sites.extend(sites)
    return report


CALL = Site("model_call", "bot/agent.py", 10, "client.chat.completions.create(...)", "openai")
TOOL = Site(
    "tool", "bot/tools.py", 5, "send_email", name="send_email", capabilities=["exfiltration"]
)
TRI = Site("lethal_trifecta", "bot/tools.py", 5, "can read, fetch and send", severity="critical")
MCP = Site("mcp_server", ".mcp.json", 1, "MCP server 'fetch'", name="fetch")


def _moved(site: Site, line: int) -> Site:
    return Site(
        site.kind,
        site.file,
        line,
        site.detail,
        site.provider,
        site.governed,
        site.severity,
        site.name,
    )


def test_a_rescan_that_only_moved_lines_is_not_a_change():
    before = snap.repo_snapshot(_report(CALL, TOOL))
    after = snap.repo_snapshot(_report(_moved(CALL, 40), _moved(TOOL, 90)))
    diff = snap.diff_repo(before, after, label="acme/bot")
    assert diff.new == []
    assert not diff.changed


def test_new_trifecta_ungoverned_call_tool_and_mcp_server_are_conditions():
    before = snap.repo_snapshot(_report())
    after = snap.repo_snapshot(_report(CALL, TOOL, TRI, MCP))
    diff = snap.diff_repo(before, after, label="acme/bot")
    types = sorted(c.type for c in diff.new)
    assert types == sorted(
        [
            snap.LETHAL_TRIFECTA,
            snap.UNGOVERNED_MODEL_CALL,
            snap.NEW_TOOL,
            snap.NEW_MCP_SERVER,
        ]
    )
    severities = {c.type: c.severity for c in diff.new}
    assert severities[snap.LETHAL_TRIFECTA] == "critical"
    assert severities[snap.NEW_TOOL] == "medium", "a tool that can send data out is not low"
    assert all((c.type, c.key) in diff.holding for c in diff.new)


def test_governance_removed_is_its_own_condition_not_a_new_call():
    governed = Site(CALL.kind, CALL.file, CALL.line, CALL.detail, CALL.provider, governed=True)
    before = snap.repo_snapshot(_report(governed))
    after = snap.repo_snapshot(_report(CALL))
    diff = snap.diff_repo(before, after, label="acme/bot")
    assert [c.type for c in diff.new] == [snap.GOVERNANCE_REMOVED]
    assert diff.changes["governance_removed"]

    # Governed again: nothing new, and the condition no longer holds.
    back = snap.diff_repo(after, before, label="acme/bot")
    assert back.new == []
    assert (snap.GOVERNANCE_REMOVED, diff.new[0].key) not in back.holding
    assert back.changes["newly_governed"]


def test_an_inconclusive_scan_is_marked():
    report = ScanReport(root="r", files_scanned=2, code_files_scanned=0)
    assert snap.repo_snapshot(report)["inconclusive"] is True


SPEC_V1 = {
    "info": {"title": "Pets", "version": "1"},
    "paths": {"/pets": {"get": {"summary": "List pets"}}},
}
SPEC_V2 = {
    "info": {"title": "Pets", "version": "2"},
    "paths": {
        "/pets": {"get": {"summary": "List pets"}, "post": {"summary": "Create a pet"}},
        "/pets/{id}": {"delete": {"summary": "Remove a pet"}},
        "/payments": {"post": {"operationId": "refundPayment"}},
    },
}


def test_api_diff_separates_destructive_from_ordinary_new_endpoints():
    diff = snap.diff_api(snap.api_snapshot(SPEC_V1), snap.api_snapshot(SPEC_V2), label="pets")
    by_key = {c.key: c for c in diff.new}
    assert by_key["DELETE /pets/{id}"].type == snap.API_DESTRUCTIVE_ENDPOINT
    assert by_key["DELETE /pets/{id}"].severity == "high"
    assert by_key["POST /payments"].type == snap.API_DESTRUCTIVE_ENDPOINT, "refund via POST"
    assert by_key["POST /pets"].type == snap.API_NEW_ENDPOINT
    assert by_key["POST /pets"].severity == "low"
    assert diff.changes["version"] == ["1", "2"]
    assert "GET /pets" not in by_key


def test_is_destructive_reads_camel_case_and_paths():
    assert snap.is_destructive("post", "/users/{id}/purge")
    assert snap.is_destructive("post", "/x", "deleteUser")
    assert not snap.is_destructive("post", "/search", "Search documents")
    assert not snap.is_destructive("get", "/delete-preview")
