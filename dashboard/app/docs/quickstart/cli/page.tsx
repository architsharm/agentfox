import type { Metadata } from "next";
import Link from "next/link";

import { Code, NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Quickstart without an account",
  description:
    "Find your agents, watch every call your app makes and read the issues, all on your own machine: agentfox scan, agentfox up, agentfox findings.",
  path: "/docs/quickstart/cli",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Quickstart without an account</h1>
      <p className="docs-lede">
        Find the agents in your repository, watch every call your app makes, and read what AgentFox
        found. Nothing leaves your machine. You need Python 3.11 or newer.
      </p>

      <Steps topLevel>
        <Step title="Scan the repository">
          <Code>{`pip install agentfox
agentfox scan`}</Code>
          <p>
            <code>scan</code> reads your code without running it. It names each agent, the tools it
            can reach, and any agent that reads private data, reads untrusted content and can send data
            out.
          </p>
          <Screenshot {...SCREENS.scanTerminal} />
        </Step>

        <Step title="Set up">
          <Code>{`agentfox up`}</Code>
          <p>
            Every question has a recommended answer; press Enter to take it. <code>up</code> registers
            your agents under the names your code uses and adds{" "}
            <code>agentfox.auto(&quot;&lt;agent&gt;&quot;)</code> to the file that starts one: a script
            in <code>pyproject.toml</code>, the graph <code>langgraph.json</code> loads, or the file
            that runs it (<code>Runner.run</code>, <code>crew.kickoff()</code>,{" "}
            <code>graph.invoke()</code>), under <code>src/</code> too. It starts in watch mode, so
            nothing is blocked yet.
          </p>
          <p>
            In a Python agent&apos;s repository it changes nothing else by default: no coding-agent
            hooks, no GitHub workflow, no background processes. Add them with{" "}
            <code>--with coding-agents</code>, <code>--with ci</code> or <code>--with view</code>.
          </p>
        </Step>

        <Step title="Run your app">
          <p>
            Run it as you always do. Each model and tool call is checked and recorded in a database on
            this machine. When the app exits, it prints how many calls it checked.
          </p>
        </Step>

        <Step title="Read what it found">
          <Code>{`agentfox findings`}</Code>
          <p>
            Each row is something a person should look at. &quot;Would have been&quot; means a rule
            caught it and watch mode let it through.
          </p>
        </Step>

        <Step title="Start blocking, one library at a time">
          <Code>{`agentfox policy enforce tool-containment   # tool calls
agentfox policy enforce baseline           # prompt attacks, personal data, secrets`}</Code>
          <p>
            When what it would have stopped is what you want stopped, turn that library to blocking.
            Your app picks it up on its next call, with no code change. Running <code>up</code> again
            never turns it back. <code>agentfox policy observe &lt;library&gt;</code> goes back to
            watching.
          </p>
        </Step>

        <Step title="Attack-test it">
          <Code>{`agentfox test redteam <agent>`}</Code>
          <p>
            Runs the attack probes against the agent&apos;s configuration: prompt injection, data
            exfiltration, destructive actions. <code>up</code> prints the command with your
            agent&apos;s name filled in.
          </p>
        </Step>
      </Steps>

      <h2>Connect to an account later</h2>
      <p>
        <Link href="/login">Sign in</Link> (that creates your workspace), press <strong>Create a key</strong> on the Agents page, and
        run the <code>init</code> command from the card in the same repository. It saves the key in{" "}
        <code>.agentfox/agentfox.env</code>, and from then on your app&apos;s calls go to your account
        and show up on the dashboard. The <Link href="/docs/quickstart">Quickstart</Link> walks through
        it. To set the key another way, see <Link href="/docs/connect/python#key">where auto() finds the key</Link>.
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
            <td>The scan finds no agent</td>
            <td>
              Run it in the repository where the agent is defined. It reads Python, TypeScript and
              JavaScript.
            </td>
          </tr>
          <tr>
            <td><code>agentfox findings</code> is empty</td>
            <td>
              Check that your app starts with <code>agentfox.auto()</code> and that you ran it from the
              folder where you ran <code>up</code>.
            </td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: "/docs/concepts", label: "Core concepts", why: "the words the rest of the docs use" },
          { href: "/docs/connect", label: "Connect your agent", why: "if your stack is not plain Python" },
          { href: "/docs/reference/cli#cmd-up", label: "agentfox up options", why: "take every default, or change nothing" },
        ]}
      />
    </article>
  );
}
