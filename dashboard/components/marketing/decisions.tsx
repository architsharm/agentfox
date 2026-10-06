import Link from "next/link";
import type { CSSProperties } from "react";

/*
 * The decision card, and the four outcomes.
 *
 * The homepage's primary visual used to be a tool call printed as JSON in a
 * monospace block. A reader who has never seen an argument object has to parse it
 * before they can learn anything, and the thing they are meant to learn is not in
 * the object at all: it is the verdict underneath. So the picture is now a record
 * with labelled rows — who, what, which argument, which rule, why — and the verdict
 * as one coloured word. There is no JSON anywhere in this file on purpose.
 *
 * Every visible string is something the product emits, and each one carries the file
 * and line it came from. Three of the four cards are the same three calls
 * `agentfox demo` makes at step 03 (src/agentfox/apps/cli/demo.py lines 276-303): one
 * agent, one tool, and an argument that changes the outcome each time. The fourth is
 * what the audit chain did with the third.
 *
 * Only marketing.css classes and its tokens are used, so light and dark both work
 * and nothing here has a colour of its own.
 */

type Tone = "go" | "hold" | "stop" | "neutral";

type Row = {
  label: string;
  value: string;
  /** Machine values are mono; a reason is ordinary body text. */
  mono?: boolean;
  /** A quieter trailing clause, printed after the value. */
  note?: string;
};

type Decision = {
  key: string;
  /** The outcome word, used as the card heading in the four-up section. */
  outcome: string;
  tone: Tone;
  /** One sentence under the outcome word. */
  gist: string;
  rows: Row[];
  /** The chip. */
  verdict: string;
  /** The escalate card is the one a human acts on, so it shows the two choices. */
  approval?: boolean;
};

/* --- The four decisions -------------------------------------------------- */

/*
 * 1. Allowed. demo.py:278-283 calls payments.transfer as payments-ops with
 *    {"amount": 250, "currency": "USD", "to": "acct_customer_44"} and no provenance
 *    override, so every argument is user-provenance.
 */
const ALLOW: Decision = {
  key: "allow",
  outcome: "Allow",
  tone: "go",
  gist: "The call goes through, and the decision is recorded either way.",
  rows: [
    { label: "Agent", value: "payments-ops", mono: true }, // seed.py:131
    { label: "Tool", value: "payments.transfer", mono: true }, // seed.py:87
    {
      label: "Argument",
      value: "amount: 250",
      mono: true,
      note: "typed by the user", // demo.py:280, no provenance override
    },
    {
      label: "Rule",
      value: "default_effect: allow",
      mono: true,
      note: "nothing fired", // policies_data/tool-containment.yaml:17
    },
    {
      label: "Reason",
      // Illustrative: an allowed call emits no rule and therefore no reason string.
      // The three facts in it are the grant at seed.py:174-178 — payments.transfer,
      // amount lt 1000, currency in USD, max_taint user.
      value:
        "The grant covers this tool, the amount is inside its limit, and the arguments came from the user.",
    },
  ],
  verdict: "allow", // enforcement.py:637
};

/*
 * 2. Escalated. The same call, with the recipient taken from a tool result
 *    (demo.py:285-292). payments.transfer is declared irreversible (seed.py:84), so
 *    the taint rule holds even though nothing recognised the attack.
 */
const ESCALATE: Decision = {
  key: "escalate",
  outcome: "Escalate",
  tone: "hold",
  gist: "The tool is not called. A person decides, and the call waits.",
  rows: [
    { label: "Agent", value: "payments-ops", mono: true }, // seed.py:131
    { label: "Tool", value: "payments.transfer", mono: true }, // seed.py:87
    {
      label: "Argument",
      value: "to: acct_attacker_991",
      mono: true,
      note: "from a tool result", // demo.py:290 provenance={"to": "tool_result"}
    },
    { label: "Rule", value: "taint.irreversible_tool", mono: true }, // tool-containment.yaml:24
    {
      label: "Reason",
      // policies_data/tool-containment.yaml:34-36, verbatim.
      value:
        "Irreversible tool invoked with arguments originating in untrusted content (retrieved document, tool result or sub-agent output). Human approval required.",
    },
  ],
  verdict: "escalate", // enforcement.py:676
  approval: true, // demo.py:293-294 prints "suspended pending human approval"
};

/*
 * 3. Blocked. demo.py:299-304 calls the same tool with amount 25000, which the grant
 *    at seed.py:174-178 caps at 1000.
 */
const BLOCK: Decision = {
  key: "block",
  outcome: "Block",
  tone: "stop",
  gist: "The call is refused, and the reason names the limit it broke.",
  rows: [
    { label: "Agent", value: "payments-ops", mono: true }, // seed.py:131
    { label: "Tool", value: "payments.transfer", mono: true }, // seed.py:87
    {
      label: "Argument",
      value: "amount: 25000",
      mono: true,
      note: "the grant allows under 1000", // seed.py:177
    },
    { label: "Rule", value: "capability.constraint_violated", mono: true }, // tool-containment.yaml:75
    {
      label: "Reason",
      // Generated, not written in the policy file: platform/identity/service.py:355-360 builds
      // this sentence from the grant and the value that failed it, via
      // _describe_violation() at platform/identity/service.py:274-287.
      value:
        "agent:payments-ops holds a grant for 'payments.transfer', so this is not a missing permission. The grant allows amount below 1000, but this call passed 25000.",
    },
  ],
  verdict: "block", // enforcement.py:648
};

/**
 * The same agent, doing its job.
 *
 * A page that only ever shows a refusal reads as a product whose answer is always
 * no, and "it blocks things" is not the hard part — blocking everything is
 * trivial. The pair is the claim: this call is allowed and that one is not, from
 * the same grant, with nothing having read a word of either.
 *
 * Both verdicts were run against the playground sandbox rather than reasoned out:
 * `kb.search` on support-triage returns `allow` with no rule fired, and
 * `payments.transfer` returns `block` on `capability.denied`.
 */
const HERO_ALLOW: Decision = {
  key: "hero-allow",
  outcome: "Allow",
  tone: "go",
  gist: "A call it holds, with an argument nothing objects to.",
  rows: [
    { label: "Agent", value: "support-triage", mono: true },
    { label: "Tool", value: "kb.search", mono: true }, // seed.py, kb.search grant
    { label: "Argument", value: "q: refund policy", mono: true },
    { label: "Rule", value: "none", mono: true },
    { label: "Reason", value: "no policy rule matched" },
  ],
  verdict: "allow",
};

/**
 * The other two boundaries, and what each one actually returned.
 *
 * Every field below was read off this repository's own gateway, running against the
 * seeded demo database, by calling the endpoint and copying the response. They are
 * not descriptions of intent, and the verbs are deliberately different from each
 * other because the three checks do genuinely different things:
 *
 *   ACCESS  /api/entitlement/filter removes the chunk. `visible: 1, withheld: 1,
 *           withheld_sources: ["hr/salaries-2026"]`. Note what this is NOT: the
 *           filter is an endpoint your retrieval code calls, not something that
 *           happens on its own. The in-path half of entitlement runs after the
 *           answer exists and files a finding — tests/capabilities/grounding/test_provenance_integrity.py
 *           :601 asserts it does not block. Saying "we filter your retrieval"
 *           would be claiming an integration nobody has written.
 *   ANSWER  /api/answerability/check returns `answerable: false` and the sentence
 *           the agent should say instead — but `should_abstain: false`, because the
 *           policy is in observe. It reports; it does not yet withhold. Saying
 *           otherwise would be the third time this site overstated a default.
 *   ACT     /api/playground tool-call returns `block` on `capability.denied`.
 *
 * Both of these need something declared first: a principal and a grant for access,
 * a knowledge boundary for answer. With nothing declared there is nothing to check
 * against, and the limits section says so.
 */
const ACCESS: Decision = {
  key: "access",
  outcome: "Withhold",
  tone: "hold",
  gist: "The salary record is not in what comes back, so it never reaches the prompt.",
  rows: [
    { label: "Asking", value: "alex@example.com", mono: true, note: "support-team" },
    { label: "Retrieved", value: "2 chunks", mono: true },
    { label: "Withheld", value: "hr/salaries-2026", mono: true },
    { label: "Rule", value: "not_entitled", mono: true },
    {
      label: "Reason",
      value: "No grant gives this person that source, so it never reaches the prompt.",
    },
  ],
  verdict: "withhold",
};

const ANSWER: Decision = {
  key: "answer",
  outcome: "Abstain",
  tone: "hold",
  gist: "Outside the boundary, with the sentence to say instead.",
  rows: [
    { label: "Agent", value: "support-triage", mono: true },
    { label: "Asked", value: "Will this customer\u2019s refund definitely be approved?" },
    { label: "Question", value: "prediction", mono: true, note: "allowed: fact, procedure" },
    { label: "Boundary", value: "help-center-articles", mono: true },
    {
      label: "Returns",
      value:
        "\u201cI can tell you what the refund policy says and where this request is in the queue, but I can\u2019t promise an outcome. That decision isn\u2019t mine to make.\u201d",
    },
  ],
  verdict: "answerable: false",
};

/** The pair, for the containment section: one allowed, one refused. */
export function DecisionPair() {
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <DecisionCard decision={HERO_ALLOW} heading />
      <DecisionCard heading />
    </div>
  );
}

/*
 * 4. Recorded. Not a verdict: it is what happened to the decision above once it was
 *    made. The digests are the ones in mocks.tsx, which were computed with
 *    audit/chain.py's own compute_digest over the payload enforcement.py writes, so
 *    they chain correctly rather than being filler.
 */
const RECORD: Decision = {
  key: "record",
  outcome: "Prove",
  tone: "neutral",
  gist: "Every decision above lands in a chain that shows if it was edited later.",
  rows: [
    { label: "Entry", value: "seq 2", mono: true }, // mocks.tsx CHAIN
    { label: "Action", value: "decision.block", mono: true }, // enforcement.py:949
    { label: "Prev", value: "7294df2480e2f21b...", mono: true }, // mocks.tsx CHAIN seq 1
    { label: "Hash", value: "f036162ef907acea...", mono: true }, // mocks.tsx CHAIN seq 2
    {
      label: "Verifier",
      // audit/chain.py:306-311 lists what verify() detects; the command is
      // apps/cli/main.py:860, and demo.py:519-548 runs it and then edits a record to
      // show the check failing.
      value:
        "Re-hashing the export reports a changed record, a gap in the sequence, an insertion or a reordering.",
    },
  ],
  verdict: "recorded",
};

const DECISIONS: Decision[] = [ALLOW, ESCALATE, BLOCK, RECORD];

/*
 * The hero's card. This is the playground's first preset verbatim
 * (dashboard/components/marketing/Playground.tsx:134-140): support-triage was granted
 * kb.search, crm.lookup and tickets.* and nothing else (seed.py:161-165), so a
 * transfer is refused without anything having to recognise the attack.
 */
const HERO: Decision = {
  key: "hero",
  outcome: "Block",
  tone: "stop",
  gist: "Refused, with no model asked and no text read.",
  rows: [
    { label: "Agent", value: "support-triage", mono: true }, // seed.py:118
    { label: "Tool", value: "payments.transfer", mono: true }, // seed.py:87
    {
      label: "Argument",
      value: "amount: 5000",
      mono: true,
      note: "to acct_x", // Playground.tsx:138
    },
    { label: "Rule", value: "capability.denied", mono: true }, // tool-containment.yaml:62
    {
      label: "Reason",
      // policies_data/tool-containment.yaml:68, verbatim.
      value: "No capability grants this agent the requested tool and action (default deny).",
    },
  ],
  verdict: "block", // enforcement.py:648
};

/** The three boundaries, in the order a request meets them. */
export const BOUNDARIES: { id: string; question: string; lede: string; decision: Decision }[] = [
  {
    id: "access",
    question: "Can it read this?",
    lede: "Your retrieval code asks who is asking. What they may not see never comes back.",
    decision: ACCESS,
  },
  {
    id: "answer",
    question: "Can it answer this?",
    lede: "A question outside the declared knowledge boundary gets a refusal written for it.",
    decision: ANSWER,
  },
  {
    id: "act",
    question: "Can it do this?",
    lede: "The call is checked against the agent\u2019s grants, not against the text.",
    decision: HERO,
  },
];


/* --- Tone ---------------------------------------------------------------- */

const EDGE: Record<Tone, string> = {
  go: "var(--mk-good)",
  hold: "var(--mk-hold)",
  stop: "var(--mk-stop)",
  neutral: "var(--mk-border-strong)",
};

/* A tinted panel is how a verdict reads at a glance. The fourth card has no verdict
   to tint, and a panel filled with a surface token would disappear into the card it
   sits in — in one theme or the other, since the two swap darkness. So that one is
   left unfilled and takes a hairline instead. */
const WASH: Record<Tone, string> = {
  go: "var(--mk-good-soft)",
  hold: "var(--mk-hold-soft)",
  stop: "var(--mk-stop-soft)",
  neutral: "transparent",
};

/* --mk-border-strong is an edge, not a text colour: it is the card heading here only
   for the three tones where it is also the semantic one. */
const HEAD: Record<Tone, string> = {
  go: "var(--mk-good)",
  hold: "var(--mk-hold)",
  stop: "var(--mk-stop)",
  neutral: "var(--mk-text)",
};

const CHIP: Record<Tone, string> = {
  go: "mk-chip mk-chip-go",
  hold: "mk-chip mk-chip-hold",
  stop: "mk-chip mk-chip-stop",
  neutral: "mk-chip",
};

/** The two choices on an escalation, drawn as capsules rather than live controls. */
function choice(tone: "go" | "stop"): CSSProperties {
  return {
    borderRadius: 980,
    padding: "6px 16px",
    fontSize: "var(--t-small)",
    fontWeight: 500,
    background: WASH[tone],
    color: EDGE[tone],
  };
}

/* --- The card ------------------------------------------------------------ */

/**
 * One decision as a record: labelled rows, then the verdict.
 *
 * `wide` puts the label and the value on one line, which is what the hero's column
 * has room for. Stacked is the default, because four of these across a desktop are
 * about 210px each and a rule id does not fit beside its label at that width.
 */
export function DecisionCard({
  decision = HERO,
  wide = false,
  heading = false,
  fill = false,
}: {
  decision?: Decision;
  wide?: boolean;
  heading?: boolean;
  /** Stretch to the row's height and pin the verdict to the bottom edge. Three of
   *  these side by side have records of different lengths, and a verdict chip that
   *  floats at a different height in each column reads as three misaligned cards
   *  rather than three answers to the same question. */
  fill?: boolean;
}) {
  const { tone } = decision;
  return (
    <div
      className={wide ? "mk-card mk-card-raised" : "mk-card"}
      style={{
        padding: wide ? 26 : 20,
        display: "grid",
        gap: 16,
        alignContent: fill ? "space-between" : "start",
        height: fill ? "100%" : undefined,
        boxShadow: wide ? "var(--mk-shadow-float)" : undefined,
        minWidth: 0 }}
    >
      {heading ? (
        <div>
          <h3 className="mk-h3" style={{ color: HEAD[tone] }}>
            {decision.outcome}
          </h3>
          <p className="mk-fine" style={{ margin: "6px 0 0" }}>
            {decision.gist}
          </p>
        </div>
      ) : null}

      <div style={{ display: "grid", gap: wide ? 10 : 9 }}>
        {decision.rows.map((row, i) => (
          <div
            key={row.label}
            className="dc-row"
            style={
              wide
                ? {
                    display: "grid",
                    gridTemplateColumns: "minmax(78px, auto) 1fr",
                    gap: "2px 14px",
                    alignItems: "baseline",
                    animationDelay: `${0.08 + i * 0.11}s`,
                  }
                : { display: "grid", gap: 3, animationDelay: `${0.08 + i * 0.11}s` }
            }
          >
            <span className="mk-label">{row.label}</span>
            <span
              className={row.mono ? "mk-mono" : undefined}
              style={{
                color: row.mono ? "var(--mk-text)" : "var(--mk-muted)",
                fontSize: row.mono ? undefined : "var(--t-small)",
                lineHeight: row.mono ? 1.45 : 1.5,
                overflowWrap: "anywhere",
                minWidth: 0 }}
            >
              {row.value}
              {row.note ? (
                <span className="mk-mono" style={{ color: "var(--mk-muted)" }}>
                  {" "}
                  {row.note}
                </span>
              ) : null}
            </span>
          </div>
        ))}
      </div>

      <div
        className="dc-verdict"
        style={{
          animationDelay: `${0.08 + decision.rows.length * 0.11 + 0.1}s`,
          background: WASH[tone],
          // The hairline goes on first so the coloured left edge below overrides it.
          border: tone === "neutral" ? "1px solid var(--mk-border)" : undefined,
          borderLeftWidth: "2.5px",
          borderLeftStyle: "solid",
          borderLeftColor: EDGE[tone],
          borderRadius: "0 var(--mk-r-sm) var(--mk-r-sm) 0",
          padding: "10px 12px",
          display: "grid",
          gap: 9 }}
      >
        <div className="mk-row" style={{ gap: 8 }}>
          <span className={CHIP[tone]}>{decision.verdict}</span>
        </div>
        {decision.approval ? (
          <>
            <span className="mk-label">Waiting for a person</span>
            <div className="mk-row" style={{ gap: 8 }}>
              <span style={choice("go")}>Approve</span>
              <span style={choice("stop")}>Deny</span>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

/* --- The section --------------------------------------------------------- */

/**
 * The product model on one screen: what can happen to a tool call, and what is kept
 * afterwards. Four cards, each a coloured word and one record.
 *
 * `auto-fit` at 210px gives four across inside the 1040px column, two on a tablet
 * and one on a phone, with no breakpoint of its own.
 */
export function Decisions() {
  return (
    <section id="decisions" className="mk-section">
      <div className="mk-wrap">
        <span className="mk-eyebrow">Tool calls</span>
        <h2 className="mk-h2" style={{ marginTop: 12 }}>
          One call, four possible outcomes</h2>
        <p className="mk-lede" style={{ margin: "16px 0 0" }}>
          The same agent and the same tool each time. The argument is what changes the
          answer.
        </p>

        <div
          className="mk-grid mk-grid-quad"
          style={{
            marginTop: 40,
            alignItems: "stretch" }}
        >
          {DECISIONS.map((d) => (
            <DecisionCard key={d.key} decision={d} heading />
          ))}
        </div>

        <p className="mk-fine" style={{ marginTop: 22 }}>
          The first three are what the offline demo does on a first install. Run the same
          ones in the <Link href="/playground">playground</Link>, or see the commands in the{" "}
          <Link href="/docs">docs</Link>.
        </p>
      </div>
    </section>
  );
}
