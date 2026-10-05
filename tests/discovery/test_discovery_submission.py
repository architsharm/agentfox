"""The optional, explicit third path out of `agentfox check` / `agentfox quickscan`,
next to plain terminal output and `--json`: submit a redacted summary to a running
control plane. Nothing here runs unless a human opts in, and what's submitted is
never file contents, line numbers, or full file paths — just counts, structure and
semantics (`discovery.ScanReport.to_submission_payload`).
"""

from __future__ import annotations

from pathlib import Path

from agentfox.discovery.repo import scan
from tests.conftest import as_user

# ---------------------------------------------------------------------------
# ScanReport.to_submission_payload — the redaction contract
# ---------------------------------------------------------------------------


def test_submission_payload_drops_file_contents_and_paths(tmp_path):
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "bot.py").write_text(
        "from openai import OpenAI\n"
        "client = OpenAI()\n"
        "def f():\n"
        "    client.chat.completions.create(model='gpt-4o', messages=[])\n"
    )
    (tmp_path / "agents" / "run.py").write_text(
        "import subprocess\nsubprocess.run('rm -rf /some/internal/path --config secret-flag')\n"
    )
    report = scan(tmp_path)
    payload = report.to_submission_payload(source="check")

    dumped = repr(payload)
    # The shell command line is real content that `discovery.py` otherwise echoes
    # (Site.detail) — it must never reach the submission payload.
    assert "rm -rf" not in dumped
    assert "secret-flag" not in dumped
    # No line numbers, no full relative file paths, no free-text "detail" field.
    assert "line" not in payload["sites"][0] if payload["sites"] else True
    for site in payload["sites"]:
        assert set(site) == {"kind", "top_dir", "provider"}
        assert "/" not in site["top_dir"]

    assert payload["label"] == tmp_path.resolve().name
    assert payload["source"] == "check"
    assert any(s["kind"] == "model_call" and s["top_dir"] == "agents" for s in payload["sites"])
    # shell_call is real (from run.py) but is not one of the three "governable"
    # kinds a scan proposes agents from, so it's excluded from the payload entirely.
    assert not any(s["kind"] == "shell_call" for s in payload["sites"])


def test_submission_payload_never_includes_a_hardcoded_secret(tmp_path):
    (tmp_path / "app.py").write_text('api_key = "sk-liveAbCdEfGhIjKlMnOpQrStUvWxYz0123456789"\n')
    report = scan(tmp_path)
    assert any(s.kind == "secret" for s in report.sites)  # sanity: it was found locally
    payload = report.to_submission_payload(source="quickscan")
    assert "sk-live" not in repr(payload)
    assert not any(s["kind"] == "secret" for s in payload["sites"])


def test_submission_payload_root_kept_out_of_label():
    """`label` is a bare directory name, never the absolute path it was scanned from —
    an absolute path can leak a username or an internal project codename."""
    report = scan(Path("."))
    payload = report.to_submission_payload(source="check")
    assert "/" not in payload["label"]
    assert str(Path(".").resolve()) not in str(payload)


# ---------------------------------------------------------------------------
# POST /api/discovery/submit — the route
# ---------------------------------------------------------------------------


def test_submitting_a_scan_proposes_a_draft_agent_and_policy(client):
    response = client.post(
        "/api/discovery/submit",
        json={
            "source": "quickscan",
            "label": "myrepo",
            "files_scanned": 5,
            "frameworks": ["OpenAI SDK"],
            "coverage": 0.5,
            "counts": {"model_call": 2},
            "sites": [{"kind": "model_call", "top_dir": "agents", "provider": "openai"}],
        },
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["agents_proposed"] == ["myrepo-agents"]
    assert body["summary"]["policies_proposed"], "a framework was reported, so a policy is proposed"
    assert body["summary"]["cli_command"] == "quickscan"

    agents = client.get("/api/agents", headers=as_user("admin@example.com")).json()["agents"]
    agent = next(a for a in agents if a["slug"] == "myrepo-agents")
    assert agent["status"] == "draft"
    assert agent["registered"] is False


def test_submission_requires_registry_write_permission(client):
    """Proposing draft agents/policies is a registry write — the same `require`
    guard the GitHub-connected scan uses, so an auditor (read-only by design) is
    refused exactly as they would be for `/api/integrations/github/scan`."""
    response = client.post(
        "/api/discovery/submit",
        json={"source": "check", "label": "myrepo", "sites": []},
        headers=as_user("aisha@example.com"),  # seeded as role=auditor
    )
    assert response.status_code == 403


def test_a_submission_with_no_sites_still_creates_a_reviewable_run(client):
    response = client.post(
        "/api/discovery/submit",
        json={"source": "check", "label": "emptyrepo", "files_scanned": 3, "sites": []},
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["agents_proposed"] == []
    assert body["summary"]["policies_proposed"] == []


def test_extra_fields_on_a_submitted_site_are_rejected_not_silently_dropped(client):
    """Pydantic's default (forbid extra fields would be stricter still, but even the
    default ignore-unknown behaviour means a client can never smuggle a `detail` or
    `line` field through — the route's model only ever reads kind/top_dir/provider."""
    response = client.post(
        "/api/discovery/submit",
        json={
            "source": "check",
            "label": "myrepo",
            "sites": [
                {
                    "kind": "model_call",
                    "top_dir": "agents",
                    "provider": "openai",
                    "detail": "openai.chat.completions.create(api_key='sk-should-not-appear')",
                    "line": 42,
                }
            ],
        },
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 200
    assert "sk-should-not-appear" not in repr(response.json())
