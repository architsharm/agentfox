import type { Metadata } from "next";
import Link from "next/link";

import { Code, NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Quickstart",
  description:
    "Connect the agents in your repository to AgentFox: create a key, run agentfox init, add the agents, test them, and turn on the basic guardrails.",
  path: "/docs/quickstart",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Quickstart</h1>
      <p className="docs-lede">
        Connect your repository, see its agents, attack them, and turn on guardrails. About five
        minutes. You need Python 3.11 or newer.
      </p>

      <Steps>
        <Step title="Create a key">
          <p>
            <Link href="/login">Sign in</Link>; signing in creates your workspace. On the Agents page,
            press <strong>Create a key</strong> and copy it. It is shown once.
          </p>
          <Screenshot {...SCREENS.setupKey} />
        </Step>

        <Step title="Run init in your repository">
          <p>Copy the command from the card. It has your key and server filled in.</p>
          <Code>{`pip install -U agentfox
agentfox init --key nom_api_… --server https://…`}</Code>
          <p>
            <code>init</code> reads your code without running it and lists the agents and tools it
            found. Answer <strong>Y</strong> so your app&apos;s calls show up on the dashboard. Leave it
            running: it runs the attack tests in the next step.
          </p>
          <Screenshot {...SCREENS.initTerminal} />
        </Step>

        <Step title="Add your agents">
          <p>
            Back on the card, press <strong>Add agents to AgentFox</strong>. Each agent may call the
            tools its own code gives it, and nothing else.
          </p>
          <Screenshot {...SCREENS.agentsArrive} />
        </Step>

        <Step title="Test, then add the basic guardrails">
          <p>
            The first attack test starts by itself, with no guardrails. When it finishes, press{" "}
            <strong>Turn on basic guardrails and test again</strong>. Each row shows how many attacks got through before
            and after.
          </p>
          <Screenshot {...SCREENS.attackTest} />
        </Step>

        <Step title="Run your app">
          <p>
            Run it as you always do. Each model and tool call appears on the agent&apos;s{" "}
            <strong>Activity</strong> tab with the checks it went through.
          </p>
          <Screenshot {...SCREENS.activity} />
        </Step>
      </Steps>

      <h2>What is on by default</h2>
      <ul>
        <li>A call to a tool the agent was not given is refused.</li>
        <li>
          The basic guardrails block prompt attacks and hide personal data and secrets in replies. On an
          agent with real traffic they watch first, so nothing changes until you{" "}
          <Link href="/docs/protect">switch them to block</Link>.
        </li>
      </ul>

      <h2>If something goes wrong</h2>
      <div className="docs-table"><table>
        <thead>
          <tr>
            <th>You see</th>
            <th>Do this</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>No agent found here.</td>
            <td>Run <code>init</code> in the repository where the agent is defined.</td>
          </tr>
          <tr>
            <td>No such option: --key</td>
            <td>Upgrade: <code>pip install -U agentfox</code>.</td>
          </tr>
          <tr>
            <td>The attack test never starts</td>
            <td>Keep <code>init</code> running. It runs the tests on your machine.</td>
          </tr>
          <tr>
            <td>Nothing on Activity</td>
            <td>
              Start the app from the folder where <code>init</code> ran, or set{" "}
              <Link href="/docs/connect/python#key">the two environment variables</Link>.
            </td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: "/docs/concepts", label: "Core concepts", why: "the five words the rest of the docs use" },
          { href: "/docs/connect", label: "Connect your agent", why: "if your stack needs more than init" },
          { href: "/docs/quickstart/cli", label: "Quickstart without an account", why: "everything on your machine" },
        ]}
      />
    </article>
  );
}
