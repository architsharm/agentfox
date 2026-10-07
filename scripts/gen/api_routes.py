#!/usr/bin/env python3
"""Regenerate the route tables in docs/architecture/api-spec.md from the live FastAPI app.

The hand-written route list drifted from the code (phantom routes, missing families), so
the tables between the GENERATED markers are now produced from `create_app().openapi()`.
Prose around them stays hand-written.

    uv run python scripts/gen/api_routes.py            # print the generated block
    uv run python scripts/gen/api_routes.py --write    # rewrite the block in Appendix C
    uv run python scripts/gen/api_routes.py --check    # exit 1 if Appendix C is out of date
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "architecture" / "api-spec.md"
BEGIN = "<!-- BEGIN GENERATED ROUTES: scripts/gen/api_routes.py --write -->"
END = "<!-- END GENERATED ROUTES -->"

# Section order and titles, keyed by the first path segment(s) after /api or /v1.
SECTIONS: list[tuple[str, tuple[str, ...]]] = [
    ("Inline enforcement (`/v1`)", ("/v1/",)),
    (
        "Platform and onboarding",
        (
            "/api/health",
            "/api/version",
            "/api/detectors",
            "/api/providers",
            "/api/reliability",
            "/api/me",
            "/api/onboarding",
            "/api/attention",
            "/metrics",
        ),
    ),
    (
        "Registry, discovery and findings (Pillar 1)",
        (
            "/api/agents",
            "/api/agent-controls",
            "/api/discovery",
            "/api/tools",
            "/api/mcp-servers",
            "/api/findings",
        ),
    ),
    (
        "Identity, credentials, approvals (Pillar 2)",
        ("/api/identities", "/api/credentials", "/api/approvals", "/api/tokens"),
    ),
    ("Policy (Pillars 2, 3, 12)", ("/api/policies",)),
    ("Guardrail tuning (Pillar 3)", ("/api/guardrails",)),
    ("Evaluation and red team (Pillar 4)", ("/api/eval", "/api/redteam", "/api/probes")),
    (
        "Audit, traces and evidence (Pillar 5)",
        (
            "/api/traces",
            "/api/audit",
            "/api/export",
            "/api/evidence",
            "/api/retention",
            "/api/legal-holds",
        ),
    ),
    (
        "Compliance and risk (Pillar 6)",
        (
            "/api/controls",
            "/api/frameworks",
            "/api/compliance",
            "/api/risk",
            "/api/obligations",
            "/api/board",
        ),
    ),
    (
        "Answerability, sources, entitlement, escalation (P7, P8, P10, P11)",
        ("/api/answerability", "/api/sources", "/api/entitlement", "/api/escalation"),
    ),
    ("Memory and inter-agent messaging (P16, P17)", ("/api/memory", "/api/agent-messages")),
    (
        "Jobs, monitors and integrations",
        (
            "/api/jobs",
            "/api/internal",
            "/api/monitors",
            "/api/alerts",
            "/api/integrations",
            "/api/auth",
        ),
    ),
    ("Playground (unauthenticated, rate-limited)", ("/api/playground",)),
    ("Public showcase (unauthenticated, cached, rate-limited)", ("/api/public",)),
]


def _app_paths() -> dict:
    os.environ.setdefault("NOMETRIA_DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/routes.db")
    sys.path.insert(0, str(REPO / "src"))
    from agentfox.apps.gateway.app import create_app

    return create_app().openapi()["paths"]


def _section_for(path: str) -> str:
    # Agent-scoped messaging keys live under /api/agents/{slug}/signing-key; keep with messaging.
    if path.endswith("/signing-key"):
        return "Memory and inter-agent messaging (P16, P17)"
    if path.startswith("/api/agents/") and path.endswith(("/approve", "/reject")):
        return "Jobs, monitors and integrations"
    for title, prefixes in SECTIONS:
        if path.startswith(prefixes):
            return title
    return "Other"


def _summary(op: dict) -> str:
    text = (op.get("summary") or "").strip()
    desc = (op.get("description") or "").strip().splitlines()
    first = desc[0].strip() if desc else ""
    out = first or text
    return out.replace("|", "\\|")[:140]


def render() -> str:
    grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for path, ops in _app_paths().items():
        for method, op in ops.items():
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            grouped[_section_for(path)].append((path, method.upper(), _summary(op)))
    total = sum(len(v) for v in grouped.values())
    lines = [
        BEGIN,
        "",
        f"{total} operations, generated from the running app's OpenAPI document. "
        "Request and response schemas: `GET /openapi.json` or the interactive `/docs`.",
        "",
    ]
    order = [t for t, _ in SECTIONS] + ["Other"]
    for title in order:
        rows = sorted(grouped.get(title, []), key=lambda r: (r[0], r[1]))
        if not rows:
            continue
        lines += [f"### {title}", "", "| Method | Path | Purpose |", "|---|---|---|"]
        lines += [f"| `{m}` | `{p}` | {s} |" for p, m, s in rows]
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


def main() -> int:
    block = render()
    doc = DOC.read_text()
    if BEGIN not in doc or END not in doc:
        print(f"markers missing in {DOC}", file=sys.stderr)
        return 2
    current = doc[doc.index(BEGIN) : doc.index(END) + len(END)]
    if "--write" in sys.argv:
        DOC.write_text(doc.replace(current, block))
        print(f"wrote {DOC.relative_to(REPO)}")
        return 0
    if "--check" in sys.argv:
        if current != block:
            print(
                "docs/architecture/api-spec.md route tables are out of date: "
                "run scripts/gen/api_routes.py --write"
            )
            return 1
        print("appendix C route tables are current")
        return 0
    print(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
