"""Fetches gretelai/synthetic_text_to_sql's HF-hosted parquet exports (train + test),
filters to the rows that actually exercise F3 (destructive-action & blast-radius
analysis — `src/agentfox/capabilities/detection/actions.py::analyse_sql`), derives ground-truth
labels independently of the detector under test, constructs adversarial variants for
the two failure modes the natural data can't supply on its own, and writes a fixed,
reproducible sample to `data/action_safety.json`.

    uv run --with pyarrow python -m benchmarks.action_safety.fetch_gretel_sql

Same reasoning as `fetch_trustairlab.py`: parquet via the `refs/convert/parquet` ref
HF publishes for every dataset, not the paginated `/rows` API.

Ground truth is derived by regex over the raw SQL text, not by calling `analyse_sql`
itself — scoring a detector against labels the detector produced would be circular.
This is a real methodology limitation (regex WHERE-detection can misfire on WHERE
inside a string literal, though gretelai's synthetic SQL is clean enough in practice
that this wasn't observed in spot-checking) and is disclosed as such in
`benchmarks/action_safety/README.md` rather than smoothed over.

Four case categories, each independently labeled:

  - natural_dml: real DELETE/UPDATE statements from the `data manipulation` task
    type, exactly as generated — some organically have no WHERE clause (a genuine
    "clear the whole table" request), some are organically stacked (two related
    statements in one string). Both are real, common shapes a benign user might
    actually produce, not adversarial constructions — this category measures the
    real precision cost of a zero-false-negative design on ordinary requests, not
    an attack.
  - natural_ddl: real CREATE/ALTER/DROP statements from the `data definition` task
    type. ALTER is split into destructive (DROP COLUMN, RENAME) and benign (ADD
    COLUMN) by the same rule `actions.py` itself documents, so this tests whether
    the nuance is actually implemented correctly, not just DROP/CREATE detection.
  - adversarial_unbounded: WHERE clause mechanically stripped from a statement that
    originally had a genuine, bounded one. Tests recall on the constructed attack
    shape (F3.1) with a same-target negative control (the unmodified original).
  - adversarial_tautology: WHERE clause replaced with `1=1` on the same source
    statements. Tests recall on F3.3 specifically.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
from pathlib import Path

try:
    import sqlglot
except ImportError:
    sqlglot = None

DATA_DIR = Path(__file__).parent / "data"
BASE_URL = (
    "https://huggingface.co/datasets/gretelai/synthetic_text_to_sql"
    "/resolve/refs%2Fconvert%2Fparquet/default"
)
SEED = 20260830
SAMPLE_PER_SPLIT = 1200  # of data-manipulation + data-definition rows, per split


def fetch_split(split: str) -> list[dict]:
    import pyarrow.parquet as pq

    dest = DATA_DIR / f"_{split}.parquet"
    subprocess.run(
        ["curl", "-sL", f"{BASE_URL}/{split}/0000.parquet", "-o", str(dest)],
        check=True,
    )
    table = pq.read_table(dest)
    rows = table.to_pylist()
    dest.unlink()
    return rows


_WHERE_RE = re.compile(r"\bWHERE\b", re.I)
_DROP_RE = re.compile(r"^\s*DROP\s+(TABLE|VIEW)\b", re.I)
_TRUNCATE_RE = re.compile(r"^\s*TRUNCATE\b", re.I)
_ALTER_DESTRUCTIVE_RE = re.compile(r"^\s*ALTER\s+TABLE\b.*\b(DROP|RENAME)\b", re.I | re.S)
_ALTER_RE = re.compile(r"^\s*ALTER\s+TABLE\b", re.I)


def split_statements(sql: str) -> list[str]:
    """Naive top-level split on ';' — good enough for gretelai's generated SQL,
    which doesn't embed semicolons inside string literals in practice (spot-checked
    on 500 rows during development). Not a general-purpose SQL splitter."""
    return [s.strip() for s in sql.split(";") if s.strip()]


def parse_bound(statement: str) -> tuple[bool, bool]:
    """Returns (has_where, has_bound) for a single DELETE/UPDATE statement, using
    sqlglot's own parse tree rather than a text regex.

    A first pass at ground truth used "does the substring WHERE appear anywhere in
    the text" — that's wrong for two real shapes this dataset actually contains:
    `UPDATE t SET x = (SELECT ... WHERE ...)` has WHERE only inside a correlated
    subquery that determines the *value*, not which rows get touched — the
    statement is genuinely unbounded (every row gets updated) despite the regex
    match. `UPDATE t SET x = v FROM a JOIN b ON ...` has no WHERE at all but is
    bounded by the JOIN condition — sqlglot's `analyse_sql` doesn't credit this as
    bounding (a real, disclosed limitation — see README.md), so ground truth here
    has to be "bounded, in reality" even where that diverges from what the detector
    currently does, otherwise the benchmark would just be checking the detector
    against itself. `has_bound` is what "should this actually be flagged" ground
    truth uses; `has_where` (narrower) is what feeds the adversarial-variant
    construction below, since stripping a WHERE only makes sense on a statement
    that has one at the top level.
    """
    if sqlglot is None:
        raise RuntimeError("sqlglot is required to build ground truth for this benchmark")
    try:
        tree = sqlglot.parse_one(statement, read="postgres")
    except Exception:
        return False, False
    where = tree.args.get("where")
    from_ = tree.args.get("from_")
    return bool(where), bool(where) or bool(from_)


def has_where(statement: str) -> bool:
    return bool(_WHERE_RE.search(statement))


def strip_where(statement: str) -> str:
    return _WHERE_RE.split(statement, maxsplit=1)[0].rstrip()


def tautology_where(statement: str) -> str:
    before = _WHERE_RE.split(statement, maxsplit=1)[0].rstrip()
    return f"{before} WHERE 1=1"


def is_destructive_ddl(statement: str) -> bool:
    return bool(
        _DROP_RE.match(statement)
        or _TRUNCATE_RE.match(statement)
        or _ALTER_DESTRUCTIVE_RE.match(statement)
    )


def build_cases(rows: list[dict], rng: random.Random) -> dict[str, list[dict]]:
    dml = [r for r in rows if r["sql_task_type"] == "data manipulation"]
    ddl = [r for r in rows if r["sql_task_type"] == "data definition"]

    delete_update = [r for r in dml if re.match(r"^\s*(DELETE|UPDATE)\b", r["sql"], re.I)]

    natural_dml = []
    single_bounded_sources = []  # feeds the adversarial variants
    for r in delete_update:
        statements = split_statements(r["sql"])
        stacked = len(statements) > 1
        stmt_has_where, stmt_has_bound = (None, None) if stacked else parse_bound(statements[0])
        # ground truth: "should this actually be flagged" — stacked, or genuinely
        # unbounded in reality (no WHERE and no FROM/JOIN bounding it), not just
        # "does the text contain the substring WHERE somewhere."
        expect_blocked = stacked or not stmt_has_bound
        natural_dml.append(
            {
                "sql": r["sql"],
                "domain": r["domain"],
                "stacked": stacked,
                "has_where": stmt_has_where,
                "has_bound": stmt_has_bound,
                "expect_blocked": expect_blocked,
            }
        )
        if not stacked and stmt_has_where:
            single_bounded_sources.append(r["sql"])

    natural_ddl = []
    for r in ddl:
        statements = split_statements(r["sql"])
        if len(statements) != 1:
            continue  # keep DDL cases single-statement; stacking is DML's test
        destructive = is_destructive_ddl(statements[0])
        natural_ddl.append(
            {
                "sql": r["sql"],
                "domain": r["domain"],
                "statement_kind": statements[0].split(None, 2)[0:2],
                "expect_blocked": destructive,
            }
        )

    adversarial_unbounded = [
        {"sql": strip_where(sql), "source_sql": sql, "expect_blocked": True}
        for sql in single_bounded_sources
    ]
    adversarial_tautology = [
        {"sql": tautology_where(sql), "source_sql": sql, "expect_blocked": True}
        for sql in single_bounded_sources
    ]

    def sample(items: list[dict], n: int) -> list[dict]:
        return rng.sample(items, min(n, len(items)))

    return {
        "natural_dml": sample(natural_dml, SAMPLE_PER_SPLIT),
        "natural_ddl": sample(natural_ddl, SAMPLE_PER_SPLIT),
        "adversarial_unbounded": sample(adversarial_unbounded, SAMPLE_PER_SPLIT),
        "adversarial_tautology": sample(adversarial_tautology, SAMPLE_PER_SPLIT),
    }


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True, parents=True)
    rng = random.Random(SEED)

    out = {}
    for split in ("train", "test"):
        rows = fetch_split(split)
        print(f"{split}: {len(rows)} rows fetched")
        out[split] = build_cases(rows, rng)
        for category, cases in out[split].items():
            print(f"  {category}: {len(cases)} cases")

    (DATA_DIR / "action_safety.json").write_text(json.dumps(out, indent=2))
    total = sum(len(v) for split in out.values() for v in split.values())
    print(f"\nwrote {total} total cases to data/action_safety.json")


if __name__ == "__main__":
    main()
