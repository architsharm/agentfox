import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import { Header } from "@/components/kit";
import { GlossaryFilter } from "@/components/product/GlossaryFilter";
import { ProductMap, PRODUCT_MAP_ROWS } from "@/components/product/ProductMap";

export const dynamic = "force-dynamic";

/**
 * Not public, despite being pure reference text with no data in it. It is linked
 * only from signed-in pages (Start here, Agents, Policies, Compliance, Findings),
 * it renders inside the app sidebar rather than the marketing chrome, and it is
 * not in middleware.ts's PUBLIC_PATHS, so a signed-out request for it is redirected
 * to /login. Marking it indexable would therefore put the sign-in form in the index
 * under this URL. See the note in the report accompanying this change: making it
 * genuinely public is a reasonable thing to want, but it needs the public header
 * treatment /how-it-works has, not just a line in a list.
 */
export const metadata: Metadata = appPageMetadata(
  "Glossary",
  "Every term and code this interface shows, decoded once: the concepts, then the pillar numbering and NOM control prefixes used across policies and compliance.",
);

const PILLARS: [string, string][] = [
  ["Pillar 1", "Discovery & Agent Registry — knowing every agent exists"],
  ["Pillar 2", "Identity, Access & Authorization — who/what an agent is, what it can do"],
  ["Pillar 3", "Runtime Guardrails — the detectors that fire on every request"],
  ["Pillar 4", "Evaluation & Reliability — did the agent actually work"],
  ["Pillar 5", "Audit, Observability & Traceability — the tamper-evident record"],
  ["Pillar 6", "Policy & Compliance Management — rules as versioned, reviewable code"],
  ["Pillar 7", "Answerability & Abstention — does it know what it doesn't know"],
  ["Pillar 8", "Provenance & Source Authority — where a claim actually came from"],
  ["Pillar 9", "Action Assurance — is a tool call safe to actually execute"],
  ["Pillar 10", "Entitlement & Disclosure Control — did this user have the right to see that"],
  ["Pillar 11", "Escalation Governance — did a human get pulled in when one should have"],
  ["Pillar 12", "Policy Composition & Lifecycle — simulate before you promote"],
  ["Pillar 13", "Failure Attribution — whose fault, on a multi-agent handoff"],
  ["Pillar 14", "Context & Retrieval Integrity — was the source material any good"],
  ["Pillar 15", "Cost, Reliability & Degradation — what happens under load or budget pressure"],
];

const NOM_PREFIXES: [string, string][] = [
  ["NOM-DSC", "Discovery & Inventory (Pillar 1) — e.g. every agent is registered and owned"],
  ["NOM-IAM", "Identity & Access (Pillar 2) — non-human identity, credential rotation, approvals"],
  ["NOM-RTG", "Runtime Guardrails (Pillar 3) — injection/PII/secrets/safety detection at request time"],
  ["NOM-EVL", "Evaluation & Reliability (Pillar 4) — pre-release testing, drift, red-team posture"],
  ["NOM-AUD", "Audit & Traceability (Pillar 5) — the execution-path record and its integrity chain"],
  ["NOM-GOV", "Governance & Compliance (Pillar 6) — policy-as-code, framework mappings, risk register"],
];

/**
 * What the filter reports as the denominator. Counted here rather than in the
 * component because the component filters the DOM and would otherwise be
 * counting whatever happened to render — including, during the first paint,
 * nothing. Concepts (23) + pillars (15) + NOM prefixes (6) + detector
 * libraries (6) + the two prose-only schemes.
 */
const TERM_COUNT = 23 + PILLARS.length + NOM_PREFIXES.length + 6 + 2 + PRODUCT_MAP_ROWS;

export default function Glossary() {
  return (
    <>
      {/* Was an <h1> and a six-line paragraph explaining what a glossary is,
          on a page nobody arrives at to read about glossaries. PageHeader for
          consistency with every other page, and the sub says the one thing that
          is not obvious from the title: where to go for the other question. */}
      <Header title="Glossary" />

      <GlossaryFilter total={TERM_COUNT} />

      <section data-gl-section>
      <h2>Concepts</h2>
      <p className="small muted" style={{ maxWidth: "var(--measure)" }}>
        The words the product itself uses that don&rsquo;t explain themselves on first
        read. The coding schemes are below.
      </p>
      <div className="panel scroll-x">
        <table>
          <thead><tr><th>term</th><th>means</th></tr></thead>
          <tbody>
            <tr id="detectors-guardrails" data-term="detectors / guardrails">
              <td className="mono small">Detectors / Guardrails</td>
              <td className="small">
                Runtime checks that run on every request as it happens — prompt injection,
                PII, secrets, unsafe content. See <a href="/app/policies?tab=advanced&sec=tuning">Guardrails</a>.
              </td>
            </tr>
            <tr id="policies" data-term="policies">
              <td className="mono small">Policies</td>
              <td className="small">
                The rules that decide what a detector's result actually does — allow,
                block, or escalate. A policy is in <span className="mono">observe</span>{" "}
                mode (records only) or <span className="mono">enforce</span> mode
                (actually blocks) — see <a href="/app/policies">Policies</a>.
              </td>
            </tr>
            <tr id="controls" data-term="controls">
              <td className="mono small">Controls</td>
              <td className="small">
                The compliance framing of the same underlying capabilities — "is this
                actually happening," each one backed by real telemetry rather than a
                self-attested checkbox — see <a href="/app/compliance">Compliance</a>.
              </td>
            </tr>
            <tr id="scorers" data-term="scorers">
              <td className="mono small">Scorers</td>
              <td className="small">
                Offline judges that grade an agent's past output after the fact —
                accuracy, groundedness, safety — against a batch of test cases or logged
                results. Different from a detector, which runs on live traffic as it
                happens — see <a href="/app/evals">Evaluation</a>.
              </td>
            </tr>
            <tr id="decisions-verdicts" data-term="decisions / verdicts">
              <td className="mono small">Decisions / Verdicts</td>
              <td className="small">
                A <strong>Decision</strong> is the logged record of one policy evaluation —
                which rules fired, what the outbound effect was. Its{" "}
                <strong>Verdict</strong> is just the outcome value on that record (allow,
                block, escalate, redact...) — see it as a colored tag on{" "}
                <a href="/app/traces">Traces</a>. A Decision is not itself a Finding: a single
                blocked call is expected, routine enforcement working correctly.
              </td>
            </tr>
            <tr id="findings" data-term="findings">
              <td className="mono small">Findings</td>
              <td className="small">
                How a Detector run and a Decision turn into something that needs a
                person: a detector tests one call → its outcome is logged as a Decision →
                a problem that's persistent, high-severity, or part of a pattern (not just
                one routine block) is raised as a <strong>Finding</strong> — a concrete,
                actionable problem tied to evidence, ranked by severity — see{" "}
                <a href="/app/findings">Findings</a>.
              </td>
            </tr>
            <tr id="observe-enforce" data-term="observe / enforce">
              <td className="mono small">Observe / enforce</td>
              <td className="small">
                The two modes a policy can be in. In{" "}
                <span className="mono">observe</span> it records what it would have
                done and blocks nothing; in <span className="mono">enforce</span> the
                blocking is real. Everything content-based starts in observe on
                purpose, so check the mode column on{" "}
                <a href="/app/policies">Policies</a> before assuming a rule is stopping
                anything.
              </td>
            </tr>
            <tr id="effective-verdict" data-term="effective verdict">
              <td className="mono small">Effective verdict</td>
              <td className="small">
                What the policy <em>would</em> have done, recorded whatever mode it is
                in. On a trace in observe mode the verdict reads{" "}
                <span className="mono">allow</span> because nothing was stopped, while
                the effective verdict reads <span className="mono">block</span> because
                that is what enforcing would have produced. It is how you tell what
                enforcing would cost you before you turn it on.
              </td>
            </tr>
            <tr id="canary" data-term="canary">
              <td className="mono small">Canary</td>
              <td className="small">
                A policy change put live for a slice of traffic rather than all of it,
                with a health gate watching. The gate rolls the change back if the
                candidate blocks much more than the current policy, and also if it
                blocks much less, because a change that suddenly stops catching things
                is as suspect as one that over-blocks.
              </td>
            </tr>
            <tr id="proposal" data-term="proposal">
              <td className="mono small">Proposal</td>
              <td className="small">
                One change to governance configuration, filed with its diff, the
                evidence behind it and every decision taken on it, instead of being
                applied. A change that loosens a control is never applied
                automatically, and a loosening at org level needs two different
                approvers. There is no screen for proposals; they are read and decided
                with <span className="mono">agentfox policy proposals</span> or{" "}
                <span className="mono">/api/proposals</span>, described on the{" "}
                <a href="/app/policies">Rules page</a>.
              </td>
            </tr>
            <tr id="capability-grant" data-term="capability grant">
              <td className="mono small">Capability grant</td>
              <td className="small">
                A declaration that one agent may call one tool, with limits on the
                argument values, a ceiling on how untrusted the arguments may be,
                optionally a required human approval, and an expiry. Default deny: an
                agent with no grant for a tool cannot call it. Made with{" "}
                <span className="mono">agentfox permit grant</span>, explained on
                the <a href="/app/agents">Agents page</a>.
              </td>
            </tr>
            <tr id="obligation" data-term="obligation">
              <td className="mono small">Obligation</td>
              <td className="small">
                A dated duty a regulation puts on you, such as a filing or a review
                that has to happen by a particular date, tracked against the agents it
                applies to. Listed on the{" "}
                <a href="/app/compliance?tab=obligations">Obligations tab</a>. A date in
                the calendar is a reminder, not proof the duty was met.
              </td>
            </tr>
            <tr id="fingerprint-occurrences" data-term="fingerprint / occurrences">
              <td className="mono small">Fingerprint / occurrences</td>
              <td className="small">
                A finding&rsquo;s <strong>fingerprint</strong> is computed from its
                type, its subject and the parts that identify the problem, so the same
                problem happening again is the same row.{" "}
                <strong>Occurrences</strong> counts how many times it has happened.
                A recurrence refreshes the evidence and can raise the severity, never
                lower it, and a problem that comes back after being resolved reopens
                the same finding rather than starting a new one. It is why one row on{" "}
                <a href="/app/findings">Findings</a> can stand for something that happened
                two hundred times. The count itself is on{" "}
                <span className="mono">GET /api/findings</span> and is not shown in
                these pages yet.
              </td>
            </tr>
            <tr id="access-control" data-term="access control">
              <td className="mono small">Access Control</td>
              <td className="small">
                Whether an agent's answer contains only what the specific person asking
                is allowed to see — not just whether the answer is factually true. See{" "}
                <a href="/app/entitlement">Access Control</a>.
              </td>
            </tr>
            <tr id="escalation" data-term="escalation">
              <td className="mono small">Escalation</td>
              <td className="small">
                A whole conversation getting handed off to a human — distinct from{" "}
                <strong>Approvals</strong>, which gates one specific tool call, not the
                conversation around it. See <a href="/app/approvals?tab=escalation">Escalation</a> and{" "}
                <a href="/app/approvals">Approvals</a>.
              </td>
            </tr>
            <tr id="tool-containment" data-term="tool containment">
              <td className="mono small">Tool containment</td>
              <td className="small">
                Deciding whether a tool call is allowed to run, from the call itself
                rather than from the wording of the prompt: which tool, what
                arguments, where those arguments came from, and the tool's declared
                impact tier. It is the reason an injection can succeed at convincing
                the model and still not get the action executed. It holds only as far
                as the declarations go — a tool declared{" "}
                <span className="mono">read</span> that actually deletes records is
                not contained by it. It has two halves: the{" "}
                <strong>capability grant</strong> that decides whether this agent may
                call this tool at all, and the <strong>impact tier</strong> declared on
                the tool that says how much damage it could do. See{" "}
                <a href="/app/policies">Policies</a> and <a href="/app/agents">Agents</a>.
              </td>
            </tr>
            <tr id="impact-tier" data-term="impact tier">
              <td className="mono small">Impact tier</td>
              <td className="small">
                How much damage one tool can do, declared per tool and the axis every
                containment rule reasons over:{" "}
                <span className="mono">read</span> (returns information),{" "}
                <span className="mono">write</span> (changes something recoverable),{" "}
                <span className="mono">high_impact</span> (significant but
                reversible), <span className="mono">irreversible</span> (cannot be
                undone — money moved, a message sent, a record deleted). Set with{" "}
                <span className="mono">agentfox declare tool --impact</span>.
              </td>
            </tr>
            <tr id="argument-provenance-taint" data-term="argument provenance / taint">
              <td className="mono small">Argument provenance / taint</td>
              <td className="small">
                Where the values in a tool call came from — typed by the user, pulled
                out of a retrieved document, or copied from another tool's output.
                Containment rules use it to tell an action the user asked for from one
                an attacker planted in content the agent read.
              </td>
            </tr>
            <tr id="provenance" data-term="provenance">
              <td className="mono small">Provenance</td>
              <td className="small">
                Being able to point to exactly which source document backed a specific
                claim in an agent's answer, and whether that source was authoritative in
                the first place.
              </td>
            </tr>
            <tr id="knowledge-boundary" data-term="knowledge boundary">
              <td className="mono small">Knowledge boundary</td>
              <td className="small">
                An explicit declaration of what an agent is and isn't supposed to answer,
                so "I don't know" becomes a detectable, correct outcome instead of the
                agent inventing an answer to something it has no data for.
              </td>
            </tr>
            <tr id="groundedness" data-term="groundedness">
              <td className="mono small">Groundedness</td>
              <td className="small">
                Whether an agent's answer is actually supported by the context it was
                given, rather than invented — a scorer, not a runtime detector.
              </td>
            </tr>
            <tr id="blast-radius" data-term="blast radius">
              <td className="mono small">Blast radius</td>
              <td className="small">
                How many other agents, tools or models are reachable from one agent
                within a couple of hops of observed traffic — a rough proxy for how far
                a compromise or a bad decision here could actually spread.
              </td>
            </tr>
            <tr id="policy-hierarchy" data-term="policy hierarchy">
              <td className="mono small">Policy hierarchy</td>
              <td className="small">
                Org, team, agent and user-level policies compose together — extending,
                restricting, or (where explicitly allowed) overriding one another —
                rather than needing one giant rule set. The narrowest level that applies
                wins ties.
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      </section>

      <ProductMap />

      <section data-gl-section>
      <h2>P#-# — PRD pillar references</h2>
      <p className="small muted" style={{ maxWidth: "var(--measure)" }}>
        This product's build is organized into 15 numbered "pillars," each a distinct
        governance capability. A reference like <span className="mono">P5-1</span> means{" "}
        <em>the first requirement under Pillar 5</em>. You'll see these in control
        cross-references and in status docs, not in the UI copy itself.
      </p>
      <div className="panel scroll-x">
        <table>
          <thead><tr><th>pillar</th><th>covers</th></tr></thead>
          <tbody>
            {PILLARS.map(([n, d]) => (
              <tr key={n} data-term={`${n.toLowerCase()} ${d.toLowerCase()}`}>
                <td className="mono small">{n}</td>
                <td className="small">{d}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      </section>

      <section data-gl-section>
      <h2>NOM-XXX-## — this product's own control codes</h2>
      <p className="small muted" style={{ maxWidth: "var(--measure)" }}>
        Every control on the <a href="/app/compliance">Compliance</a> page and every rule in a{" "}
        <a href="/app/policies">policy</a> carries one of these codes — the prefix says which
        pillar it belongs to, the number is just an index within it.
      </p>
      <div className="panel scroll-x">
        <table>
          <thead><tr><th>prefix</th><th>area</th></tr></thead>
          <tbody>
            {NOM_PREFIXES.map(([n, d]) => (
              <tr key={n} data-term={`${n.toLowerCase()} ${d.toLowerCase()}`}>
                <td className="mono small">{n}-##</td>
                <td className="small">{d}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      </section>

      <section data-gl-section data-term="owasp llm top 10 prompt injection sensitive information disclosure llm01 llm02">
      <h2>OWASP LLM Top 10</h2>
      <p className="small muted" style={{ maxWidth: "var(--measure)" }}>
        The industry-standard risk list for LLM applications (OWASP Top 10 for LLM
        Applications). A finding or rule tagged <span className="mono">LLM01</span>,{" "}
        <span className="mono">LLM02</span> etc. is mapped to one of these ten categories —
        the two seen most often here are <strong>LLM01 Prompt Injection</strong> and{" "}
        <strong>LLM02 Sensitive Information Disclosure</strong>. Full list at{" "}
        <a href="https://genai.owasp.org/llm-top-10/" target="_blank" rel="noreferrer">
          genai.owasp.org/llm-top-10
        </a>.
      </p>

      </section>

      <section data-gl-section data-term="mitre atlas att&ck adversarial tactics techniques">
      <h2>MITRE ATLAS</h2>
      <p className="small muted" style={{ maxWidth: "var(--measure)" }}>
        MITRE's adversarial-tactics knowledge base for AI systems (the AI-specific sibling
        of MITRE ATT&amp;CK) — a taxonomy of real attack techniques, e.g. prompt injection or
        data exfiltration, used to tag red-team findings against a shared, external reference
        rather than an invented one. See{" "}
        <a href="https://atlas.mitre.org/" target="_blank" rel="noreferrer">atlas.mitre.org</a>.
      </p>

      </section>

      <section data-gl-section>
      <h2>Detector library names</h2>
      <p className="small muted" style={{ maxWidth: "var(--measure)" }}>
        The <a href="/app/policies?tab=advanced&sec=tuning">Guardrails</a> and <a href="/app/policies">Policies</a> pages
        name the underlying open-source engine behind each detector, since which library
        caught something is itself useful debugging context:
      </p>
      <div className="panel scroll-x">
        <table>
          <thead><tr><th>library</th><th>used for</th></tr></thead>
          <tbody>
            <tr id="presidio" data-term="presidio"><td className="mono small">Presidio</td><td className="small">Microsoft's PII detection and anonymization engine</td></tr>
            <tr id="spacy" data-term="spacy"><td className="mono small">spaCy</td><td className="small">NLP toolkit Presidio uses for entity recognition</td></tr>
            <tr id="colang-nemo-guardrails" data-term="colang / nemo guardrails"><td className="mono small">Colang / NeMo Guardrails</td><td className="small">NVIDIA's conversational-rail definition language and runtime</td></tr>
            <tr id="granite-guardian" data-term="granite guardian"><td className="mono small">Granite Guardian</td><td className="small">IBM's safety-classification model</td></tr>
            <tr id="garak" data-term="garak"><td className="mono small">garak</td><td className="small">Open-source LLM vulnerability scanner (probes used in red-team campaigns)</td></tr>
            <tr id="pyrit" data-term="pyrit"><td className="mono small">pyrit</td><td className="small">Microsoft's Python Risk Identification Tool, another red-team probe source</td></tr>
          </tbody>
        </table>
      </div>
      </section>
    </>
  );
}
