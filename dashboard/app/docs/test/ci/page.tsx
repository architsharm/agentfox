import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Step, Steps } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "In CI and in production",
  description:
    "Fail a build when an attack starts getting through or answer quality drops, score real traffic against a target, and probe a deployed agent on a schedule.",
  path: "/docs/test/ci",
});

const cli = (path: string) => `/docs/reference/cli#cmd-${path}`;

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>In CI and in production</h1>
      <p className="docs-lede">
        Fail a pull request when an agent gets weaker, and keep checking it once it is live.
      </p>

      <h2>Before you start</h2>
      <ul>
        <li>
          Suites and baselines live in the AgentFox database. The CLI gate needs that database:
          the CI job sets <code>AGENTFOX_DATABASE_URL</code> (a secret) to the one you created
          them in.
        </li>
        <li>
          With an account key and no database access (AgentFox Cloud, or a server CI can only
          reach over HTTP), gate over HTTP instead: see{" "}
          <a href="#http">Gate over HTTP</a>.
        </li>
      </ul>

      <Steps>
        <Step title="Fail the build when an attack gets through">
          <p>
            <code>test redteam</code> exits 1 when any attack got through. With{" "}
            <code>--adaptive</code> it also retries blocked attacks in disguised forms (encodings,
            role-play, look-alike tool names) and compares with the last run: <strong>WEAKER</strong>,{" "}
            <strong>STRONGER</strong> or <strong>UNCHANGED</strong>.
          </p>
          <Code>{`agentfox test redteam support-triage --adaptive`}</Code>
          <p>
            The first adaptive run is the baseline. Keep the probe list and <code>--budget</code>{" "}
            the same between runs, or each run starts a new baseline.
          </p>
        </Step>

        <Step title="Keep a test suite">
          <p>
            A suite is a set of prompts and what a good answer contains. Create one on{" "}
            <strong>Testing → Test suites</strong>, then add cases on its page. To turn a real
            failure into a case, paste its trace id (<code>trc_…</code>) under{" "}
            <strong>Promote a trace</strong>. The case asks what the run&apos;s user asked: runs
            keep the user&apos;s message and the reply, with personal data and secrets masked. A
            run with no recorded message (one from an older version) can&apos;t be promoted, and
            says so.
          </p>
        </Step>

        <Step title="Pin a baseline, then gate on it">
          <p>
            Run the suite once with your real model and save that run as the baseline. In CI,{" "}
            <code>test gate</code> runs it again and exits 1 if a score drops by more than 0.05, or
            if any case errored.
          </p>
          <Code title=".github/workflows/agent-tests.yml (steps)" lang="yaml">{`- run: pip install "agentfox[postgres]"
- run: agentfox test redteam support-triage --adaptive
- run: agentfox test gate support-quality --provider openai --model gpt-4o-mini --junit reports/junit.xml --sarif reports/agentfox.sarif`}</Code>
          <p>
            Save the baseline with <Link href={cli("test-baseline")}><code>agentfox test baseline RUN_ID</code></Link>.
            The gate creates the <code>reports/</code> folder if it isn&apos;t there. The{" "}
            <strong>CI</strong> tab on Testing shows these commands, and the HTTP one with your
            server filled in. A real provider needs <code>AGENTFOX_ALLOW_EGRESS=true</code> and its key.
          </p>
        </Step>

        <Step title="Gate over HTTP">
          <p id="http">
            <code>POST /api/eval/gate</code> runs the same gate with an API key. A gate that
            fails answers <strong>412</strong> with the result (<code>passed: false</code>, JUnit,
            SARIF), so <code>curl --fail-with-body</code> fails the step and still saves it. Without{" "}
            <code>--fail</code> (or <code>--fail-with-body</code>) curl exits 0 and the build passes.
          </p>
          <Code>{`curl --fail-with-body -sS -X POST "$AGENTFOX_URL/api/eval/gate" \\
  -H "Authorization: Bearer $AGENTFOX_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"suite": "support-quality", "baseline_run_id": "RUN_ID", "min_pass_rate": 0.9}' \\
  -o gate.json
jq -r .junit gate.json > junit.xml`}</Code>
          <p>
            <code>min_pass_rate</code> is a share from 0 to 1.
          </p>
        </Step>

        <Step title="Scan each pull request">
          <p>
            The <a href="https://github.com/architsharm/agentfox/blob/main/action.yml">AgentFox
            GitHub Action</a> comments on risky tool combinations, poisoned skills and model calls
            without guardrails, and fails the check on the first two. It is static: nothing is run or
            sent. See <Link href="/docs/discover">Discover</Link>.
          </p>
          <Code lang="yaml">{`- uses: actions/checkout@v4
- uses: architsharm/agentfox@main
  with:
    fail-on: trifecta,skills`}</Code>
        </Step>

        <Step title="Score real traffic against a target">
          <p>
            On <strong>Testing → Reliability</strong>, <strong>Score real traffic</strong> grades
            recent runs with the same scorers as a suite. <strong>Add target</strong> sets a goal for
            one agent and one measure, such as 95% of answers grounded over 7 days, and shows how much
            budget is left. Only runs with a recorded reply are scored; the summary counts the
            ones it skipped.
          </p>
          <Code>{`agentfox test online support-triage
agentfox report drift support-triage --scorer groundedness`}</Code>
        </Step>
      </Steps>

      <Callout kind="warning">
        Suites default to the offline <code>echo</code> model, which repeats the prompt. A run left on
        it proves the pipeline works, not that your agent answers well.
      </Callout>

      <h2 id="live">Probe a live agent</h2>
      <p>
        AgentFox can send a small, fixed set of attacks (9 attacks and 2 ordinary questions) to a
        deployed agent&apos;s endpoint on a schedule. When an attack that was stopped last time gets
        through, it opens an issue; when a later run stops it again, it closes the issue.
      </p>
      <ul>
        <li>
          Set it up over the API: register the endpoint (<code>POST /api/probes/targets</code>, created
          off), then opt in with the exact warning text from <code>GET /api/probes/warning</code>.
          The opt-in is recorded on the audit trail. See{" "}
          <Link href="/docs/reference/api#api-probes">the probes routes</Link>.
        </li>
        <li>
          Your endpoint takes <code>{`{"message": …}`}</code> and answers with the{" "}
          <code>reply</code>, any <code>tool_calls</code>, and <code>blocked</code>.
        </li>
        <li>
          At most one scheduled run an hour and one manual run every ten minutes. Only the host you
          opted in for is contacted. <code>AGENTFOX_LIVE_PROBES_ENABLED=false</code> stops every target.
        </li>
      </ul>
      <Callout kind="warning">
        Probes send real attacks. If the agent can reach real systems, one that gets through can act
        on them. Sandbox its tools for probe traffic: every request carries an{" "}
        <code>X-AgentFox-Probe</code> header.
      </Callout>

      <h2>If something goes wrong</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>You see</th>
            <th>Do this</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <code>unknown suite</code> in CI
            </td>
            <td>
              <code>AGENTFOX_DATABASE_URL</code> points at a different database from the one you created
              the suite in.
            </td>
          </tr>
          <tr>
            <td>
              <code>GATE FAIL</code> with errored cases
            </td>
            <td>The model was not reached. Check egress and the provider key.</td>
          </tr>
          <tr>
            <td>&quot;No previous adaptive campaign&quot; on every run</td>
            <td>The probe list or <code>--budget</code> changed. Keep them fixed.</td>
          </tr>
          <tr>
            <td>A target reads &quot;No data&quot;</td>
            <td>Press <strong>Score real traffic</strong> for that agent first.</td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: cli("test"), label: "test in the CLI reference", why: "every option of redteam, run, gate and online" },
          { href: "/docs/prove", label: "Activity and issues", why: "where escapes and regressions land" },
        ]}
      />
    </article>
  );
}
