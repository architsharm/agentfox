import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Evaluation",
  description:
    "Suites, cases, promoting a trace to a case, runs and results, the human review queue, scorers, SLOs, drift, online evaluation and red-team campaigns.",
  path: "/docs/app/evals",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Web app</p>
      <h1>Evaluation</h1>
      <p className="docs-lede">
        Whether an agent gets the answer right, graded by scorers and tracked over time; and
        whether the built-in attacks get through it.
      </p>
      <InTheApp path="/app/evals">Evaluation</InTheApp>

      <h2>When to use this</h2>
      <ul>
        <li>To get a first quality number from real traffic without writing test cases.</li>
        <li>To keep a regression suite, fed from production failures.</li>
        <li>To set a reliability objective and see how much error budget is left.</li>
        <li>To run the attack probes against an agent before and after promoting a policy.</li>
      </ul>

      <h2>The Evaluation page</h2>
      <p>
        <code>/app/evals</code> loads <code>GET /api/eval/suites</code>,{" "}
        <code>/api/eval/runs</code>, <code>/api/eval/scorers</code>,{" "}
        <code>/api/eval/slos</code> and <code>/api/redteam/campaigns</code>. A strip counts
        suites, recent runs, scorers and red-team campaigns.
      </p>
      <ul>
        <li>
          <strong>Latest run</strong>: runner, mode and case count, and per scorer the mean, min,
          max and pass rate (green at 90% and above, amber from 70%). If cases failed, a link
          to promote a production failure into that suite.
        </li>
      </ul>

      <h3 id="slos">Reliability &amp; SLOs</h3>
      <p>
        An SLO is a target for one agent and one scorer, for example &quot;95% of answers stay
        grounded, measured over 7 days&quot;. The form takes agent, scorer, objective text,
        window (1, 7 or 30 days) and target (0 to 1), and posts to{" "}
        <code>POST /api/eval/slos</code>. The table shows attainment, error budget remaining,
        and a <strong>check drift →</strong> link. Attainment is measured from online samples
        (next section); without them it reads &quot;no data&quot;. SLOs also show on the
        agent&apos;s Activity tab.
      </p>

      <h3>Score real production traffic</h3>
      <p>
        Pick an agent and a window (1, 7, 30 or 90 days) and press{" "}
        <strong>Sample &amp; score</strong> (<code>POST /api/eval/online</code>). It runs the
        offline scorers (groundedness, task completion, silent failure) over traces already
        recorded, with no model call and no suite to write. The result is stored as a suite
        named <code>online:&lt;agent&gt;</code>.
      </p>
      <Output title="Notice after Sample & score">{`Sampled 2 recent trace(s) from 'support-triage' and scored them.`}</Output>

      <h3>Drift</h3>
      <p>
        <strong>check drift →</strong> on an SLO compares that scorer&apos;s recent online
        samples with its baseline window, using the population stability index (PSI): above
        about 0.1 is worth a look, above about 0.25 usually means something changed. Without
        enough samples in both windows it says so. From{" "}
        <code>GET /api/eval/drift?agent=…&amp;scorer=…</code>.
      </p>

      <h3>Suites</h3>
      <p>
        Key, description, tags and case count, each linking to the suite. The form under the
        table creates one: key, optional name and description (<code>POST /api/eval/suites</code>).
      </p>

      <h2 id="cases">A suite: cases, promoting a trace, running it</h2>
      <InTheApp path="/app/evals">Evaluation → a suite</InTheApp>
      <p><code>/app/evals/&lt;key&gt;</code>:</p>
      <ul>
        <li>
          <strong>Cases</strong>: prompt, expected goal, split (test or regression), and
          source: &quot;hand-authored&quot; or the trace it came from.
        </li>
        <li>
          <strong>Add a case</strong>: a prompt and an optional expected goal (
          <code>POST /api/eval/suites/&#123;key&#125;/cases</code>).
        </li>
        <li>
          <strong>Promote a trace</strong>: paste a <code>trc_…</code> id to turn a real
          execution into a regression case (
          <code>POST /api/eval/suites/&#123;key&#125;/cases/from-trace</code>). The trace&apos;s
          intent becomes the prompt and the goal.
        </li>
        <li>
          <strong>New run</strong>: optional agent (fits that agent&apos;s reliability envelope),
          provider (default <code>echo</code>), model (default <code>echo-1</code>), and the
          scorers to use (none ticked means the default set). Disabled until the suite has a
          case. Posts <code>POST /api/eval/runs</code>.
        </li>
        <li><strong>Runs</strong>: id, runner, status and case count, each linking to the run.</li>
      </ul>
      <Callout kind="warning">
        The default provider is <code>echo</code>, which answers offline with a fixed stub. A
        run left on it proves the pipeline works, not that a model answers well. Set a real
        provider and model to evaluate one.
      </Callout>

      <h3>A run: results and the review queue</h3>
      <p>
        <code>/app/evals/&lt;key&gt;/runs/&lt;run id&gt;</code> (<code>GET /api/eval/runs/&#123;id&#125;</code>)
        shows the per-scorer summary and every case result with its score, pass or fail and
        output.
      </p>
      <p>
        <strong>Needs human review</strong> lists results within 0.1 of the scorer&apos;s
        threshold, or where scorers disagree on the same case (from{" "}
        <code>GET /api/eval/annotations/queue</code>). <strong>Annotate</strong> asks whether the
        scorer was right (agree or disagree) and requires a note; it saves with{" "}
        <code>POST /api/eval/results/&#123;id&#125;/annotate</code> and the row is tagged{" "}
        <code>reviewed</code>.
      </p>
      <Code>{`agentfox test suites
agentfox test run support-quality`}</Code>
      <Output>{`suite                  name                            cases
online:support-triage  Online sample — support-triage  2
support-quality        Support answer quality          7
support-quality — 7 cases, 0 errors
  run run_01m469xha1byj5jmxp · \`agentfox test baseline run_01m469xha1byj5jmxp\` to pin it
scorer            mean    min    max  pass rate
fuzzy_match      1.000  1.000  1.000       100%
groundedness     0.286  0.000  1.000        29%
task_completion  0.429  0.000  1.000        43%
silent_failure   0.336  0.000  0.500        29%`}</Output>

      <h3>Scorers and the CI gate</h3>
      <p>
        The <strong>Scorers and the CI gate</strong> button lists the scorers that ship (20 in
        this build: exact and fuzzy match, regex, JSON schema, latency, cost, tool trajectory,
        safety, LLM judge, groundedness, task completion, silent failure, the RAGAS set and
        others) with their kind, direction and built-in threshold. Thresholds are fixed; the
        number you choose is an SLO. Gating a build is a command, not a screen:
      </p>
      <Code>{`agentfox test baseline run_01m469xha1byj5jmxp --label main
agentfox test gate support-quality --baseline run_01m469xha1byj5jmxp --junit results.xml`}</Code>
      <p>
        <code>test gate</code> exits 1 on a regression. (The explainer in the app shows these
        under their older <code>eval</code> name.) See{" "}
        <Link href="/docs/guides/red-team-and-evals">Red team and evals in CI</Link>.
      </p>

      <h2 id="redteam">Red-team posture</h2>
      <p>
        Pick an agent and <strong>Run built-in probes</strong> (
        <code>POST /api/redteam/campaigns</code>). A campaign runs the probe library through the
        same enforcement path as live traffic, with that agent&apos;s real grants and policy
        bindings. The table lists each campaign: probes run, attacks blocked, attacks that got
        through, and posture (the share blocked). The library includes benign control probes,
        and a benign probe that is refused raises an Over-blocking finding.
      </p>
      <Code>{`agentfox test redteam support-triage`}</Code>
      <Output>{`support-triage — 22 probes (18 attacks, 4 benign controls)
  recall (attacks caught) 100% — 18 blocked, 0 got through
  precision 100% — no benign controls wrongly blocked
probe                                     severity  OWASP  verdict   result
injection.direct_override                 high      LLM01  block     blocked
injection.indirect_document               critical  LLM01  block     blocked
…
benign.refund_within_constraint           low       —      allow     allowed
benign.independently_supplied_id          low       —      allow     allowed`}</Output>
      <Callout kind="note">
        A high posture is a narrow claim: the probes in this library did not get through. An
        attack nobody wrote a probe for scores the same as one that was stopped. The full probe
        list is on <Link href="/docs/app/policies">Policies</Link> under Attack simulations.
      </Callout>

      <h2>Common tasks</h2>
      <TaskTable
        rows={[
          { task: "List suites", run: "agentfox test suites" },
          { task: "Run a suite", run: "agentfox test run support-quality" },
          { task: "Score real traffic", run: "agentfox test online support-triage --since-days 30" },
          { task: "Check a scorer for drift", run: "agentfox report drift support-triage --scorer groundedness" },
          { task: "Pin a baseline", run: "agentfox test baseline RUN_ID --label main" },
          { task: "Fail CI on regression", run: "agentfox test gate support-quality --min-pass-rate 0.9" },
          { task: "Run the attack probes", run: "agentfox test redteam support-triage" },
          { task: "List the probes", run: "agentfox test probes" },
        ]}
      />

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong>Run is disabled: &quot;Add a case first&quot;.</strong> The suite has no cases.
        </li>
        <li>
          <strong>SLO attainment says &quot;no data&quot;.</strong> No online samples for that
          agent and scorer in the window. Use Sample &amp; score.
        </li>
        <li>
          <strong>Drift says not enough samples.</strong> It needs online samples in both the
          current and the baseline window.
        </li>
        <li>
          <strong>Every score is the same across runs.</strong> The provider is still{" "}
          <code>echo</code>.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>No editing or deleting of cases or suites in the web app.</li>
        <li>Adaptive red teaming (<code>--adaptive</code>) is CLI only.</li>
        <li>Runs started from the web app run the suite once; scheduling is up to your CI.</li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/guides/red-team-and-evals", label: "Red team and evals in CI", why: "the gate and adaptive probes" },
          { href: "/docs/app/traces", label: "Traces", why: "find a trace to promote" },
          { href: "/docs/app/policies", label: "Policies", why: "promote once the red team is clean" },
        ]}
      />
    </article>
  );
}
