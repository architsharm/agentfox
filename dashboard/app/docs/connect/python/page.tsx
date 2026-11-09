import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Python apps",
  description:
    "Add agentfox.auto() to a Python app so every model call and tool call is checked and shows on the dashboard. Watch first, then block.",
  path: "/docs/connect/python",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Python apps</h1>
      <p className="docs-lede">
        Add one line, and every model call and tool call in your app is checked and shows on the
        agent&apos;s Activity tab.
      </p>

      <h2>Before you start</h2>
      <ul>
        <li>
          If you ran <code>agentfox init</code> or <code>agentfox up</code> and answered Y, the line is
          already there. Skip to step 2.
        </li>
      </ul>

      <Steps>
        <Step title="Add the line">
          <p>Put it at startup, before any code that calls a model.</p>
          <Code lang="python" title="main.py">{`import agentfox

agentfox.auto(agent="support-triage", intent="answer customer questions about orders")`}</Code>
          <p>
            <code>agent</code> is the name everything is recorded under. Set it, so renaming a file
            does not make a new agent. <span id="intent" /><code>intent</code> is the agent&apos;s task
            in a sentence. Tool containment judges an irreversible tool call against it: with no task
            declared, such a call is held for a person once Tool containment blocks, and recorded as
            would-hold while it watches (<code>intent.undeclared_irreversible</code>), since nothing
            says it is part of the job.
          </p>
        </Step>

        <Step title="Run your app">
          <p>
            Run it from the folder where <code>init</code> ran, or set the{" "}
            <a href="#key">two environment variables</a>. At startup it prints what it patched; with a
            key it adds &quot;Every check goes to your AgentFox account&quot;. Each call then shows up
            with the checks it went through.
          </p>
          <Screenshot {...SCREENS.activity} />
        </Step>

        <Step title="Look at the issues, then block">
          <p>
            Every library starts in Watch, so nothing is stopped. When the <strong>Issues</strong> page
            shows only what you want stopped, switch that library to Block (Policies → Libraries, or{" "}
            <code>agentfox policy enforce tool-containment</code>). <code>auto()</code> follows the
            change with no code change: in its default mode the libraries decide.
          </p>
          <p>
            A line with <code>mode=&quot;observe&quot;</code> (earlier versions of{" "}
            <code>agentfox up</code> wrote one) never blocks, whatever the libraries say: remove it.{" "}
            <code>agentfox policy enforce</code> names any such line it finds.
          </p>
        </Step>
      </Steps>

      <h2 id="key">Where auto() finds the account key</h2>
      <p>It takes the first of these it finds:</p>
      <ol>
        <li>
          <code>agentfox.auto(server=&quot;https://…&quot;, key=&quot;nom_api_…&quot;)</code>
        </li>
        <li>
          <code>AGENTFOX_URL</code> and <code>AGENTFOX_API_KEY</code> in the environment
        </li>
        <li>
          <code>.agentfox/agentfox.env</code> in the working directory, which{" "}
          <code>agentfox init --key</code> writes
        </li>
      </ol>
      <p>
        With none, the checks run in your process and are kept on this machine. In production, set the
        two variables:
      </p>
      <Code lang="bash">{`export AGENTFOX_URL=https://…
export AGENTFOX_API_KEY=nom_api_…`}</Code>

      <h2 id="what-is-sent">What auto() sends to your account</h2>
      <p>
        Only with a key. Each check is one HTTPS request to your account&apos;s gateway
        (<code>/v1/guard/input</code>, <code>/v1/guard/output</code>,{" "}
        <code>/v1/guard/tool_call</code>), with the key in the <code>Authorization</code> header:
      </p>
      <ul>
        <li>
          <strong>Every request:</strong> the agent&apos;s name, the environment, and the session
          id and <code>intent</code> if you passed them.
        </li>
        <li>
          <strong>Before a model call:</strong> the text of each message that is new since the
          model last answered (the user&apos;s turn and any tool results), each marked as coming
          from the user or from a tool.
        </li>
        <li>
          <strong>After it:</strong> the model&apos;s reply text, the model name and the token
          counts.
        </li>
        <li>
          <strong>Each tool call:</strong> the tool&apos;s name and its arguments, and what the
          tool returned.
        </li>
      </ul>
      <p>
        That text is sent as it is: nothing is masked before it leaves your process, because the
        checks need to read it. Not sent: your source code, environment variables, files, or your
        model provider&apos;s API key. On the account, a run&apos;s one-line summary is masked,
        detector matches are kept as a type, a position and a masked sample, and a call held for a
        person keeps its arguments so they can decide. <strong>Settings → Retention</strong> sets
        how long runs are kept. The full account is on the{" "}
        <Link href="/privacy">privacy page</Link>. Without a key, nothing is sent to AgentFox.
      </p>

      <h2 id="modes">Observe or enforce</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th><code>mode</code></th>
            <th>What it stops</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>&quot;observe&quot;</code></td>
            <td>Nothing. What would have been stopped is recorded. Use it first.</td>
          </tr>
          <tr>
            <td><code>&quot;policy&quot;</code> (default)</td>
            <td>What your rules in Block stop, a stopped agent, and a budget cap. Use it in production.</td>
          </tr>
          <tr>
            <td><code>&quot;enforce&quot;</code></td>
            <td>Anything a rule would stop, even one still in Watch. Use it in tests and CI.</td>
          </tr>
        </tbody>
      </table></div>
      <p>
        A stopped call raises <code>agentfox.Blocked</code>. A refused LangChain tool hands the agent
        the refusal as the tool&apos;s result instead, and the run carries on.
      </p>

      <h2 id="frameworks">What it covers</h2>
      <ul>
        <li>
          <strong>Patched:</strong> <code>openai</code> chat completions and the Responses API,{" "}
          <code>anthropic</code> messages, <code>litellm</code>, LangChain chat models and tools,
          and CrewAI tools. Sync, async and streamed.
        </li>
        <li>
          <strong>LangChain, LangGraph, CrewAI, LlamaIndex, AutoGen, the OpenAI Agents SDK:</strong>{" "}
          covered through the client they call the model with. LangChain and CrewAI tools are also
          checked where they run, so a CrewAI agent&apos;s text tool calls (&quot;Action:
          ...&quot;) are checked too. For checks on graph nodes, see{" "}
          <Link href="/docs/connect/langgraph">LangGraph</Link>.
        </li>
        <li>
          <strong>Not covered:</strong> a tool your code calls without the model asking (LangChain
          and CrewAI tools excepted), and other processes. Tools OpenAI hosts (web search, file
          search, code interpreter) are recorded, not stopped: they ran before the response came
          back.
        </li>
      </ul>

      <div id="openai-agents" />
      <Callout kind="note" title="OpenAI Agents SDK">
        <p>
          The Agents SDK calls the model through the Responses API, which <code>auto()</code>{" "}
          patches: every model call, each tool call the model asks for (before the SDK runs it) and
          each tool result fed back are checked, with nothing else added. A refused tool call raises{" "}
          <code>agentfox.Blocked</code> out of <code>Runner.run</code>. If you would rather the
          refusal went back to the model as the tool&apos;s answer, so the run carries on, use{" "}
          <code>govern()</code> instead, once, after you build your agents (
          <code>pip install &quot;agentfox[openai-agents]&quot;</code>):
        </p>
        <Code lang="python">{`import os
from agentfox.frameworks.sdk import AgentFox
from agentfox.frameworks.openai_agents import govern

fox = AgentFox("support-bot", base_url=os.environ["AGENTFOX_URL"],
               api_key=os.environ["AGENTFOX_API_KEY"])
govern(fox, triage_agent)  # its hand-offs and tools too`}</Code>
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
            <td>Nothing patched</td>
            <td>None of the libraries above is installed in this Python. Check the virtual environment.</td>
          </tr>
          <tr>
            <td>Nothing on Activity</td>
            <td>
              <code>auto()</code> ran after the first model call, or no <a href="#key">key</a> was
              found.
            </td>
          </tr>
          <tr>
            <td>Every tool call is refused in enforce mode</td>
            <td>
              Give the agent its tools (<Link href="/docs/govern">Tool access</Link>), or use the
              default mode.
            </td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: "/docs/govern", label: "Tool access", why: "which tools the agent may call" },
          { href: "/docs/protect", label: "Guardrails", why: "switch rules from Watch to Block" },
          { href: "/docs/reference/python", label: "Python SDK reference", why: "every auto() option, Blocked, FastAPI" },
        ]}
      />
    </article>
  );
}
