"""One conversation turn is one Activity row (wow3 prove: "1 turn = 3 Activity rows").

``auto()`` reporting to an account checks the person's message, each tool call and
each tool's result through ``/v1/guard/*``, each its own run. Activity listed them as
three rows, the second headed by the tool's name and the third by the tool's output.
Grouped, they are one row headed by what the person asked.
"""

from __future__ import annotations

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
AGENT = "turn-bot"


def _turn(client, asked: str, tool: str, result: str, reply: str) -> list[str]:
    """The calls `auto()` makes for one question that uses one tool."""
    first = client.post("/v1/guard/input", json={"agent": AGENT, "content": asked}).json()
    client.post(
        "/v1/guard/output",
        json={"agent": AGENT, "content": "", "trace_id": first["trace_id"]},
    )
    call = client.post(
        "/v1/guard/tool_call", json={"agent": AGENT, "tool": tool, "arguments": {}}
    ).json()
    second = client.post(
        "/v1/guard/input",
        json={"agent": AGENT, "content": result, "taint_source": "tool_result"},
    ).json()
    client.post(
        "/v1/guard/output",
        json={"agent": AGENT, "content": reply, "trace_id": second["trace_id"]},
    )
    return [first["trace_id"], call["trace_id"], second["trace_id"]]


def test_a_turn_with_a_tool_is_one_row_headed_by_the_question(client):
    ids_1 = _turn(client, "please list the files here", "file_read", ".agentfox app.py", "Two.")
    ids_2 = _turn(client, "write a note for me", "file_write", "ok", "Done.")

    ungrouped = client.get(f"/api/traces?agent={AGENT}", headers=ADMIN).json()["traces"]
    assert len(ungrouped) == 6

    rows = client.get(f"/api/traces?agent={AGENT}&group=true", headers=ADMIN).json()["traces"]
    assert [r["summary"] for r in rows] == ["write a note for me", "please list the files here"]
    assert rows[0]["trace_ids"] == ids_2
    assert rows[1]["trace_ids"] == ids_1
    assert rows[1]["id"] == ids_1[0]  # the row opens the run the person started
    assert rows[1]["runs"] == 3
    assert "file_read" in rows[1]["tools"]


def test_a_tools_output_is_never_the_runs_request(client):
    """The tool's result checked as input used to become the run's summary."""
    result = client.post(
        "/v1/guard/input",
        json={"agent": AGENT, "content": ".agentfox app.py", "taint_source": "tool_result"},
    ).json()
    rows = client.get(f"/api/traces?agent={AGENT}", headers=ADMIN).json()["traces"]
    row = next(r for r in rows if r["id"] == result["trace_id"])
    assert row["summary"] is None


def test_separate_questions_stay_separate_rows(client):
    for q in ("hi there", "what is the time?", "hi there"):
        client.post("/v1/guard/input", json={"agent": AGENT, "content": q})
    rows = client.get(f"/api/traces?agent={AGENT}&group=true", headers=ADMIN).json()["traces"]
    # The repeat of "hi there" comes after a different question: its own turn.
    assert [r["summary"] for r in rows] == ["hi there", "what is the time?", "hi there"]


def test_a_session_still_groups_by_turn_not_whole_conversation(client):
    sid = "sess-turns-1"
    for q in ("first question", "second question"):
        t = client.post(
            "/v1/guard/input", json={"agent": AGENT, "content": q, "session_id": sid}
        ).json()["trace_id"]
        client.post(
            "/v1/guard/tool_call",
            json={"agent": AGENT, "tool": "lookup", "arguments": {}, "session_id": sid},
        )
        client.post(
            "/v1/guard/output",
            json={"agent": AGENT, "content": "answer", "trace_id": t, "session_id": sid},
        )
    rows = client.get(f"/api/traces?agent={AGENT}&group=true", headers=ADMIN).json()["traces"]
    assert [(r["summary"], r["runs"]) for r in rows] == [
        ("second question", 2),
        ("first question", 2),
    ]
