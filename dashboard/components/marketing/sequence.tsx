/*
 * One request, three boundaries — shown, not described.
 *
 * The first version of this replaced three cards with one journey, which was the
 * right structure and the wrong execution: each stage still explained itself in
 * two paragraphs of prose. Roughly 135 words of "retrieval returns three chunks,
 * two come back, the third does not". Nobody reads that while scrolling, and it
 * is describing something we can simply show.
 *
 * So each stage now renders the artefacts themselves. The three retrieved
 * documents are three rows, and the one that is withheld is visibly struck out
 * and marked. The proposed answer is a row that gets replaced by the abstention.
 * The tool call is a row with its real arguments, and `block` lands on it. The
 * prose that remains per stage is one short line: what the operator has to have
 * done for that stage to exist, which a previous accuracy audit established the
 * page cannot leave out.
 *
 * Every value is the one the gateway emits — `not_entitled`, `answerable:
 * false`, `capability.denied`, and the verdict vocabulary — matching the
 * Decision records in decisions.tsx.
 *
 * Motion carries the meaning rather than decorating it: the withheld row strikes
 * through and fades back, the proposed answer is crossed out as the abstention
 * arrives, and the blocked call is marked last. All of it resolves to the
 * resting state, so a screenshot of any frame is still true and the scene reads
 * identically with motion disabled.
 */

type Row = {
  /** The thing itself: a document path, a question, a tool call. */
  text: string;
  /** Mono for identifiers and arguments, prose for sentences people say. */
  mono?: boolean;
  /** How this row ends up once the check has run. */
  state: "kept" | "cut" | "blocked" | "answer" | "quiet";
  /** The short word rendered against it. */
  mark?: string;
};

type Stage = {
  n: string;
  question: string;
  label: string;
  rows: Row[];
  rule: string;
  verdict: string;
  tone: "hold" | "stop";
  /** What the operator must have done. Kept per the accuracy audit. */
  requires: string;
};

const STAGES: Stage[] = [
  {
    n: "01",
    question: "Can it read this?",
    label: "retrieved",
    rows: [
      { text: "billing/refund-policy", mono: true, state: "kept", mark: "returned" },
      { text: "orders/ord_88213", mono: true, state: "kept", mark: "returned" },
      { text: "hr/salaries-2026", mono: true, state: "cut", mark: "withheld" },
    ],
    rule: "not_entitled",
    verdict: "withhold",
    tone: "hold",
    requires: "Call the filter from retrieval.",
  },
  {
    n: "02",
    question: "Can it answer this?",
    label: "asked",
    rows: [
      { text: "Will this refund be approved?", state: "quiet" },
      { text: "Yes. It should go through.", state: "cut", mark: "not supported" },
      { text: "Policy and queue status. No promise.", state: "answer", mark: "sent instead" },
    ],
    rule: "answerable: false",
    verdict: "abstain",
    tone: "hold",
    requires: "Declare a boundary, then enforce it.",
  },
  {
    n: "03",
    question: "Can it do this?",
    label: "requested",
    rows: [
      { text: "payments.transfer", mono: true, state: "blocked", mark: "block" },
      { text: "amount: 5000   to: acct_x", mono: true, state: "quiet" },
      { text: "argument value came from tool_result", state: "quiet" },
    ],
    rule: "capability.denied",
    verdict: "block",
    tone: "stop",
    requires: "Nothing extra. Containment already enforces.",
  },
];

export function BoundarySequence() {
  return (
    <div className="seq">
      {/* The rail sits behind the stages and the pulse travels it, so the reader
          sees one request moving rather than three things that happen to be next
          to each other. Desktop only: over a stacked column a horizontal rail
          would describe a direction the layout does not have. */}
      <div className="seq-rail" aria-hidden>
        <span className="seq-pulse" />
      </div>

      <ol className="seq-stages">
        {STAGES.map((s, i) => (
          <li
            key={s.n}
            className={s.tone === "stop" ? "seq-stage seq-stage-stop" : "seq-stage"}
            style={{ ["--d" as string]: `${0.45 + i * 0.85}s` }}
          >
            <div className="seq-head">
              <span className="seq-n">{s.n}</span>
              <h3 className="mk-h3">{s.question}</h3>
            </div>

            <span className="mk-label">{s.label}</span>

            <ul className="seq-rows">
              {s.rows.map((r, j) => (
                <li
                  key={r.text}
                  className={`seq-row seq-row-${r.state}`}
                  style={{ ["--rd" as string]: `${0.55 + i * 0.85 + j * 0.12}s` }}
                >
                  <span className={r.mono ? "mk-mono" : undefined}>{r.text}</span>
                  {r.mark ? <i>{r.mark}</i> : null}
                </li>
              ))}
            </ul>

            <div className="seq-verdict">
              <span className="seq-chip">{s.verdict}</span>
              <code className="mk-mono">{s.rule}</code>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
