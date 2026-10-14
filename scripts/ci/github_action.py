"""The AgentFox GitHub Action's scan step (see action.yml at the repository root).

Runs the same static scans as `agentfox scan repo` and `agentfox scan skills` on the
checked-out repository, then turns the result into the three things a pull request
reviewer actually reads:

* annotations on the changed lines (``::error`` / ``::warning`` workflow commands),
* a job summary table (``$GITHUB_STEP_SUMMARY``),
* step outputs other steps can branch on (``$GITHUB_OUTPUT``).

Static and offline like the scans themselves: nothing in the repository is imported
or run, and nothing is sent anywhere. The exit code is decided by ``--fail-on``.

    python scripts/ci/github_action.py --path . --fail-on trifecta,skills
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

FAIL_CHOICES = ("trifecta", "skills", "ungoverned", "none")


def _escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def annotation(level: str, message: str, *, file: str, line: int, title: str) -> str:
    """One workflow command, escaped the way the runner expects."""
    props = f"file={_escape_property(file)},line={max(line, 1)},title={_escape_property(title)}"
    return f"::{level} {props}::{_escape_data(message)}"


def _relative(path: str, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path


def collect(root: Path) -> dict[str, Any]:
    """Run the scans. Kept apart from the reporting so it can be tested without a runner."""
    from agentfox.capabilities.discovery.repo import scan
    from agentfox.capabilities.discovery.skills import scan_skills_dir

    repo = scan(root).to_json()
    skills = scan_skills_dir(root)
    for result in skills:
        result["path"] = _relative(result["path"], root)
    return {"repo": repo, "skills": skills}


def annotations(result: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for site in result["repo"]["sites"]:
        kind = site["kind"]
        if kind == "lethal_trifecta":
            fix = (site.get("evidence") or {}).get("fix", "")
            lines.append(
                annotation(
                    "error",
                    site["detail"] + (f"\n\n{fix}" if fix else ""),
                    file=site["file"],
                    line=site["line"],
                    title="AgentFox: lethal trifecta",
                )
            )
        elif kind == "model_call" and not site.get("governed"):
            lines.append(
                annotation(
                    "warning",
                    f"Ungoverned {site.get('provider') or 'model'} call: {site['detail']}. "
                    "Add `import agentfox; agentfox.auto()` to the entry point.",
                    file=site["file"],
                    line=site["line"],
                    title="AgentFox: ungoverned model call",
                )
            )
        elif site.get("severity") in ("critical", "high"):
            lines.append(
                annotation(
                    "warning",
                    site["detail"],
                    file=site["file"],
                    line=site["line"],
                    title=f"AgentFox: {kind.replace('_', ' ')}",
                )
            )
    for skill in result["skills"]:
        for issue in skill["issues"]:
            detail = issue.get("excerpt") or issue.get("risk") or issue.get("location") or ""
            lines.append(
                annotation(
                    "error" if issue["severity"] in ("critical", "high") else "warning",
                    f"Skill '{skill['skill']}': {issue['type'].replace('_', ' ')}"
                    + (f" — {detail}" if detail else ""),
                    file=skill["path"],
                    line=1,
                    title="AgentFox: skill",
                )
            )
    return lines


def counts(result: dict[str, Any]) -> dict[str, int]:
    repo = result["repo"]
    return {
        "trifectas": len(repo["lethal_trifectas"]),
        "ungoverned": int(repo["ungoverned_model_calls"]),
        "model-calls": int(repo["model_calls"]),
        "mcp-servers": int(repo["mcp_servers"]),
        "tools": int(repo["tools"]),
        "skills": len(result["skills"]),
        "skill-issues": sum(len(s["issues"]) for s in result["skills"]),
    }


def summary(result: dict[str, Any], failed: list[str]) -> str:
    c = counts(result)
    verdict = (
        f"**Failed on:** {', '.join(failed)}" if failed else "**Passed** the configured checks."
    )
    rows = [
        ("Lethal trifectas", c["trifectas"]),
        ("Ungoverned model calls", f"{c['ungoverned']} of {c['model-calls']}"),
        ("Skills with planted instructions", f"{c['skill-issues']} issue(s) in {c['skills']}"),
        ("Tools found", c["tools"]),
        ("MCP servers found", c["mcp-servers"]),
    ]
    out = ["## AgentFox scan", "", verdict, "", "| Check | Result |", "|---|---|"]
    out += [f"| {name} | {value} |" for name, value in rows]
    for item in result["repo"]["lethal_trifectas"]:
        out += ["", f"> **Lethal trifecta.** {item['detail']}"]
    out += [
        "",
        "Static scan: nothing was imported, run or sent anywhere. "
        "[What each finding means](https://useagentfox.com/docs/guides/scan-a-repo).",
    ]
    return "\n".join(out) + "\n"


def failures(result: dict[str, Any], fail_on: set[str]) -> list[str]:
    c = counts(result)
    failed = []
    if "trifecta" in fail_on and c["trifectas"]:
        failed.append(f"{c['trifectas']} lethal trifecta(s)")
    if "skills" in fail_on and c["skill-issues"]:
        failed.append(f"{c['skill-issues']} skill issue(s)")
    if "ungoverned" in fail_on and c["ungoverned"]:
        failed.append(f"{c['ungoverned']} ungoverned model call(s)")
    return failed


def _append(env_var: str, text: str) -> None:
    target = os.environ.get(env_var)
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", default=".", help="Directory to scan.")
    parser.add_argument(
        "--fail-on",
        default="trifecta,skills",
        help=f"Comma-separated: {', '.join(FAIL_CHOICES)}.",
    )
    parser.add_argument("--json-out", default="", help="Also write the full result here.")
    args = parser.parse_args(argv)

    fail_on = {part.strip() for part in args.fail_on.split(",") if part.strip()}
    unknown = fail_on - set(FAIL_CHOICES)
    if unknown:
        print(f"unknown fail-on value(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    root = Path(args.path)
    result = collect(root)
    for line in annotations(result):
        print(line)
    failed = failures(result, fail_on)
    _append("GITHUB_STEP_SUMMARY", summary(result, failed))
    _append("GITHUB_OUTPUT", "".join(f"{k}={v}\n" for k, v in counts(result).items()))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2, default=str))

    c = counts(result)
    print(
        f"AgentFox: {c['trifectas']} lethal trifecta(s), {c['ungoverned']} ungoverned "
        f"model call(s), {c['skill-issues']} skill issue(s)."
    )
    if failed:
        print(f"Failing on: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
