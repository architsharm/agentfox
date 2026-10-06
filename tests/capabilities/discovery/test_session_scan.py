"""Local AI-tool session scanning (quickscan) — the privacy guarantee is the whole
point of this module, so it's asserted directly: raw message/tool-input content must
never appear anywhere in a report, no matter how it's shaped."""

from __future__ import annotations

import json
from pathlib import Path

from agentfox.capabilities.discovery.sessions import scan_claude_code

SECRET_MARKER = "sk-do-not-leak-this-9f3a7c"


def _write_session(tmp_path: Path, project: str, lines: list[dict]) -> Path:
    project_dir = tmp_path / project
    project_dir.mkdir(parents=True, exist_ok=True)
    session_file = project_dir / "session-1.jsonl"
    with session_file.open("w") as handle:
        for line in lines:
            handle.write(json.dumps(line) + "\n")
    return session_file


def _assistant_turn(*, model: str | None = None, content: list[dict]) -> dict:
    message: dict = {"content": content}
    if model:
        message["model"] = model
    return {"type": "assistant", "message": message}


def test_missing_directory_is_not_an_error(tmp_path: Path):
    report = scan_claude_code(base=tmp_path / "does-not-exist")
    assert report.found is False
    assert report.sessions_found == 0


def test_extracts_tool_names_model_and_mcp_server(tmp_path: Path):
    _write_session(
        tmp_path,
        "-Users-dev-myrepo",
        [
            _assistant_turn(
                model="claude-sonnet-5",
                content=[
                    {"type": "text", "text": SECRET_MARKER},
                    {"type": "tool_use", "name": "Bash", "input": {"command": SECRET_MARKER}},
                    {
                        "type": "tool_use",
                        "name": "mcp__github__create_issue",
                        "input": {"title": SECRET_MARKER},
                    },
                ],
            ),
        ],
    )
    report = scan_claude_code(base=tmp_path)

    assert report.found is True
    assert report.sessions_found == 1
    assert report.sessions_parsed == 1
    assert report.tools_used == {"Bash": 1, "mcp__github__create_issue": 1}
    assert report.mcp_servers == {"github"}
    assert report.models_seen == {"claude-sonnet-5"}
    assert report.projects == {"-Users-dev-myrepo"}


def test_never_leaks_message_or_tool_input_content(tmp_path: Path):
    """The privacy guarantee, asserted directly: whatever the JSON is shaped like,
    the marker value must never surface in the report."""
    _write_session(
        tmp_path,
        "proj",
        [
            _assistant_turn(
                content=[
                    {"type": "text", "text": SECRET_MARKER},
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"file_path": f"/etc/{SECRET_MARKER}"},
                    },
                ]
            ),
            {"type": "user", "message": {"content": [{"type": "text", "text": SECRET_MARKER}]}},
        ],
    )
    report = scan_claude_code(base=tmp_path)

    serialized = json.dumps(report.to_json())
    assert SECRET_MARKER not in serialized
    assert SECRET_MARKER not in repr(report)


def test_malformed_lines_are_skipped_not_fatal(tmp_path: Path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    session_file = project_dir / "session-1.jsonl"
    session_file.write_text("not json\n" + json.dumps(_assistant_turn(content=[])) + "\n")

    report = scan_claude_code(base=tmp_path)

    assert report.sessions_found == 1
    assert report.sessions_parsed == 1


def test_ignores_non_assistant_turns(tmp_path: Path):
    _write_session(
        tmp_path,
        "proj",
        [
            {"type": "user", "message": {"content": [{"type": "text", "text": "hi"}]}},
            {"type": "system", "subtype": "init"},
        ],
    )
    report = scan_claude_code(base=tmp_path)

    assert report.sessions_parsed == 1
    assert report.tools_used == {}
    assert report.models_seen == set()


def test_aggregates_across_multiple_sessions_and_projects(tmp_path: Path):
    _write_session(
        tmp_path,
        "proj-a",
        [_assistant_turn(content=[{"type": "tool_use", "name": "Bash"}])],
    )
    (tmp_path / "proj-b").mkdir()
    (tmp_path / "proj-b" / "session-2.jsonl").write_text(
        json.dumps(_assistant_turn(content=[{"type": "tool_use", "name": "Read"}])) + "\n"
    )

    report = scan_claude_code(base=tmp_path)

    assert report.sessions_found == 2
    assert report.projects == {"proj-a", "proj-b"}
    assert report.tools_used == {"Bash": 1, "Read": 1}
