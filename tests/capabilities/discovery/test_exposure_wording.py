"""Regressions for scan wording (#58, #88a, #88b).

- `tickets_close` was classified as private data + untrusted input, and read as
  "can read tickets closes";
- `crm` read as "can read crms";
- the trifecta branch of the Next panel suggested auto() when every call was governed.
"""

from __future__ import annotations

from agentfox.capabilities.discovery.exposure import EXFIL, PRIVATE, UNTRUSTED, classify_tool
from agentfox.capabilities.discovery.repo import ScanReport, Site


def test_closing_a_ticket_reads_nothing_in():
    for name in ("tickets_close", "tickets.close", "close_ticket", "resolve_issue"):
        caps = classify_tool(name)
        assert PRIVATE not in caps.flags, name
        assert UNTRUSTED not in caps.flags, name


def test_reading_tickets_still_counts():
    caps = classify_tool("tickets_search")
    assert {PRIVATE, UNTRUSTED} <= caps.flags
    assert caps.phrases[PRIVATE] == "can read tickets"


def test_mass_nouns_are_not_pluralised():
    assert classify_tool("crm.lookup").phrases[PRIVATE] == "can read CRM records"
    assert classify_tool("read_crm").phrases[PRIVATE] == "can read CRM records"
    assert classify_tool("query_db").phrases[PRIVATE] == "can read the database"
    assert classify_tool("read_customer_record").phrases[PRIVATE] == "can read customer records"
    assert EXFIL in classify_tool("send_email").flags


def _report(governed: bool) -> ScanReport:
    return ScanReport(
        root=".",
        code_files_scanned=1,
        sites=[
            Site(kind="model_call", file="app.py", line=1, detail="", governed=governed),
            Site(kind="lethal_trifecta", file="app.py", line=1, detail="", severity="critical"),
        ],
    )


def test_trifecta_next_step_only_suggests_auto_when_something_is_ungoverned():
    assert "agentfox.auto()" in _report(governed=False).next_step()
    governed = _report(governed=True).next_step()
    assert "agentfox.auto()" not in governed
    assert "already governed" in governed
