import type { Metadata } from "next";
import Link from "next/link";

import { NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Attack tests",
  description:
    "Run the built-in attacks against your agent, see what got through, add guardrails and test again. Try a single message, or the public playground.",
  path: "/docs/test",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Attack tests</h1>
      <p className="docs-lede">
        Attack your agent with the built-in attack library, see what got through, and fix it before
        real users find it.
      </p>

      <h2>Before you start</h2>
      <ul>
        <li>
          Your repository is connected with <code>agentfox init</code> (see the{" "}
          <Link href="/docs/quickstart">Quickstart</Link>), and <code>init</code> is still running.
          The attacks run your agent on your machine, with every tool faked.
        </li>
        <li>
          Your agent is built with LangChain or LangGraph, the OpenAI Agents SDK, CrewAI, or is a
          function that runs its own function-calling loop. It runs on its own model, with the key in
          your environment.
        </li>
      </ul>

      <h3>CrewAI</h3>
      <p>
        AgentFox finds a crew in a module-level <code>Crew(...)</code> or in a{" "}
        <code>@CrewBase</code> class (its <code>@crew</code> and <code>@agent</code> methods, with{" "}
        <code>config/agents.yaml</code> and <code>tasks.yaml</code>), and builds a fresh crew for
        each attack. The crew gets the attack in every <code>{"{input}"}</code> its tasks take, as{" "}
        <code>kickoff(inputs=...)</code> would; a hierarchical crew runs its manager, which hands work
        to the agents as it would live. Each agent is also attacked on its own, as the one task of a
        crew. Your tools are faked; CrewAI&apos;s own delegation tools still run. A crew with no{" "}
        <code>{"{input}"}</code> in its tasks, and an agent with MCP servers or CrewAI platform apps,
        are reported as not run, with the reason.
      </p>

      <h3>Agents that hand off</h3>
      <p>
        An agent is attacked through the tools it reaches by handing off too (Agents SDK handoffs
        and agents used as tools, LangGraph supervisor and swarm hand-offs, CrewAI delegation),
        not only its own. A triage agent that can only look up an order but hands refunds to
        another agent is attacked with unsafe refunds: the attack goes to the triage agent, the
        hand-off happens inside the run, and a refund there counts against the triage agent,
        read as <em>reached issue_refund through Refunds specialist</em>. The call is checked
        under the agent that makes it. The agents it hands off to are still attacked on their own.
      </p>

      <Steps>
        <Step title="Run the attack test">
          <p>
            Open <strong>Agents</strong> and pick the project. With nothing selected on the map, the
            panel shows the <strong>Attack test</strong>: one row per attack set. Press the play
            button to run it. Use <strong>+</strong> to add more sets from the library.
          </p>
          <Screenshot {...SCREENS.attackTest} />
        </Step>

        <Step title="Read what got through">
          <p>
            Each row shows how many attacks in that set got through. A set that got through also
            raises an issue on <strong>Issues</strong>, with each attack that was tried and the
            verdict it got.
          </p>
        </Step>

        <Step title="Add guardrails and test again">
          <p>
            Press <strong>Turn on basic guardrails and test again</strong>. It turns on the basic guardrails and reruns
            the same attacks. Each row then reads <em>no guardrails → basic guardrails</em>. For
            what is still getting through, add a{" "}
            <Link href="/docs/protect/custom-rules">custom rule</Link> or tighten{" "}
            <Link href="/docs/govern">tool access</Link>, then run it again.
          </p>
        </Step>

        <Step title="See past runs">
          <p>
            <strong>Testing → Attack tests</strong> lists every run of this test, for every
            project, with the same numbers as the agent&apos;s panel: attacks, stopped, got
            through, and the normal requests. Choose an agent and press <strong>Run</strong> to
            run its project&apos;s test again (its <code>agentfox init</code> must be running).
            An agent&apos;s page shows that agent&apos;s own attacks.
          </p>
          <Screenshot {...SCREENS.testing} />
          <p>
            Without a dashboard, <code>agentfox test redteam &lt;agent&gt;</code> checks the
            same attacks against the agent&apos;s rules with no model: each message, then the
            tool call it is after, as live traffic checks them. It measures your rules; the
            test above measures the agent. Its runs are listed apart, under{" "}
            <strong>Checked without a model</strong>.
          </p>
        </Step>
      </Steps>

      <h2>How to read a result</h2>
      <ul>
        <li>
          <strong>Blocked</strong>: a rule that blocks stopped it. Live traffic is stopped too.
        </li>
        <li>
          <strong>Would block (watching)</strong>: only a rule in Watch stopped it. Real requests
          still go through until you <Link href="/docs/protect">switch that guardrail to Block</Link>.
        </li>
        <li>
          The library includes a few ordinary requests. If one of those is refused, the test reports
          it as over-blocking.
        </li>
        <li>
          A clean run means these attacks were stopped, not that every attack would be. Adaptive mode
          retries blocked attacks in disguised forms; see <Link href="/docs/test/ci">In CI and in
          production</Link>.
        </li>
      </ul>

      <h2>Try one message</h2>
      <p>
        <strong>Testing → Try it</strong> checks a single message or tool call against an
        agent&apos;s real rules and shows the verdict and the rules that matched. It is not counted as
        traffic.
      </p>
      <Screenshot {...SCREENS.tryIt} />

      <h2 id="playground">The public playground</h2>
      <p>
        <Link href="/playground">The playground</Link> needs no account. It has three sample agents:
        try a prompt attack, or ask an agent to call a tool it was not given, and see the decision
        and why. Press <strong>switch to enforce</strong> to see watching (it calls this observe)
        turn into blocking. No model runs and no tool does
        anything real. A sandbox expires 30 minutes after your last action; don&apos;t paste real
        data into it.
      </p>

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
            <td>The play button is greyed out</td>
            <td>
              Run <code>agentfox init</code> in this project&apos;s repository and keep it running.
            </td>
          </tr>
          <tr>
            <td>Waiting for agentfox init on your machine…</td>
            <td>
              <code>init</code> stopped. Start it again in the repository.
            </td>
          </tr>
          <tr>
            <td>&quot;resume it to run the attack test&quot;</td>
            <td>An agent in the project is stopped. Resume it first.</td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: "/docs/test/ci", label: "In CI and in production", why: "fail a build when an attack starts getting through" },
          { href: "/docs/protect/tuning", label: "Fix false positives", why: "if a guardrail refuses ordinary requests" },
        ]}
      />
    </article>
  );
}
