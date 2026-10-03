"""PII detection: 7,221 texts, ~88,000 per-entity-type judgments.

The remaining large block of repo benchmark data. Three datasets the repo
already fetched, each with character-level ground-truth spans:

    presidio-research   1,500   10 in-scope types, synthetic English
    gretel multilingual 5,594   13 in-scope types, 9 languages
    TAB (ECHR)            127    3 in-scope types, real court judgments

Jev classifies; it does not extract spans. So the question is reshaped to the
one it can answer — per text, one Noul per in-scope entity type: *does this
text contain one of these?* Ground truth is "a span of that type exists",
which makes it a fair presence/absence comparison and not a span-matching one.

The expectation going in is that **Jev loses here**, and that is worth
measuring rather than skipping. Finding an email address in a string is a
regex-and-gazetteer problem, the same category as SQL blast radius, and the
shipping detector reaches 51.9% precision on the worst of these datasets only
after two rounds of directed fixes. A negative result here is the same finding
as the SQL one from a second direction.

    JEV_API_KEY=... python scripts/pii_run.py
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sp_run import JEV_URL, _errors, _post  # noqa: E402

HERE = pathlib.Path(__file__).parent
DATA = HERE.parent / "benchmarks" / "pii" / "data"
MAX_CHARS = 6000

#: in-scope types per dataset, taken from each benchmark's own summary so the
#: comparison is against what the shipping detector was scored on
PRESIDIO = [
    "CREDIT_CARD",
    "DATE_TIME",
    "EMAIL_ADDRESS",
    "GPE",
    "IBAN_CODE",
    "IP_ADDRESS",
    "PERSON",
    "PHONE_NUMBER",
    "US_DRIVER_LICENSE",
    "US_SSN",
]
GRETEL = [
    "credit_card_number",
    "date_of_birth",
    "driver_license_number",
    "email",
    "first_name",
    "iban",
    "ipv4",
    "ipv6",
    "last_name",
    "name",
    "passport_number",
    "phone_number",
    "ssn",
]
TAB = ["DATETIME", "LOC", "PERSON"]

DESC = {
    "CREDIT_CARD": "a payment card number",
    "credit_card_number": "a payment card number",
    "DATE_TIME": "a specific date or time",
    "DATETIME": "a specific date or time",
    "date_of_birth": "a date of birth",
    "EMAIL_ADDRESS": "an email address",
    "email": "an email address",
    "GPE": "a country, city or other named place",
    "LOC": "a named place or location",
    "IBAN_CODE": "an IBAN or bank account number",
    "iban": "an IBAN or bank account number",
    "IP_ADDRESS": "an IP address",
    "ipv4": "an IPv4 address",
    "ipv6": "an IPv6 address",
    "PERSON": "a person's name",
    "name": "a person's full name",
    "first_name": "a person's first name",
    "last_name": "a person's surname",
    "PHONE_NUMBER": "a telephone number",
    "phone_number": "a telephone number",
    "US_DRIVER_LICENSE": "a driving licence number",
    "driver_license_number": "a driving licence number",
    "US_SSN": "a social security number",
    "ssn": "a social security number",
    "passport_number": "a passport number",
}


def q(t: str) -> dict:
    d = DESC.get(t, t.replace("_", " ").lower())
    return {
        "type": "noul",
        "instructions": f"Does `text` contain {d}?",
        "criteria": {
            "what": f"{d[0].upper()}{d[1:]} appears somewhere in the text, in any format or language.",
            "not_for": "The text does not contain one, or mentions the idea without giving an actual value.",
        },
    }


def load() -> list[dict]:
    cases = []
    for i, r in enumerate(json.loads((DATA / "synth_dataset_v2.json").read_text())):
        present = {s["entity_type"] for s in (r.get("spans") or [])}
        cases.append(
            {
                "id": f"presidio/{i}",
                "ds": "presidio",
                "types": PRESIDIO,
                "text": r["full_text"][:MAX_CHARS],
                "present": present,
            }
        )
    for i, r in enumerate(json.loads((DATA / "gretel_multilingual_pii.json").read_text())):
        present = {s["label"] for s in (r.get("spans") or [])}
        cases.append(
            {
                "id": f"gretel/{i}",
                "ds": "gretel",
                "types": GRETEL,
                "text": r["text"][:MAX_CHARS],
                "present": present,
                "lang": r.get("language", ""),
            }
        )
    for i, r in enumerate(json.loads((DATA / "tab_echr_test.json").read_text())):
        present = set()
        for ann in (r.get("annotations") or {}).values():
            for m in ann.get("entity_mentions", []):
                present.add(m["entity_type"])
        cases.append(
            {
                "id": f"tab/{i}",
                "ds": "tab",
                "types": TAB,
                "text": r["text"][:MAX_CHARS],
                "present": present,
            }
        )
    return cases


def ask(case: dict) -> dict:
    body = json.dumps(
        {
            "model": "jev-latest",
            "state": {"text": case["text"]},
            "questions": {t: q(t) for t in case["types"]},
        },
        sort_keys=True,
        default=str,
    ).encode()
    res = _post(
        JEV_URL,
        body,
        {
            "Authorization": f"Bearer {os.environ.get('JEV_API_KEY', '')}",
            "Content-Type": "application/json",
        },
    )
    a = res["answers"]
    return {
        "id": case["id"],
        "ds": case["ds"],
        "lang": case.get("lang", ""),
        "p": {t: float(a[t]["noul"]) for t in case["types"]},
        "present": sorted(case["present"] & set(case["types"])),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=14)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    cases = load()
    if args.limit:
        cases = cases[: args.limit]
    for d in ("presidio", "gretel", "tab"):
        sub = [c for c in cases if c["ds"] == d]
        if sub:
            print(f"  {d:10} {len(sub):>5} texts x {len(sub[0]['types'])} types")
    out, t0, done = [], time.perf_counter(), 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(ask, cases):
            out.append(row)
            done += 1
            if done % 700 == 0:
                print(f"  {done}/{len(cases)}  {time.perf_counter() - t0:.0f}s")
    dest = HERE / "pii_jev_results.json"
    dest.write_text(json.dumps({"rows": out}, indent=1, sort_keys=True))
    j = sum(len(r["p"]) for r in out)
    print(f"  {len(out)} texts, {j:,} judgments in {time.perf_counter() - t0:.0f}s -> {dest.name}")
    if _errors:
        print(f"  transport: {dict(_errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
