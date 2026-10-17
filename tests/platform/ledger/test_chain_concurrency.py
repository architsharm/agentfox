"""Two requests appending to the audit chain at once must both succeed.

Each read the same last entry and claimed its next `seq`; the second insert hit the
unique (org, seq) index and its request returned a 500. Found by denying an approval
while the agent's own requests were still writing.
"""

from __future__ import annotations

from agentfox.core.models import AuditEntry
from agentfox.platform.ledger import chain


def test_an_append_that_loses_the_race_takes_the_next_seq(seeded, monkeypatch):
    first = chain.append(seeded, "test.first", subject_type="t")
    stale = first  # what a concurrent request read as the last entry
    real_scalars = seeded.scalars
    calls = {"n": 0}

    def racing_scalars(statement, *args, **kwargs):
        result = real_scalars(statement, *args, **kwargs)
        if "audit_entries" in str(statement) and calls["n"] == 0:
            calls["n"] += 1
            # Another request appends between this read and this insert.
            monkeypatch.setattr(seeded, "scalars", real_scalars)
            chain.append(seeded, "test.concurrent", subject_type="t")
            monkeypatch.setattr(seeded, "scalars", racing_scalars)

            class Stale:
                def first(self):
                    return stale

            return Stale()
        return result

    monkeypatch.setattr(seeded, "scalars", racing_scalars)
    entry = chain.append(seeded, "test.second", subject_type="t")
    monkeypatch.setattr(seeded, "scalars", real_scalars)
    assert entry.seq == first.seq + 2
    seqs = [e.seq for e in seeded.query(AuditEntry).order_by(AuditEntry.seq)]
    assert len(seqs) == len(set(seqs))
