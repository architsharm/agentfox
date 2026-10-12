"""The opt-in a benchmark needs before it sends dataset text to a third-party API.

Benchmarks run with ``allow_egress`` off like everything else. A script that turns it
on to measure a hosted model has to be told to, each run, with a reason, so a default
invocation never discloses anything. That matters most for the committed datasets that
are real text about real people rather than synthetic:

- ``pii/data/tab_echr_test.json`` (TAB): 127 published European Court of Human Rights
  judgments. Public court records, but they name real applicants, witnesses and
  officials, and sending them to someone else's API puts a copy in that party's logs.

An earlier internal run sent all 127 to a hosted judgment API inside a batch of 7,221
texts that was described as synthetic; the other 7,094 were. This is the check that
would have made that a decision instead of a default.
"""

from __future__ import annotations

#: Committed datasets, relative to ``benchmarks/``, made of real text that names real
#: people. Sending any of them anywhere needs the reason to say so.
REAL_PERSONAL_DATA = frozenset({"pii/data/tab_echr_test.json"})


def require_egress(reason: str | None, *, destination: str, datasets: list[str]) -> None:
    """Exit unless the run was given an explicit reason to send ``datasets`` out.

    ``reason`` is the value of the script's ``--allow-egress`` flag. Without one, print
    what would have been sent and where, and stop before anything is.
    """
    real = sorted(set(datasets) & REAL_PERSONAL_DATA)
    lines = [f"  would send to {destination}:"]
    lines += [
        f"    {d}" + ("  (real, non-synthetic personal data)" if d in real else "")
        for d in datasets
    ]
    if not (reason or "").strip():
        raise SystemExit(
            "refusing to send benchmark data to a third-party API without "
            '--allow-egress "<reason>"\n' + "\n".join(lines)
        )
    print("\n".join(lines))
    print(f"  egress allowed: {reason.strip()}")
