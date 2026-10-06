import Link from "next/link";
import { InfoTip } from "@/components/ui";

const AREAS: {
  name: string;
  href: string;
  answers: string;
  doThere: string;
}[] = [
  {
    name: "Overview",
    href: "/app",
    answers: "What needs a person right now, most severe first.",
    doThere:
      "Start a working session here. Every row links through to the finding, approval or conversation it is about.",
  },
  {
    name: "Agents",
    href: "/app/agents",
    answers:
      "Which agents exist, who is accountable for each one, and which models and tools each one actually calls.",
    doThere:
      "Register an agent, or claim one that turned up in traffic without ever being registered. Open an agent to see its traces, its lineage and its risk tier.",
  },
  {
    name: "Verified sources",
    href: "/app/sources",
    answers:
      "Which of the places your agents read from are systems of record, and which are somebody's notes.",
    doThere:
      "Tier a source, then validate it: validation fetches it and checks the content is still what it was, which a registered key on its own never proves.",
  },
  {
    name: "Findings",
    href: "/app/findings",
    answers:
      "Which problems are worth a person's attention, ranked by severity, with the evidence attached.",
    doThere:
      "Read a finding, then resolve it with a note or suppress it with a reason. One routine blocked call is not a finding; a pattern or a severe one is.",
  },
  {
    name: "Traces",
    href: "/app/traces",
    answers:
      "What one agent actually did on one request: the prompt, what it retrieved, which tools it called, and every guardrail decision along the way.",
    doThere:
      "Open a trace when you want to know why a specific request was allowed, redacted, escalated or blocked. Filter by agent or by outcome to find it.",
  },
  {
    name: "Evaluation",
    href: "/app/evals",
    answers:
      "Whether the agent gets the answer right, not just whether it avoids saying something unsafe.",
    doThere:
      "Build a suite of known questions and run it, or sample real traffic and score that instead. This is also where you run red-team probes against an agent.",
  },
  {
    name: "Policies",
    href: "/app/policies",
    answers:
      "The rules that decide what a detector's result does: allow, redact, escalate or block.",
    doThere:
      "Read what is in force for an agent, and check which policies are still in observe mode rather than enforcing. Changes are simulated against recorded traffic before they are promoted.",
  },
  {
    name: "Guardrail tuning",
    href: "/app/policies?tab=guardrails",
    answers:
      "Whether those checks are catching real problems, how much time they cost, and which ones someone has quietly silenced.",
    doThere:
      "Label a detection as a false positive, and turn that label into a scoped suppression that expires on its own rather than a detector somebody switches off.",
  },
  {
    name: "Access Control",
    href: "/app/entitlement",
    answers:
      "Whether an agent's answer contained only what the specific person asking was cleared to see.",
    doThere:
      "Add the people and teams an agent answers for, grant them resources, then read the report on how much the agent could reach that its callers could not.",
  },
  {
    name: "Approvals",
    href: "/app/approvals",
    answers:
      "Which single tool calls a policy handed to a human instead of deciding on its own.",
    doThere:
      "Approve a call so it runs, or deny it so it does not. An unanswered request denies itself when it expires rather than sitting open.",
  },
  {
    name: "Escalation",
    href: "/app/approvals?tab=escalation",
    answers:
      "Which whole conversations should have reached a person, including the ones that never did.",
    doThere:
      "Work the hand-off queue, and read the conversations that qualified for a human and kept going anyway. Set the conditions that qualify one.",
  },
  {
    name: "Compliance",
    href: "/app/compliance",
    answers:
      "Which controls are actually holding, computed from telemetry rather than attested on a form, mapped across seven frameworks.",
    doThere:
      "Build an evidence package for an auditor, verify the audit chain, and read the risk register and the regulatory dates. Framework mappings ship as drafts until a named reviewer signs one off.",
  },
  {
    name: "Glossary",
    href: "/app/glossary",
    answers:
      "What every word and code in this interface means, including the ones this product invented.",
    doThere: "Look up anything above that did not explain itself.",
  },
];

const OFF_SCREEN: { name: string; where: string; body: React.ReactNode }[] = [
  {
    name: "Change proposals",
    where: "agentfox proposals · /api/proposals",
    body: (
      <>
        Governance changes are filed as proposals, not applied.{" "}
        <InfoTip text="Every change this product wants to make to its own governance configuration is filed as a proposal instead of applied. A proposal carries the diff, the evidence behind it and every decision taken on it. A change that loosens a control is never applied automatically, and a loosening at org level needs two different approvers." />{" "}
        <Link href="/app/policies">Policies</Link>.
      </>
    ),
  },
  {
    name: "Capability grants",
    where: "agentfox capability grant · /api/identities/{id}/capabilities",
    body: (
      <>
        What an agent is allowed to do, decided from the action, not the prompt.{" "}
        <InfoTip text="Least privilege here is default deny: an agent with no grant for a tool cannot call it." />{" "}
        <Link href="/app/agents">Agents</Link>.
      </>
    ),
  },
  {
    name: "Evaluation gate for CI",
    where: "agentfox eval gate · POST /api/eval/gate",
    body: (
      <>
        Runs a suite against a baseline run; exits non-zero on a regression.{" "}
        <InfoTip text="A pull request can fail on it. It can write JUnit and SARIF files for whatever reads them." />{" "}
        <Link href="/app/evals">Evaluation</Link>.
      </>
    ),
  },
];

/**
 * The product's areas and its off-screen capabilities.
 *
 * These were a "What's in here" tab on Start here, which is the wrong page for
 * them: Start here is the four things you DO to get set up, and this is
 * reference material you consult once and come back to. It lives on the
 * Glossary now, beside the other reference material, and — because the rows
 * carry data-term like every other row here — the filter at the top of this
 * page finds an area by name too.
 */
/** Rows this component contributes to the Glossary filter's denominator. */
export const PRODUCT_MAP_ROWS = AREAS.length + OFF_SCREEN.length;

export function ProductMap() {
  return (
    <>
      <section data-gl-section id="areas">
      <h2>Areas of the product</h2>
      <p className="small muted" style={{ maxWidth: "var(--measure)" }}>
        What each page in the sidebar answers, and what you do there. The groups run
        Discover, Monitor, Test, Govern — roughly the order you meet them in.
      </p>
      <div className="panel scroll-x">
        <table>
          <thead>
            <tr>
              <th>area</th>
              <th>what it answers</th>
              <th>what you do there</th>
            </tr>
          </thead>
          <tbody>
            {AREAS.map((a) => (
              <tr key={a.href} data-term={`${a.name.toLowerCase()} ${a.answers.toLowerCase()}`}>
                <td className="small" style={{ whiteSpace: "nowrap" }}>
                  <Link href={a.href}>{a.name}</Link>
                </td>
                <td className="small wrap" style={{ maxWidth: 400 }}>
                  {a.answers}
                </td>
                <td className="small muted wrap" style={{ maxWidth: 420 }}>
                  {a.doThere}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      </section>

      <section data-gl-section id="off-screen">
      <h2>Things that work but have no screen</h2>
      <p className="small muted" style={{ maxWidth: "var(--measure)" }}>
        Running today, with no page of their own — reached from the command line or
        the HTTP API.
      </p>
      <div className="panel scroll-x">
        <table>
          <thead>
            <tr>
              <th>capability</th>
              <th>used from</th>
              <th>what it is</th>
            </tr>
          </thead>
          <tbody>
            {OFF_SCREEN.map((c) => (
              <tr key={c.name} data-term={`${c.name.toLowerCase()} ${c.where.toLowerCase()}`}>
                <td className="small" style={{ whiteSpace: "nowrap" }}>
                  {c.name}
                </td>
                <td
                  className="mono small muted wrap"
                  style={{ maxWidth: 220, overflowWrap: "anywhere" }}
                >
                  {c.where}
                </td>
                <td className="small wrap" style={{ maxWidth: 480 }}>
                  {c.body}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

    </section>
    </>
  );
}