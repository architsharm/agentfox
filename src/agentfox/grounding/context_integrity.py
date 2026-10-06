"""Context integrity.

*"The answer was grounded in the retrieved context. The retrieved context was junk."*

Every quality metric this product already computes looks at the far end of the pipe.
Groundedness compares the answer to the context; provenance asks whether the source was
authoritative; answerability asks whether the question was in scope. All three can pass
on a context that was destroyed before the model ever saw it — by a PDF extractor that
dropped the spaces, by a chunker that split a sentence in half, by a token budget that
cut the one paragraph the citation depended on.

That failure is invisible from the far end. A model handed a mangled context does not
report a mangled context; it answers confidently from whatever survived, and the answer
is *fluent*, which is exactly what makes it dangerous. The evidence base put this whole
family at zero coverage, and the reason is structural: nobody instruments the middle.

So these are gates on the pipe itself, and they share one property — they are all
computable without a model. Whether a chunk ends mid-sentence, whether a document is
mojibake, whether the top-ranked passage survived truncation, whether nDCG dropped
after an embedding change: each is a measurement, not a judgement. That matters here
more than elsewhere, because a model-based check on a corrupted context is being asked
to read the same corruption it is meant to detect.

Ordering note: `assemble_context` both diagnoses and repairs. Reordering is the one
mitigation in this module that is safe to apply automatically — moving the strongest
passage to the front changes nothing about what the model is shown, only where. Every
other finding is reported and left to policy, because dropping a corrupt document is a
decision with a cost that belongs to the operator.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from agentfox.core.finding import RiskFinding

# --- Findings --------------------------------------------------------------

#: Advisory. Something is off; the pipeline is still usable.
WARN = "warn"
#: The context is degraded enough that an answer built on it should be caveated or
#: withheld. Maps onto `abstain` in the enforcement lattice.
DEGRADED = "degraded"
#: The input should not enter the corpus at all.
REJECT = "reject"

_SEVERITY_RANK = {WARN: 0, DEGRADED: 1, REJECT: 2}

#: How a context-integrity finding lands in the enforcement lattice. Deliberately
#: conservative: a corrupt *document* is refused at ingestion, but a degraded *context*
#: at answer time abstains rather than blocks — the question may still be answerable
#: from the parts that survived, and refusing outright trains people to route around
#: the gate.
VERDICT_FOR = {WARN: "allow", DEGRADED: "abstain", REJECT: "block"}


@dataclass
class Finding(RiskFinding):
    """One measurable defect in the context pipeline — same shape as `RiskFinding`,
    plus the verdict this module's own three-value severity scale maps onto."""

    severity: str = WARN

    @property
    def verdict(self) -> str:
        return VERDICT_FOR[self.severity]

    def to_json(self) -> dict[str, Any]:
        return {**super().to_json(), "verdict": self.verdict}


def worst(findings: list[Finding]) -> str:
    """The verdict a set of findings implies. Empty means allow."""
    if not findings:
        return "allow"
    return VERDICT_FOR[max((f.severity for f in findings), key=lambda s: _SEVERITY_RANK[s])]


# --- Document quality (corrupt ingest, encoding failure) ---------------------

#: UTF-8 bytes decoded as latin-1. The single most common way a document arrives
#: readable-looking and wrong: "don't" becomes "donâ€™t" and every downstream
#: similarity score degrades quietly rather than failing.
_MOJIBAKE = re.compile(r"â€[™œ\x9d\"]|Ã[©¨¤¶±§]|Â[ ­»«°]|ï»¿")

#: Explicit tokeniser damage. U+FFFD is the decoder giving up; the bracketed forms are
#: model tokenisers reporting a character they have no token for.
_UNKNOWN_TOKEN = re.compile(r"�|\[UNK\]|<unk>|&#xfffd;", re.I)

#: PDF extractors that lose the space glyph produce runs of joined words. Detected by
#: word length rather than by dictionary lookup so it works in any language.
_LONG_RUN = re.compile(r"[A-Za-z]{28,}")

#: A hyphen at end-of-line is a line break, not a word. Left in place it splits the
#: term the retriever is matching on.
_SOFT_HYPHEN_BREAK = re.compile(r"[A-Za-z]-\n[a-z]")


@dataclass
class DocumentQuality:
    """Whether a document is fit to enter the corpus."""

    score: float
    findings: list[Finding] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not any(f.severity == REJECT for f in self.findings)

    def to_json(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "usable": self.usable,
            "findings": [f.to_json() for f in self.findings],
        }


def _printable_ratio(text: str) -> float:
    if not text:
        return 1.0
    bad = sum(
        1 for ch in text if unicodedata.category(ch) in ("Cc", "Co", "Cs") and ch not in "\n\r\t"
    )
    return 1.0 - bad / len(text)


def document_quality(text: str, *, source_key: str = "") -> DocumentQuality:
    """Score an extracted document before it becomes authoritative context.

    The checks are ordered by how silently each one fails. Mojibake and lost spaces
    produce text that *looks* fine in a log line and is unrecoverable by the retriever;
    control-character noise at least announces itself.
    """
    findings: list[Finding] = []
    evidence_base = {"source": source_key} if source_key else {}

    if not text or not text.strip():
        return DocumentQuality(
            0.0,
            [
                Finding(
                    "empty-extraction",
                    "the document extracted to nothing",
                    REJECT,
                    {**evidence_base},
                )
            ],
        )

    length = len(text)

    if hits := _MOJIBAKE.findall(text):
        findings.append(
            Finding(
                "mojibake",
                f"UTF-8 text decoded as latin-1 in {len(hits)} place(s) — re-extract with "
                "the correct encoding rather than ingesting this",
                REJECT if len(hits) > length / 500 else DEGRADED,
                {**evidence_base, "samples": sorted(set(hits))[:5], "count": len(hits)},
            )
        )

    if hits := _UNKNOWN_TOKEN.findall(text):
        ratio = len(hits) / max(1, length)
        findings.append(
            Finding(
                "unknown-characters",
                f"{len(hits)} character(s) the decoder or tokeniser could not represent",
                REJECT if ratio > 0.01 else DEGRADED,
                {**evidence_base, "count": len(hits), "ratio": round(ratio, 5)},
            )
        )

    printable = _printable_ratio(text)
    if printable < 0.99:
        findings.append(
            Finding(
                "control-characters",
                f"{(1 - printable) * 100:.1f}% of the document is control or private-use "
                "characters, which usually means a binary was read as text",
                REJECT if printable < 0.95 else WARN,
                {**evidence_base, "printable_ratio": round(printable, 4)},
            )
        )

    runs = _LONG_RUN.findall(text)
    if runs:
        findings.append(
            Finding(
                "lost-word-boundaries",
                f"{len(runs)} run(s) of 28+ letters with no space — the extractor dropped "
                "the space glyph, and no retriever will match the terms inside them",
                DEGRADED if len(runs) > 3 else WARN,
                {**evidence_base, "samples": runs[:3], "count": len(runs)},
            )
        )

    if breaks := _SOFT_HYPHEN_BREAK.findall(text):
        findings.append(
            Finding(
                "hyphenated-line-breaks",
                f"{len(breaks)} word(s) split by an end-of-line hyphen; de-hyphenate before "
                "chunking or the split halves become the index terms",
                WARN,
                {**evidence_base, "count": len(breaks)},
            )
        )

    letters = sum(1 for ch in text if ch.isalpha())
    if length > 200 and letters / length < 0.5:
        findings.append(
            Finding(
                "low-text-density",
                f"only {letters / length:.0%} of the document is letters — this is usually a "
                "table of contents, a scanned page that failed OCR, or layout debris",
                WARN,
                {**evidence_base, "letter_ratio": round(letters / length, 3)},
            )
        )

    penalty = {WARN: 0.1, DEGRADED: 0.3, REJECT: 0.6}
    score = max(0.0, 1.0 - sum(penalty[f.severity] for f in findings))
    return DocumentQuality(score, findings)


# --- Chunk coherence ------------------------------------------------

#: A chunk that opens mid-clause. Leading lowercase is the signal, with the usual
#: exceptions for identifiers and list continuations.
_OPENS_MID_SENTENCE = re.compile(r"^[a-z]")
_CLOSES_CLEANLY = re.compile(r"[.!?:;\"')\]}]\s*$|^\s*$")
#: An explicit heading marker is required. Matching "short single line" instead made
#: every orphan fragment report twice, and a check that fires on ordinary text is one
#: people learn to ignore.
_HEADING_ONLY = re.compile(r"^\s*(?:#{1,6}\s+|\d+(?:\.\d+)*\.\s+)[^\n]{1,60}\s*$")

#: Below this a chunk carries no retrievable meaning on its own.
MIN_CHUNK_CHARS = 40


def _chunk_text(chunk: Any) -> str:
    if isinstance(chunk, dict):
        return str(chunk.get("text") or chunk.get("content") or "")
    return str(chunk)


def chunk_quality(chunks: list[Any]) -> list[Finding]:
    """Find chunk boundaries that destroyed the meaning they were splitting.

    A sentence cut in half indexes as two fragments, neither of which answers the
    question the whole sentence answered. This is invisible downstream: retrieval
    returns the fragment, groundedness confirms the answer matches the fragment, and
    the claim the other half carried — the exception, the threshold, the negation —
    is simply gone.
    """
    findings: list[Finding] = []
    for index, chunk in enumerate(chunks):
        text = _chunk_text(chunk)
        stripped = text.strip()
        where = {"chunk": index}

        if not stripped:
            findings.append(Finding("empty-chunk", f"chunk {index} is empty", WARN, where))
            continue

        # A heading is not a broken sentence. Checking it as one produced three
        # findings for a chunk with a single, different problem.
        is_heading = bool(_HEADING_ONLY.match(stripped)) and "\n" not in stripped
        if is_heading:
            findings.append(
                Finding(
                    "heading-without-body",
                    f"chunk {index} is a heading with no content under it — it will be "
                    "retrieved and will answer nothing",
                    WARN,
                    {**where, "heading": stripped[:60]},
                )
            )
            continue

        if len(stripped) < MIN_CHUNK_CHARS:
            findings.append(
                Finding(
                    "orphan-chunk",
                    f"chunk {index} is {len(stripped)} characters — too short to answer "
                    "anything on its own, and it will still be retrieved",
                    WARN,
                    {**where, "length": len(stripped)},
                )
            )

        if _OPENS_MID_SENTENCE.match(stripped) and not stripped.startswith(("http", "www")):
            findings.append(
                Finding(
                    "split-sentence-start",
                    f"chunk {index} opens mid-sentence; the subject of the clause is in the "
                    "previous chunk and will not be retrieved with it",
                    DEGRADED,
                    {**where, "opens": stripped[:60]},
                )
            )

        if not _CLOSES_CLEANLY.search(stripped):
            findings.append(
                Finding(
                    "split-sentence-end",
                    f"chunk {index} ends mid-sentence — whatever qualifies the claim is in "
                    "the next chunk",
                    DEGRADED,
                    {**where, "ends": stripped[-60:]},
                )
            )

        if stripped.count("```") % 2:
            findings.append(
                Finding(
                    "split-code-fence",
                    f"chunk {index} has an unbalanced code fence, so the boundary fell "
                    "inside a code block",
                    DEGRADED,
                    where,
                )
            )

    return findings


# --- Assembly: truncation and position ----------------------

#: Characters per token. Deliberately an estimate: the exact number is model-specific
#: and the decision this feeds — "will the citation survive?" — needs a *conservative*
#: bound, not an accurate one. Under-estimating the budget drops evidence silently,
#: so this errs towards assuming text is more expensive than it is.
CHARS_PER_TOKEN = 3.6


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


@dataclass
class Assembly:
    """What actually reaches the model, and what did not."""

    kept: list[int] = field(default_factory=list)
    dropped: list[int] = field(default_factory=list)
    order: list[int] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    tokens: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "kept": self.kept,
            "dropped": self.dropped,
            "order": self.order,
            "tokens": self.tokens,
            "findings": [f.to_json() for f in self.findings],
        }


def assemble_context(
    chunks: list[Any],
    *,
    budget_tokens: int,
    required: list[int] | None = None,
    reorder: bool = True,
    reserve_tokens: int = 0,
) -> Assembly:
    """Fit ranked chunks into a token budget, and say what the fit cost.

    Two distinct failures live here and they are usually confused. *Truncation* drops
    evidence outright — the citation the answer needs never reaches the model, which
    then answers from what remains and cites it. *Position* keeps the evidence but puts
    it where attention is weakest; the well-replicated finding is that material in the
    middle of a long context is used least.

    Truncation is reported, never repaired: which passage to sacrifice is a decision
    with a cost. Position *is* repaired, because moving the strongest passage to the
    front changes what the model attends to and nothing about what it is shown.

    ``required`` names chunks the answer is known to depend on — a citation resolved
    earlier in the turn, for instance. Dropping one of those is a different severity
    from dropping the tail of the ranking.
    """
    required = required or []
    budget = max(0, budget_tokens - reserve_tokens)
    findings: list[Finding] = []

    costs = [estimate_tokens(_chunk_text(c)) for c in chunks]

    kept: list[int] = []
    spent = 0
    # Required chunks are seated first, in rank order, so a budget that can hold them
    # always does — the alternative silently drops the one passage the answer needs
    # because two lower-ranked chunks happened to come first.
    for index in sorted(set(required)):
        if index < len(chunks) and spent + costs[index] <= budget:
            kept.append(index)
            spent += costs[index]
    for index in range(len(chunks)):
        if index in kept:
            continue
        if spent + costs[index] <= budget:
            kept.append(index)
            spent += costs[index]

    kept.sort()
    dropped = [i for i in range(len(chunks)) if i not in kept]

    dropped_required = [i for i in required if i in dropped]
    if dropped_required:
        findings.append(
            Finding(
                "required-evidence-truncated",
                f"chunk(s) {dropped_required} are cited by the answer but do not fit in "
                f"{budget} tokens — the model is being asked to support a claim from "
                "evidence it cannot see",
                REJECT,
                {"dropped": dropped_required, "budget_tokens": budget},
            )
        )
    elif dropped:
        top_dropped = min(dropped)
        findings.append(
            Finding(
                "context-truncated",
                f"{len(dropped)} of {len(chunks)} chunks did not fit; the highest-ranked "
                f"one dropped was #{top_dropped}",
                DEGRADED if top_dropped < 3 else WARN,
                {"dropped": dropped, "budget_tokens": budget, "highest_dropped": top_dropped},
            )
        )

    order = list(kept)
    if reorder and len(kept) >= 5:
        # Strongest at the edges, weakest in the middle. The ranking is preserved as
        # an alternation outward-in rather than being discarded.
        front: list[int] = []
        back: list[int] = []
        for position, index in enumerate(kept):
            (front if position % 2 == 0 else back).append(index)
        order = front + back[::-1]
        findings.append(
            Finding(
                "reordered-for-salience",
                "the highest-ranked passages were moved to the start and end of the "
                "context; material in the middle of a long context is attended to least",
                WARN,
                {"from": kept, "to": order},
            )
        )
    elif len(kept) >= 5 and required:
        middle = set(kept[len(kept) // 4 : -len(kept) // 4 or None])
        buried = [i for i in required if i in middle]
        if buried:
            findings.append(
                Finding(
                    "evidence-buried-mid-context",
                    f"required chunk(s) {buried} sit in the middle of a "
                    f"{len(kept)}-chunk context, where they are least likely to be used",
                    DEGRADED,
                    {"buried": buried},
                )
            )

    return Assembly(kept=kept, dropped=dropped, order=order, findings=findings, tokens=spent)


# --- Retrieval quality drift ---------------------------------------


def retrieval_metrics(ranked: list[str], relevant: set[str] | list[str], *, k: int = 10) -> dict:
    """nDCG@k, recall@k and precision@k for one query against a golden set.

    Binary relevance, which is what a hand-labelled golden set realistically carries.
    nDCG is the one that matters for the failure being guarded against: recall can hold
    steady while the right passage slides from rank 1 to rank 9, and rank 9 is past
    where a truncated context reaches.
    """
    relevant = set(relevant)
    top = ranked[:k]
    if not relevant:
        return {"ndcg": 1.0, "recall": 1.0, "precision": 1.0, "k": k}

    gains = [1.0 if doc in relevant else 0.0 for doc in top]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    hits = sum(gains)
    return {
        "ndcg": round(dcg / ideal, 4) if ideal else 0.0,
        "recall": round(hits / len(relevant), 4),
        "precision": round(hits / len(top), 4) if top else 0.0,
        "k": k,
    }


def evaluate_retrieval(cases: list[tuple[list[str], set[str]]], *, k: int = 10) -> dict:
    """Mean metrics across a golden set."""
    if not cases:
        return {"ndcg": 1.0, "recall": 1.0, "precision": 1.0, "k": k, "queries": 0}
    scored = [retrieval_metrics(ranked, relevant, k=k) for ranked, relevant in cases]
    return {
        "ndcg": round(sum(s["ndcg"] for s in scored) / len(scored), 4),
        "recall": round(sum(s["recall"] for s in scored) / len(scored), 4),
        "precision": round(sum(s["precision"] for s in scored) / len(scored), 4),
        "k": k,
        "queries": len(scored),
    }


def retrieval_drift(current: dict, baseline: dict, *, tolerance: float = 0.05) -> Finding | None:
    """Compare a retrieval run against its recorded baseline.

    An embedding-model swap, a re-index, or a chunking change can move nDCG several
    points without any error being raised anywhere — the pipeline still returns ten
    results and the model still answers. Regression is only visible against a baseline,
    which is why this takes one rather than a threshold.
    """
    regressions = {}
    for metric in ("ndcg", "recall", "precision"):
        before, after = baseline.get(metric), current.get(metric)
        if before is None or after is None or before <= 0:
            continue
        delta = (after - before) / before
        if delta < -tolerance:
            regressions[metric] = {
                "baseline": before,
                "current": after,
                "relative_change": round(delta, 4),
            }
    if not regressions:
        return None
    worst_drop = min(r["relative_change"] for r in regressions.values())
    return Finding(
        "retrieval-regression",
        f"retrieval quality fell {abs(worst_drop):.0%} against the baseline "
        f"({', '.join(sorted(regressions))}) — answers will still be produced and will "
        "still look grounded",
        DEGRADED if worst_drop > -0.2 else REJECT,
        {"metrics": regressions, "tolerance": tolerance},
    )


# --- Memory binding ------------------------------------------------


def memory_binding_breach(
    entries: list[dict[str, Any]],
    *,
    principal: str,
    session_id: str | None = None,
) -> list[Finding]:
    """Catch memory written for one end user surfacing for another.

    Tenant isolation already prevents this across organisations. Within one tenant it
    does not apply and cannot: a shared assistant legitimately holds memory for
    thousands of end users in one org, and the boundary that matters is the *subject*
    the memory is about, not the tenant that owns the store.

    An entry with no subject is the dangerous case rather than the safe one. It was
    written by someone, about someone, and nothing records who — so it is reported
    rather than allowed through on the grounds that no rule matched it.
    """
    findings: list[Finding] = []
    for index, entry in enumerate(entries):
        if entry.get("shared"):
            continue
        subject = entry.get("subject") or entry.get("principal")
        where = {"entry": index, "key": entry.get("key", "")}
        if subject is None:
            findings.append(
                Finding(
                    "unbound-memory",
                    f"memory entry {index} records no subject, so there is nothing to check "
                    "it against before showing it to someone else",
                    DEGRADED,
                    where,
                )
            )
            continue
        if subject != principal:
            findings.append(
                Finding(
                    "cross-subject-memory",
                    f"memory written about '{subject}' surfaced for '{principal}'",
                    REJECT,
                    {**where, "subject": subject, "principal": principal},
                )
            )
            continue
        origin = entry.get("session")
        if session_id and origin and origin != session_id and not entry.get("durable"):
            findings.append(
                Finding(
                    "cross-session-memory",
                    f"memory entry {index} was written in session '{origin}' and is not "
                    "marked durable, but is being read in session '{}'".format(session_id),
                    WARN,
                    {**where, "written_in": origin, "read_in": session_id},
                )
            )
    return findings


# --- Aggregate -------------------------------------------------------------


@dataclass
class ContextAssessment:
    """Everything context integrity can say about one retrieval, in one object."""

    findings: list[Finding] = field(default_factory=list)
    assembly: Assembly | None = None

    @property
    def verdict(self) -> str:
        return worst(self.findings)

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "findings": [f.to_json() for f in self.findings],
            "assembly": self.assembly.to_json() if self.assembly else None,
        }


def assess_context(
    chunks: list[Any],
    *,
    budget_tokens: int | None = None,
    required: list[int] | None = None,
    documents: dict[str, str] | None = None,
    memory: list[dict[str, Any]] | None = None,
    principal: str | None = None,
    session_id: str | None = None,
    retrieval: dict | None = None,
    baseline: dict | None = None,
) -> ContextAssessment:
    """Run every gate that has the inputs it needs, and skip the rest.

    Callers instrument different parts of the pipeline, so every input beyond the
    chunks is optional. A gate with no input is not a passing gate — it simply did not
    run, and the findings list says nothing about it either way.
    """
    findings: list[Finding] = []

    for key, text in (documents or {}).items():
        findings.extend(document_quality(text, source_key=key).findings)

    findings.extend(chunk_quality(chunks))

    assembly = None
    if budget_tokens is not None:
        assembly = assemble_context(chunks, budget_tokens=budget_tokens, required=required)
        findings.extend(assembly.findings)

    if memory is not None and principal:
        findings.extend(memory_binding_breach(memory, principal=principal, session_id=session_id))

    if retrieval and baseline and (drift := retrieval_drift(retrieval, baseline)):
        findings.append(drift)

    return ContextAssessment(findings=findings, assembly=assembly)
