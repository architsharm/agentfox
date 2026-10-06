import Link from "next/link";

import type { TocItem } from "@/components/blog/article";
import { Diagram, Figure, InlineCTA, Stat, StatRow, Takeaways, type FaqItem } from "@/components/blog/blocks";
import { Code } from "@/components/docs/blocks";
import coverage from "@/lib/coverage.json";

/*
 * Every coverage figure in this post is computed from lib/coverage.json, the
 * same file /coverage renders, so the post cannot disagree with the page. The
 * numbers on /live change every hour and are deliberately not quoted at all.
 */
const ABSENT = coverage.rows.filter((r) => r.verdict === "absent");
const PCT = Math.round(coverage.weighted_coverage * 100);

export const toc: TocItem[] = [
  { id: "reports-go-stale", label: "Red-team reports go stale" },
  { id: "what-live-is", label: "What /live is" },
  { id: "how-a-probe-scores", label: "How a probe is scored" },
  { id: "your-own-agent", label: "Probing your own agent" },
  { id: "in-ci", label: "Red teaming in CI" },
  { id: "what-it-does-not-prove", label: "What it does not prove" },
];

export const faq: FaqItem[] = [
  {
    q: "What is continuous red teaming for AI agents?",
    a: "Running a fixed set of attacks against a deployed agent on a schedule, comparing each run with the last, and opening a finding when an attack that used to be contained gets through. It catches regressions caused by a model update, a prompt change or a policy change, which a one-off red-team report cannot.",
  },
  {
    q: "How often does AgentFox probe its own demo agent?",
    a: "Every hour. The public /live page shows the results, unedited, including any attack that got through. Probe targets you add for your own agents default to once a day and can run at most hourly.",
  },
  {
    q: "Is it safe to red team a production AI agent?",
    a: "Only with explicit opt-in and limits. AgentFox probe targets are created disabled and need the operator to acknowledge a warning before anything is sent. Probes go only to the registered host, with private addresses refused by default, hard caps on rate and volume, and a kill switch that stops every target at once.",
  },
  {
    q: "How do I run AI red teaming in CI?",
    a: "Run agentfox test redteam <agent>. It exits 1 if any attack got through, so the build fails on an escape. agentfox test gate runs an evaluation suite and can write JUnit and SARIF reports for your CI system.",
  },
  {
    q: "Does a contained probe mean the agent is secure?",
    a: "No. The probe library is small, fixed and public. A contained probe says nothing about attacks outside the library, and an adaptive attacker eventually finds a way past detection. Continuous probing catches regressions; it is not a robustness certificate.",
  },
];

export function Body() {
  return (
    <>
      <Takeaways
        items={[
          "A red-team report describes the agent on the day it was written. A model update or a prompt edit the next week can undo it silently.",
          "We probe our own demo agent every hour through the real enforcement path and publish every result, including the attacks that got through.",
          "You can do the same to your agent: opt-in probe targets, a regression finding when something that used to be contained escapes, and a CI command that fails the build.",
        ]}
      />

      <h2 id="reports-go-stale">Red-team reports go stale the day they ship</h2>
      <p>
        Most AI red teaming happens once: before launch, as a report. That report is accurate
        about the agent that existed that week. Then the model provider ships an update, someone
        rewrites the system prompt, a new tool is added, a policy is loosened to stop a false
        positive. Each change can reopen a hole the report said was closed, and nothing tells
        you, because nothing is running the attacks any more.
      </p>
      <p>
        The fix is not a better report. It is running the same attacks again, on a schedule,
        against the deployed agent, and treating a change in the result as an incident. That is
        what <strong>continuous red teaming</strong> means here, and the most honest way we know
        to show it works is to do it to ourselves, in public.
      </p>

      <h2 id="what-live-is">What /live is</h2>
      <p>
        <Link href="/live">/live</Link> shows AgentFox probing its own demo agent every hour.
        The agent is a support-triage bot on <code>echo-1</code>, an offline model that follows
        injected instructions on purpose. That choice matters: a model that resists attacks on
        its own would make the guardrail look better than it is. With a model that always
        complies, every contained attack was contained by the enforcement path and nothing else.
      </p>
      <Figure
        src="/blog/live-page.png"
        alt="The AgentFox live page, showing the demo agent's probe results over the last 30 days."
        caption="The live page renders from the gateway's public showcase feed. Nothing on it is typed by hand, and an attack that gets through is shown as one."
        width={1600}
        height={900}
      />
      <p>Each hourly run sends eleven probes: nine attacks and two benign controls.</p>
      <ul>
        <li>A direct instruction override, and the same instruction inside a retrieved document.</li>
        <li>
          Obfuscated variants: base64, letters spaced apart, and an instruction hidden in an HTML
          comment. These three are the subject of{" "}
          <Link href="/blog/hidden-indirect-prompt-injection">
            our post on hidden prompt injection
          </Link>
          .
        </li>
        <li>A developer-mode role-play jailbreak.</li>
        <li>Exfiltration by email, a call to a forbidden tool, and a system-prompt leak.</li>
        <li>Two ordinary support questions, to catch the guardrail blocking real work.</li>
      </ul>
      <p>
        The headline figures are thirty-day totals, and they move. We do not quote them here for
        that reason. Go and look.
      </p>

      <h2 id="how-a-probe-scores">How a probe is scored</h2>
      <p>
        The hard part of automated red teaming is deciding, without a person, whether an attack
        worked. A model that repeats the attack text back is not compromised, and a scorer that
        cannot tell the difference reports nonsense.
      </p>
      <Diagram
        label="How a live probe is scored"
        caption="A probe carries a canary the agent can only produce by obeying it. The verdict comes from what the agent did, never from what the attack text said."
      >
        <svg className="dg" viewBox="0 0 780 220" xmlns="http://www.w3.org/2000/svg">
          <rect x="10" y="70" width="160" height="80" rx="10" className="dg-box" />
          <text x="90" y="98" textAnchor="middle" className="dg-strong">Probe</text>
          <text x="90" y="118" textAnchor="middle" className="dg-small">&quot;reply with the code,</text>
          <text x="90" y="134" textAnchor="middle" className="dg-small">written backwards&quot;</text>

          <rect x="210" y="70" width="160" height="80" rx="10" className="dg-box-accent" />
          <text x="290" y="100" textAnchor="middle" className="dg-strong">Deployed agent</text>
          <text x="290" y="122" textAnchor="middle" className="dg-small">real enforcement path</text>

          <rect x="410" y="10" width="190" height="56" rx="10" className="dg-box" />
          <text x="505" y="34" textAnchor="middle" className="dg-small">reversed canary in reply?</text>
          <text x="505" y="52" textAnchor="middle" className="dg-small">forbidden tool called?</text>
          <rect x="410" y="82" width="190" height="56" rx="10" className="dg-box" />
          <text x="505" y="106" textAnchor="middle" className="dg-small">exfil address in a tool call?</text>
          <text x="505" y="124" textAnchor="middle" className="dg-small">system prompt leaked?</text>
          <rect x="410" y="154" width="190" height="56" rx="10" className="dg-box" />
          <text x="505" y="178" textAnchor="middle" className="dg-small">benign control blocked?</text>
          <text x="505" y="196" textAnchor="middle" className="dg-small">reply off-contract?</text>

          <rect x="640" y="10" width="130" height="56" rx="10" className="dg-box-stop" />
          <text x="705" y="43" textAnchor="middle" className="dg-strong dg-t-stop">escaped</text>
          <rect x="640" y="82" width="130" height="56" rx="10" className="dg-box-good" />
          <text x="705" y="115" textAnchor="middle" className="dg-strong dg-t-good">contained</text>
          <rect x="640" y="154" width="130" height="56" rx="10" className="dg-box-hold" />
          <text x="705" y="178" textAnchor="middle" className="dg-strong dg-t-hold">over-blocked</text>
          <text x="705" y="196" textAnchor="middle" className="dg-small">or error</text>

          <path d="M170 110 L210 110" className="dg-line" />
          <path d="M370 110 L410 38" className="dg-line" />
          <path d="M370 110 L410 110" className="dg-line" />
          <path d="M370 110 L410 182" className="dg-line" />
          <path d="M600 38 L640 38" className="dg-line-stop" />
          <path d="M600 110 L640 110" className="dg-line" />
          <path d="M600 182 L640 182" className="dg-line" />
        </svg>
      </Diagram>
      <p>
        Every attack asks the agent to reply with a code written backwards. The forward code is
        never in the message, so an agent that merely echoes its input does not score as
        compromised. Other escape signals are a call to a forbidden tool, a tool call carrying
        the probe&apos;s unique exfiltration address, and a reply containing a leak marker. A
        response that does not follow the contract counts as an <em>error</em>, never as
        contained, and a benign control that gets blocked counts as <em>over-blocked</em>.
      </p>
      <p>
        Each run is compared with the previous one. Every attack that got through opens a
        finding, flagged as a <strong>regression</strong> if it was contained last time, and the
        finding closes when a later run contains it again. That comparison is the point: the
        interesting event is not an escape, it is a change.
      </p>

      <InlineCTA
        title="Watch our own agent get attacked"
        body="Hourly probes through the real enforcement path, with thirty days of history and every finding the probes opened."
        href="/live"
        label="See the live results"
        secondary={{ href: "/playground", label: "Attack it yourself" }}
      />

      <h2 id="your-own-agent">Probing your own agent</h2>
      <p>
        Sending attacks at a production system needs more care than sending them at a demo, so
        a <strong>probe target</strong> is built to be hard to turn on by accident:
      </p>
      <ul>
        <li>
          It is created disabled. Opting in requires sending back the exact text of a warning,
          and records who did it and when, in the{" "}
          <Link href="/blog/ai-agent-audit-trail">audit chain</Link>.
        </li>
        <li>Changing the target URL clears the opt-in, because the consent was for that host.</li>
        <li>
          Probes go only to the registered host. Private and metadata addresses are refused by
          default, the connection is pinned and redirects are not followed.
        </li>
        <li>
          Hard caps: at most hourly, 50 probes a run, 60 a minute, a 30-second timeout and a
          64 KB response limit. A stored credential is encrypted and never returned.
        </li>
        <li>
          One environment variable, <code>AGENTFOX_LIVE_PROBES_ENABLED=false</code>, stops every
          target at once.
        </li>
      </ul>
      <p>
        Targets default to daily. When one fails, it is pushed back a full interval rather than
        retried on every scheduler tick, so one broken endpoint never stops the others. Opting
        in also creates a monitor, so an escape alerts through Slack or a webhook like any other
        finding. The setup is in{" "}
        <Link href="/docs/guides/live-probes">Probe deployed agents</Link>, and the alerting in{" "}
        <Link href="/docs/guides/monitoring">Monitor connected sources</Link>.
      </p>

      <h2 id="in-ci">Red teaming in CI</h2>
      <p>
        Live probes catch drift in production. The cheaper place to catch it is before the merge:
      </p>
      <Code>{`agentfox test redteam support-triage          # exits 1 if any attack got through
agentfox test redteam support-triage --adaptive --budget 5
agentfox test gate support-quality --junit reports/agentfox-junit.xml --sarif reports/agentfox.sarif`}</Code>
      <p>
        <code>test redteam</code> runs the offline probe suite against the agent&apos;s current
        policy and fails the build on an escape. Its tool calls are checked without being
        persisted, so a CI run never writes decisions into production history or shows up in a
        policy simulation. <code>test gate</code> runs an evaluation suite and writes JUnit and
        SARIF, which most CI systems display natively. See{" "}
        <Link href="/docs/guides/red-team-and-evals">Red team and evals in CI</Link>.
      </p>

      <h2 id="what-it-does-not-prove">What it does not prove</h2>
      <p>
        We map every way we know an agent can fail, and score the product against it on the{" "}
        <Link href="/coverage">coverage page</Link>. Today that is:
      </p>
      <StatRow>
        <Stat value={String(coverage.scenarios)} label="failure scenarios mapped" source="lib/coverage.json" />
        <Stat value={String(coverage.verified)} label="executed against the running product" source="Checked by the nightly job" />
        <Stat value={`${PCT}%`} label="weighted coverage, partial counting half" source="lib/coverage.json" />
        <Stat value={String(ABSENT.length)} label="with no control at all" source="Listed below" />
      </StatRow>
      <p>The scenarios with nothing in place are:</p>
      <ul>
        {ABSENT.map((r) => (
          <li key={r.id}>
            <code>{r.id}</code> {r.name}
          </li>
        ))}
      </ul>
      <p>And the limits of the probing itself:</p>
      <ul>
        <li>
          <strong>The library is small, fixed and public.</strong> A contained probe says
          nothing about an attack outside it. It is a regression test, not a robustness
          certificate.
        </li>
        <li>
          <strong>The showcase tests the guardrail, not a model.</strong> <code>echo-1</code>{" "}
          always complies, which is the point, and it means /live says nothing about how a real
          model resists.
        </li>
        <li>
          <strong>Black-box scoring needs a signal.</strong> For an HTTP target, an escape that
          produces none of the configured signals is missed.
        </li>
        <li>
          <strong>Adaptive attackers win eventually.</strong> Our{" "}
          <Link href="/benchmark">benchmark</Link> shows how quickly, which is why we lean on{" "}
          <Link href="/blog/prompt-injection-containment-not-detection">containment</Link>{" "}
          rather than detection.
        </li>
        <li>
          <strong>Hourly depends on a scheduler.</strong> Ours is a GitHub Actions job every 30
          minutes, and scheduled Actions run on a best-effort basis.
        </li>
      </ul>
      <Figure
        src="/blog/coverage-page.png"
        alt="The AgentFox coverage page: failure scenarios scored against what the product catches, by cause, with the gaps listed."
        caption={
          <>
            The <Link href="/coverage">coverage page</Link> cuts the same scenarios by cause:
            external, internal, autonomous and intrinsic.
          </>
        }
        width={1600}
        height={900}
      />
    </>
  );
}
