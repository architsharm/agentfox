"""Scores `src/agentfox/capabilities/grounding/entitlement.py::filter_retrieval`'s purpose-limitation
check (F4.6, GDPR Art. 5(1)(b)) against scenarios built from PrivacyLens's real
vignette content (`data/privacylens.json`, 493 rows, MIT).

    uv run python -m benchmarks.entitlement.run_privacylens_benchmark

**This benchmark is a different kind from every other one in this repo, and
that difference is the point of this docstring.** Every prior benchmark
(action_safety, pii, answerability) scores existing code against a dataset's
*own* ground-truth labels — a public dataset says "this is a driver's license"
or "this is a future-tense question," and the detector is checked against that
external, independently-authored answer. `entitlement.py`'s mechanism has no
public dataset that supplies labels in its shape at all (see
`docs/evaluation/dataset-sourcing.md`'s own "Gap, stated plainly" note, and this repo's
`benchmarks/source_authority/README.md` for the same conclusion reached
independently for F2). What follows instead is a **self-constructed scenario
benchmark**: PrivacyLens supplies real, human-authored, varied *content*
(a data type, a data subject, a sender, a disclosure channel) but the actual
test — what's granted, what purpose is requested, what the correct verdict is
— is built here, not sourced from PrivacyLens's own labels (PrivacyLens itself
doesn't grade contextual-integrity judgments the way `filter_retrieval` makes
them; it grades whether an *executed agent trajectory* leaked data).

### The construction

PrivacyLens's design guarantees every one of its 493 vignettes is an
over-sharing scenario: information retrieved for one purpose (a lawyer's case
notes, for internal case work) is about to be disclosed through an unrelated
channel (a public Facebook post) to an unrelated audience. That structural
guarantee — original purpose and disclosure purpose are *always* different —
is what this benchmark tests mechanically:

  1. Register a `ResourceGrant` for each vignette's resource
     (`privacylens/<name>`), scoped to a single purpose: `"original_collection"`.
  2. **Positive case** (should be withheld): call `filter_retrieval` with
     `purpose=<the vignette's own transmission_principle, slugified>` — e.g.
     `"post_it_on_facebook"`. Since that string is never in the resource's
     declared purposes, this should trigger `reason="purpose_limitation"`.
  3. **Negative case** (should be allowed): call `filter_retrieval` with
     `purpose="original_collection"` — the resource's own declared purpose,
     on the same resource, same principal. This should NOT be withheld.

The negative case isn't from PrivacyLens either — it's the same mechanical
complement used to build adversarial variants elsewhere in this project (e.g.
`benchmarks/action_safety/fetch_gretel_sql.py`'s `adversarial_unbounded`/
`adversarial_tautology`, mechanically derived from real source statements) —
same resource, same principal, only the requested purpose changes, isolating
exactly the one decision this test is about.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = Path(__file__).parent / "results"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def load_dataset() -> list[dict]:
    return json.loads((DATA_DIR / "privacylens.json").read_text())


def main() -> None:
    import os
    import tempfile

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="privacylens_bench_")
    os.environ["AGENTFOX_DATABASE_URL"] = f"sqlite:///{tmpdir}/bench.db"
    os.environ["AGENTFOX_EVIDENCE_DIR"] = f"{tmpdir}/evidence"
    os.environ["AGENTFOX_AUDIT_SIGNING_KEY"] = "bench-key"
    os.environ["AGENTFOX_ALLOW_EGRESS"] = "false"

    from agentfox.capabilities.grounding.entitlement import (
        filter_retrieval,
        grant,
        upsert_principal,
    )
    from agentfox.core import db
    from agentfox.core.config import reset_settings_cache

    reset_settings_cache()
    db.reset_engine()
    db.init_db()

    rows = load_dataset()
    print(f"Loaded {len(rows)} rows")

    pos_tp = pos_fn = 0
    neg_tn = neg_fp = 0
    pos_examples = []
    neg_examples = []
    skipped = 0

    with db.session_scope() as session:
        for i, row in enumerate(rows):
            resource = f"privacylens/{row['name']}"
            subject = f"user_{i}"
            transmission_principle = row["seed"]["transmission_principle"]
            disclosure_purpose = slugify(transmission_principle)
            if not disclosure_purpose or disclosure_purpose == "original_collection":
                skipped += 1
                continue

            principal = upsert_principal(session, subject=subject, groups=[], clearances=[])
            grant(
                session,
                resource=resource,
                principal=subject,
                principal_kind="subject",
                classes=[],
                purposes=["original_collection"],
            )
            chunk = {"source": resource, "text": row["vignette"]["data_type_concrete"]}

            # Positive case: disclosure through the vignette's own (different) channel.
            pos_decision = filter_retrieval(session, principal, [chunk], purpose=disclosure_purpose)
            withheld_correctly = bool(pos_decision.withheld) and any(
                r.startswith("purpose_limitation") for r in pos_decision.reasons
            )
            if withheld_correctly:
                pos_tp += 1
            else:
                pos_fn += 1
                if len(pos_examples) < 10:
                    pos_examples.append(
                        {
                            "name": row["name"],
                            "transmission_principle": transmission_principle,
                            "visible": bool(pos_decision.visible),
                            "reasons": pos_decision.reasons,
                        }
                    )

            # Negative case: same resource, its own declared (original) purpose.
            neg_decision = filter_retrieval(
                session, principal, [chunk], purpose="original_collection"
            )
            allowed_correctly = bool(neg_decision.visible) and not neg_decision.withheld
            if allowed_correctly:
                neg_tn += 1
            else:
                neg_fp += 1
                if len(neg_examples) < 10:
                    neg_examples.append(
                        {
                            "name": row["name"],
                            "reasons": neg_decision.reasons,
                        }
                    )

            if (i + 1) % 100 == 0:
                print(f"  {i + 1}/{len(rows)} rows")

    total_pos = pos_tp + pos_fn
    total_neg = neg_tn + neg_fp
    recall = pos_tp / total_pos if total_pos else 0.0
    fp_rate = neg_fp / total_neg if total_neg else 0.0
    precision = pos_tp / (pos_tp + neg_fp) if (pos_tp + neg_fp) else 0.0

    summary = {
        "dataset": "PrivacyLens main_data.json (MIT) — self-constructed scenario benchmark",
        "rows": len(rows),
        "skipped": skipped,
        "positive_case": {
            "description": "disclosure requested through the vignette's own (different) transmission channel — should be withheld",
            "support": total_pos,
            "tp": pos_tp,
            "fn": pos_fn,
            "recall": round(recall, 4),
        },
        "negative_case": {
            "description": "disclosure requested for the resource's own declared original purpose — should be allowed",
            "support": total_neg,
            "tn": neg_tn,
            "fp": neg_fp,
            "false_positive_rate": round(fp_rate, 4),
        },
        "precision": round(precision, 4),
        "positive_miss_examples": pos_examples,
        "negative_miss_examples": neg_examples,
    }

    out_path = RESULTS_DIR / "privacylens_summary.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {out_path}\n")
    print(f"Positive case (should withhold): recall={recall:.4f} ({pos_tp}/{total_pos})")
    print(f"Negative case (should allow):    FP rate={fp_rate:.4f} ({neg_fp}/{total_neg})")
    print(f"Precision: {precision:.4f}")


if __name__ == "__main__":
    main()
