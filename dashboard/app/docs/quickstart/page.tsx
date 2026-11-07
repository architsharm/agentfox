import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Quickstart",
  description:
    "Connect the agents in your repository to AgentFox: create a key, run agentfox init, add the agents, test them, and see your app's calls. Or do it all from the command line.",
  path: "/docs/quickstart",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Start</p>
      <h1>Quickstart</h1>
      <p className="docs-lede">
        From your repository to its agents guarded, tested and visible on the dashboard in a
        few minutes. You need Python 3.11 or newer.
      </p>
      <p>
        There are two ways in. With the <a href="#dashboard">dashboard</a>, the setup card
        walks you through it and the attack test runs for you. From the{" "}
        <a href="#cli">command line only</a>, everything stays on your machine. Both find the
        same agents and give them the same names.
      </p>

      <h2 id="dashboard">With the dashboard</h2>
      <Steps>
        <Step title="Create a key">
          <p>
            <Link href="/login">Sign up</Link>. The Agents page opens on{" "}
            <strong>Connect your first agent</strong>. Press <strong>Create a key</strong> and
            copy it: it is a workspace API key (<code>nom_api_…</code>), shown once. Keep it out
            of your code.
          </p>
          <Screenshot {...SCREENS.setupKey} caption="The setup card fills your key and server into the command for step 2." />
        </Step>

        <Step title="Run agentfox init in the repository">
          <Code>{`pip install agentfox
agentfox init --key nom_api_… --server https://…`}</Code>
          <p>
            Copy the command from the card: it has your key and server filled in.{" "}
            <code>init</code> reads your code without running it, prints the agents and tools
            it recognised, and reports them to your workspace. Then it asks:
          </p>
          <Screenshot {...SCREENS.initTerminal} caption={<>Answer <code>Y</code> to see your app&apos;s calls on the dashboard.</>} />
          <p>
            Yes adds <code>agentfox.auto(&quot;&lt;agent&gt;&quot;)</code> to the file that runs
            the agent, and saves the key and server in <code>.agentfox/agentfox.env</code>{" "}
            (readable only by you, and git-ignored). No prints the line for you to add. Leave{" "}
            <code>init</code> running: it runs the attack tests on your machine when the
            dashboard asks for them. Ctrl-C stops it.
          </p>
        </Step>

        <Step title="Add the agents">
          <p>
            The card lists what <code>init</code> found. Press{" "}
            <strong>Add N agents to AgentFox</strong>.
          </p>
          <Screenshot {...SCREENS.agentsArrive} />
          <p>
            Each agent is allowed the tools its own code hands it, and nothing else. A read
            tool is allowed whatever its arguments came from. A tool that changes something or
            sends data out is allowed only with values from what the user asked, so an argument
            copied out of a tool result or a web page is still stopped.
          </p>
        </Step>

        <Step title="Test, add basic guardrails, test again">
          <p>
            The first attack test runs by itself, with no guardrails: <code>init</code> runs
            your agent against each attack with every tool faked. When it finishes, press{" "}
            <strong>Add and test again</strong> under <strong>Add basic guardrails</strong>.
            Each row then shows how many attacks got through before and after.
          </p>
          <Screenshot {...SCREENS.attackTest} />
          <p>The basic guardrails are four rules for each agent:</p>
          <ul>
            <li>block prompt attacks and jailbreaks in what users send;</li>
            <li>block instructions hidden in what the agent reads (tool results, documents);</li>
            <li>hide personal data in replies;</li>
            <li>hide secrets in replies.</li>
          </ul>
          <p>
            For a new agent with no real traffic yet, they go live blocking. For an agent whose
            recorded traffic they would change, they watch, and you switch them on from{" "}
            <Link href="/docs/app/policies#libraries">Policies → Libraries</Link> after the
            simulation looks right.
          </p>
        </Step>

        <Step title="Run your app">
          <p>
            Run it as you always do. Its model and tool calls show up on the agent&apos;s{" "}
            <strong>Activity</strong> tab, each with the checks it went through and the
            verdict.
          </p>
          <Screenshot {...SCREENS.activity} />
        </Step>
      </Steps>

      <h2 id="cli">From the command line only</h2>
      <Steps>
        <Step title="Scan">
          <Code>{`pip install agentfox
agentfox scan`}</Code>
          <p>
            A static read of the repository: nothing is started or sent. It names each agent it
            found, the tools it can reach, and every place where one agent reads private data,
            reads untrusted content and can send data out (the lethal trifecta).
          </p>
          <Screenshot {...SCREENS.scanTerminal} />
        </Step>

        <Step title="Set up">
          <Code>{`agentfox up`}</Code>
          <p>
            <code>up</code> registers your agents under the names the code uses, declares the
            tools it found, and adds <code>agentfox.auto()</code> to your Python entry point,
            LangGraph, LangChain, CrewAI and AutoGen apps included. Every question has a
            recommended answer; <code>agentfox up --yes</code> takes them all and{" "}
            <code>agentfox up --dry-run</code> changes nothing. It starts in watch mode.
          </p>
        </Step>

        <Step title="Run your app, then read what it found">
          <Code>{`agentfox findings`}</Code>
          <p>
            Every call your app made was checked and recorded on this machine. Findings are
            what a person should look at; &quot;would have been&quot; means a rule decided it
            and watch mode let it through.
          </p>
        </Step>
      </Steps>

      <h2 id="one-key">Where your app&apos;s calls go</h2>
      <p>
        <code>agentfox.auto()</code> looks for an account key, first match wins:{" "}
        <code>auto(server=…, key=…)</code>, then <code>AGENTFOX_URL</code> and{" "}
        <code>AGENTFOX_API_KEY</code> in the environment, then{" "}
        <code>.agentfox/agentfox.env</code> in the working directory. With a key, every check
        goes to that account&apos;s gateway and the calls appear on its dashboard. Without one,
        the checks run in your process and are recorded in a local database. One key works
        everywhere: <code>init</code>, your app, and your deployed app with the same two
        variables set.
      </p>
      <Code lang="bash" title="In production">{`export AGENTFOX_URL=https://…
export AGENTFOX_API_KEY=nom_api_…`}</Code>

      <Callout kind="note" title="What is blocked on day one">
        Tool containment applies from the start: a call to a tool the agent was not allowed
        is refused, and an untrusted value headed for a tool that changes something is
        refused or held for a person. Content rules watch until you switch them on, except
        the basic guardrails on a new agent. <code>auto(mode=&quot;observe&quot;)</code>{" "}
        never blocks anything. Details are in <Link href="/docs/guides/python-auto">One line in Python</Link>.
      </Callout>

      <h2>If something goes wrong</h2>
      <table>
        <thead>
          <tr>
            <th>You see</th>
            <th>What to do</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>No agent found here.</code></td>
            <td>
              Run <code>init</code> in the repository where the agent is defined. It reads
              Python, TypeScript and JavaScript and recognises known frameworks; an agent behind
              a wrapper it does not know is invisible to it.
            </td>
          </tr>
          <tr>
            <td><code>No such option: --key</code></td>
            <td>Your <code>agentfox</code> is older than 0.5. <code>pip install -U agentfox</code>.</td>
          </tr>
          <tr>
            <td>The attack test never starts</td>
            <td><code>init</code> has to be running; it runs the tests on your machine.</td>
          </tr>
          <tr>
            <td>Nothing shows under Activity</td>
            <td>
              Check that the app starts with <code>agentfox.auto()</code> and that it runs
              where <code>.agentfox/agentfox.env</code> is, or with <code>AGENTFOX_URL</code>{" "}
              and <code>AGENTFOX_API_KEY</code> set. The startup banner says &quot;Every check
              goes to your AgentFox account&quot; when it found them.
            </td>
          </tr>
        </tbody>
      </table>

      <NextSteps
        items={[
          { href: "/docs/guides/walkthrough", label: "Offline walkthrough", why: "every step by hand on a sample agent, with real output" },
          { href: "/docs/guides/python-auto", label: "One line in Python", why: "modes, what auto() sees, and how to enforce" },
          { href: "/docs/guides/contain-tool-calls", label: "Contain tool calls", why: "grants, limits and approvals" },
          { href: "/docs/guides/gateway", label: "Any language: the gateway", why: "the same checks over HTTP" },
        ]}
      />
    </article>
  );
}
