import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Step, Steps } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "LangGraph",
  description:
    "Guard the retrieval, model and tool nodes of a LangGraph graph with AgentFoxGuard, and pause the graph when a call needs a person's approval.",
  path: "/docs/connect/langgraph",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>LangGraph</h1>
      <p className="docs-lede">
        Check what each node of your graph reads, says and does, and pause the graph when a tool call
        needs a person.
      </p>

      <h2>Before you start</h2>
      <ul>
        <li>
          If your model node calls a LangChain chat model,{" "}
          <Link href="/docs/connect/python">agentfox.auto()</Link> already checks that call and its
          tool calls. Use this page to add checks on retrieval and on tool nodes.
        </li>
      </ul>

      <Steps>
        <Step title="Install">
          <Code>{`pip install "agentfox[langgraph]"`}</Code>
        </Step>

        <Step title="Wrap your nodes">
          <Code lang="python" title="graph.py">{`from agentfox.frameworks.langgraph import AgentFoxGuard

guard = AgentFoxGuard(agent="research-bot", intent="Answer from the knowledge base.")

@guard.retrieval_node      # checks retrieved text for planted instructions
def retrieve(state): ...

@guard.model_node          # checks the messages going in and the reply coming out
def model(state): ...

@guard.tool_node(tool="tickets.create")   # checks the call before the body runs
def file_ticket(state): ...`}</Code>
        </Step>

        <Step title="Add the guard's key to your state">
          <p>
            The guard keeps the trace id and what earlier nodes read under <code>__agentfox__</code>.
            Declare it, or LangGraph drops it between nodes.
          </p>
          <Code lang="python">{`class State(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    __agentfox__: Annotated[dict, lambda old, new: {**(old or {}), **(new or {})}]`}</Code>
        </Step>

        <Step title="Give the agent its tool">
          <p>
            The first run registers the agent and refuses <code>tickets.create</code>, because nobody
            has said what it does or that the agent may call it.
          </p>
          <Code>{`agentfox declare tool tickets.create --impact write
agentfox permit grant research-bot tickets.create --yes`}</Code>
        </Step>

        <Step title="Ask a person first, if you want">
          <p>
            Grant with <code>--requires-approval</code> and the graph pauses at that node. Compile it
            with a checkpointer, then resume once someone approves in{" "}
            <Link href="/docs/govern/approvals">Approvals</Link>:
          </p>
          <Code lang="python">{`out = graph.invoke(inputs, config)          # paused: out["__interrupt__"]
out = graph.invoke(Command(resume={"approved": True}), config)`}</Code>
        </Step>
      </Steps>

      <Callout kind="note" title="Only an approval runs the tool">
        Only <code>{`{"approved": True}`}</code> (or <code>True</code>) runs it. Anything else raises{" "}
        <code>PolicyViolation</code>. Add the paused <code>approval_id</code> to the resume value and
        the guard also checks that the approval was granted.
      </Callout>

      <h2>What happens on a refusal</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>Verdict</th>
            <th>What the node does</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Block</td>
            <td>Raises <code>agentfox.PolicyViolation</code>. The node body does not run.</td>
          </tr>
          <tr>
            <td>Needs approval</td>
            <td>
              Calls LangGraph&apos;s <code>interrupt()</code> with the <code>approval_id</code> and the
              reason. Pass <code>raise_on_escalate=False</code> to keep going instead.
            </td>
          </tr>
          <tr>
            <td>Redact</td>
            <td>A model node&apos;s reply is rewritten with the personal data or secret hidden.</td>
          </tr>
        </tbody>
      </table></div>

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
            <td><code>capability.denied</code></td>
            <td>Grant the tool to the agent (step 4).</td>
          </tr>
          <tr>
            <td>A limit refuses with &quot;this call passed None&quot;</td>
            <td>
              The tool node found no arguments. Put the model&apos;s tool call in{" "}
              <code>state[&quot;messages&quot;]</code>, or pass <code>arguments=</code>.
            </td>
          </tr>
          <tr>
            <td>A paused run cannot be resumed</td>
            <td>Compile with a checkpointer and pass the same <code>thread_id</code>.</td>
          </tr>
          <tr>
            <td>No trace id in the result</td>
            <td>Declare <code>__agentfox__</code> in your state (step 3).</td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: "/docs/govern", label: "Tool access", why: "limits on a tool's arguments" },
          { href: "/docs/reference/python", label: "Python SDK reference", why: "every AgentFoxGuard option" },
        ]}
      />
    </article>
  );
}
