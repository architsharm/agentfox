"""SafePyramid as a rule-level guardrail corpus.

Everything measured so far ran on corpora I wrote, which means every result
carries the risk that I also wrote the failure modes. SafePyramid is external,
labelled by someone else, and large enough to settle that.

    ByteDance/SafePyramid, CC-BY-4.0
    3,000 cases, 10 domains, 3 difficulty levels
    each case: a conversation, a policy of 12-37 numbered rules, and the
    exact set of rule numbers that the conversation violates

That last part is what makes it usable here. The unit of judgment is a RULE,
not a case, so the corpus is 77,755 labelled allow/flag decisions at 23.9%
positive — two orders of magnitude more than anything generated locally, and
with the policy text supplied rather than invented.

Two parsing facts worth knowing, both found the hard way:

  * The rules are deliberately SHUFFLED in the policy text (1, 2, 3, 37, 4,
    30, 5 ...). A parser that assumes ascending order silently drops rules
    and loses 2% of cases.
  * A rule's text in the policy may carry a trailing `[overrides: Rule 16]`
    annotation that the rubric omits. The rubric text is a prefix of the
    policy text, not an exact match.

`validate()` checks both, plus that every violated and distractor id resolves,
and is run by `__main__`. It passes 3000/3000 on v1.1.

    python scripts/sp_corpus.py --download   # fetch to the scratch dir
    python scripts/sp_corpus.py              # validate and summarise
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import statistics as st
import sys
import urllib.request

URL = "https://huggingface.co/datasets/ByteDance/SafePyramid/resolve/main/benchmark.json"
DEFAULT = pathlib.Path(
    "/private/tmp/claude-501/-Users-architsharma-guardrails--claude-worktrees-"
    "gap-analysis-failure-modes-2a3ba9/51690438-15cf-42ec-80c2-29ce269bcca9/"
    "scratchpad/data/safepyramid.json"
)

# A rule starts at the beginning of a line and runs to the next line-initial
# "<n>. ". The body may itself contain numbers, section marks and newlines.
RULE = re.compile(r"(?m)^\s*(\d+)\.\s+(.*?)(?=\n\s*\d+\.\s|\Z)", re.S)


def parse_rules(policy: str) -> dict[int, str]:
    """Rule number -> rule text. Order in the document is not rule order."""
    return {int(m.group(1)): " ".join(m.group(2).split()) for m in RULE.finditer(policy)}


def load(path: pathlib.Path = DEFAULT) -> list[dict]:
    return json.loads(path.read_text())["data"]


def validate(cases: list[dict]) -> dict[str, int]:
    bad: collections.Counter = collections.Counter()
    for c in cases:
        r = parse_rules(c["policy"])
        if not set(c["ground_truth_violations"]) <= set(r):
            bad["violated id not found"] += 1
        if not set(c["failure_mode_metadata"].get("distractor_rules", [])) <= set(r):
            bad["distractor id not found"] += 1
        if r and set(r) != set(range(1, max(r) + 1)):
            bad["rule ids are not 1..N"] += 1
        for v in c["rubric"].get("violations", []):
            if not r.get(v["rule"], "").startswith(" ".join(v["text"].split())):
                bad["rubric text mismatch"] += 1
                break
    return dict(bad)


def to_judgments(cases: list[dict]) -> list[dict]:
    """One row per (case, rule): the unit a guardrail actually decides."""
    out = []
    for c in cases:
        rules = parse_rules(c["policy"])
        violated = set(c["ground_truth_violations"])
        distractors = set(c["failure_mode_metadata"].get("distractor_rules", []))
        for n, text in sorted(rules.items()):
            out.append(
                {
                    "id": f"{c['id']}#r{n}",
                    "case_id": c["id"],
                    "domain": c["domain"],
                    "level": c["level"],
                    "rule_no": n,
                    "rule": text,
                    "conversation": c["conversation"],
                    "expect": "flag" if n in violated else "allow",
                    # a non-violated rule the authors designed to look violated:
                    # the false-block stratum, and the only one worth reporting
                    # separately
                    "distractor": n in distractors,
                }
            )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--path", type=pathlib.Path, default=DEFAULT)
    args = ap.parse_args()

    if args.download:
        args.path.parent.mkdir(parents=True, exist_ok=True)
        print(f"  fetching {URL}")
        urllib.request.urlretrieve(URL, args.path)  # noqa: S310
        print(f"  -> {args.path} ({args.path.stat().st_size / 1e6:.0f} MB)")
    if not args.path.exists():
        print(f"not found: {args.path}\nrun with --download", file=sys.stderr)
        return 2

    cases = load(args.path)
    bad = validate(cases)
    print(f"  {len(cases)} cases   validation: {bad or 'clean'}")
    if bad:
        return 1

    rows = to_judgments(cases)
    flag = sum(1 for r in rows if r["expect"] == "flag")
    dis = sum(1 for r in rows if r["distractor"])
    print(f"  {len(rows):,} rule-level judgments   {flag:,} flag ({100 * flag / len(rows):.1f}%)")
    print(f"  {dis:,} of the {len(rows) - flag:,} allows are designed distractors")

    print(f"\n  {'domain':24} {'rules':>8} {'flag':>8} {'rate':>7}")
    by: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        by[r["domain"]][0] += 1
        by[r["domain"]][1] += r["expect"] == "flag"
    for k, (a, b) in sorted(by.items()):
        print(f"  {k:24} {a:>8,} {b:>8,} {100 * b / a:>6.1f}%")

    print(f"\n  {'level':8} {'cases':>7} {'rules/case':>12} {'conv chars':>12}")
    for lv in sorted({c["level"] for c in cases}):
        sub = [c for c in cases if c["level"] == lv]
        nr = [len(parse_rules(c["policy"])) for c in sub]
        cl = [len(c["conversation"]) for c in sub]
        print(f"  {lv:8} {len(sub):>7} {st.median(nr):>12.0f} {st.median(cl):>12,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
