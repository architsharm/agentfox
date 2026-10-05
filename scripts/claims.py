#!/usr/bin/env python3
"""Every headline number we publish is bound to the result it came from.

    uv run python scripts/claims.py            # list claims with their current values
    uv run python scripts/claims.py --check    # exit 1 if any document drifted from its source

A benchmark number typed into a README is a claim that silently goes stale the next time the
benchmark changes. This renders each claim in `benchmarks/claims.yaml` from its result file and
checks every document that quotes it still says exactly that. Matching ignores markdown emphasis
and line wraps, so reflowing a paragraph never breaks it; changing a number does.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "benchmarks" / "claims.yaml"


@dataclass
class Drift:
    claim: str
    file: str
    expected: str
    reason: str


def _lookup(data: Any, path: list[Any]) -> Any:
    for key in path:
        data = data[key]
    return data


def render_values(claim: dict[str, Any], data: Any) -> dict[str, str]:
    kind = claim["render"]
    if kind == "fraction":
        raw = str(_lookup(data, claim["path"]))
        match = re.match(r"\s*(\d+)\s*/\s*(\d+)", raw)
        if not match:
            raise ValueError(f"{claim['id']}: expected 'n/d' at {claim['path']}, got {raw!r}")
        return {"n": match.group(1), "d": match.group(2)}
    if kind == "sum_fraction":
        numerator = int(_lookup(data, claim["numerator"]))
        remainder = int(_lookup(data, claim["remainder"]))
        return {"n": str(numerator), "d": str(numerator + remainder)}
    if kind == "ratio":
        return {
            "n": str(int(_lookup(data, claim["numerator"]))),
            "d": str(int(_lookup(data, claim["denominator"]))),
        }
    if kind == "percent":
        value = float(_lookup(data, claim["path"]))
        return {"pct": f"{value * 100:.{int(claim.get('decimals', 0))}f}"}
    if kind == "fields":
        out: dict[str, str] = {}
        for name, spec in claim["fields"].items():
            spec = spec if isinstance(spec, dict) else {"path": spec}
            value = _lookup(data, spec["path"])
            if isinstance(value, (dict, list)):
                raise ValueError(f"{claim['id']}: expected a scalar at {spec['path']}")
            if "format" in spec:
                value = format(float(value) * float(spec.get("scale", 1)), spec["format"])
            out[name] = str(value)
        return out
    if kind == "value":
        value = _lookup(data, claim["path"])
        if isinstance(value, (dict, list)):
            raise ValueError(f"{claim['id']}: expected a scalar at {claim['path']}")
        if "format" in claim:
            value = format(float(value) * float(claim.get("scale", 1)), claim["format"])
        return {"v": str(value)}
    raise ValueError(f"{claim['id']}: unknown render {kind!r}")


def normalise(text: str) -> str:
    """Drop markdown emphasis and collapse all whitespace, so reflowing never breaks a match."""
    return re.sub(r"\s+", " ", text.replace("*", "")).strip()


def _doc(docs: dict[str, str], repo: Path, file: str) -> str:
    if file not in docs:
        path = repo / file
        docs[file] = normalise(path.read_text()) if path.exists() else ""
    return docs[file]


def check(manifest: Path = MANIFEST, repo: Path = REPO) -> tuple[list[dict[str, Any]], list[Drift]]:
    loaded = yaml.safe_load(manifest.read_text())
    claims = loaded["claims"]
    sources: dict[str, Any] = {}
    docs: dict[str, str] = {}
    table: list[dict[str, Any]] = []
    drifts: list[Drift] = []
    for claim in claims:
        source = claim["source"]
        if source not in sources:
            sources[source] = json.loads((repo / source).read_text())
        try:
            values = render_values(claim, sources[source])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            drifts.append(Drift(claim["id"], source, "", f"source value unreadable: {exc}"))
            continue
        table.append({"id": claim["id"], **values, "quotes": len(claim["quoted_in"])})
        for quote in claim["quoted_in"]:
            file = quote["file"]
            expected = normalise(quote["text"].format(**values))
            if expected not in _doc(docs, repo, file):
                drifts.append(
                    Drift(
                        claim["id"], file, expected, "document no longer says what the result says"
                    )
                )
    # A figure that was withdrawn must not come back: binding only catches numbers that are
    # still bound, and a superseded number that a document keeps quoting is the drift that
    # the bound check cannot see.
    for retired in loaded.get("retired", []):
        phrase = normalise(retired["text"])
        for file in retired["files"]:
            if phrase in _doc(docs, repo, file):
                drifts.append(
                    Drift(retired["id"], file, "", f"quotes a retired figure: {retired['reason']}")
                )
    return table, drifts


def main() -> int:
    table, drifts = check()
    if "--check" not in sys.argv:
        for row in table:
            fields = {k: v for k, v in row.items() if k not in ("id", "quotes")}
            if set(fields) == {"n", "d"}:
                value = f"{row['n']}/{row['d']}"
            elif set(fields) == {"pct"}:
                value = f"{row['pct']}%"
            elif set(fields) == {"v"}:
                value = row["v"]
            else:
                value = ", ".join(f"{k}={v}" for k, v in fields.items())
            print(f"  {row['id']:58s} {value:>9s}   quoted in {row['quotes']} place(s)")
    if drifts:
        print(f"\n{len(drifts)} published claim(s) drifted from their source:")
        for drift in drifts:
            print(f"  - {drift.claim} in {drift.file}: {drift.reason}")
            if drift.expected:
                print(f"      expected to find: {drift.expected!r}")
        return 1
    if "--check" in sys.argv:
        print(f"all {len(table)} published claims match their sources")
    return 0


if __name__ == "__main__":
    sys.exit(main())
