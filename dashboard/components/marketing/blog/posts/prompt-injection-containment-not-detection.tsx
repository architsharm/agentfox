import Link from "next/link";

import type { TocItem } from "@/components/marketing/blog/article";
import { Diagram, Figure, InlineCTA, Stat, StatRow, Takeaways, type FaqItem } from "@/components/marketing/blog/blocks";
import { Code, Output } from "@/components/docs/blocks";

export const toc: TocItem[] = [
  { id: "detection-loses", label: "Why detection loses" },
  { id: "change-the-question", label: "Ask a different question" },
  { id: "three-checks", label: "Three checks on every call" },
  { id: "in-code", label: "What it looks like in code" },
  { id: "measured", label: "What we measured" },
  { id: "the-cost", label: "The cost, honestly" },
  { id: "where-to-start", label: "Where to start" },
];

export const faq: FaqItem[] = [
  {
    q: "Can prompt injection be fully prevented?",
    a: "Not by detection alone. Published work on adaptive attacks reports high success rates against every defence it tested once the attacker can iterate, and our own detector is no exception. What can be prevented is the damaging action: a tool call the agent was never granted, or an irreversible call whose arguments came from untrusted content.",
  },
  {
    q: "What is the lethal trifecta?",
    a: "Simon Willison's term for an agent that has access to private data, is exposed to content an outsider can write, and has a way to send data out. Any two are manageable. All three in one agent means a single injected instruction can exfiltrate data. AgentFox's repository scan reports it as a critical finding.",
  },
  {
    q: "What is argument provenance or taint tracking for AI agents?",
    a: "Recording where each tool-call argument came from: your own code, the user, a retrieved document, another tool's output, a sub-agent or memory. A policy can then refuse or escalate an irreversible call whose arguments came from untrusted content, whatever those arguments say.",
  },
  {
    q: "Does containment replace prompt injection detection?",
    a: "No. Detection still raises the attacker's cost and catches the obvious cases early. Containment is what still holds when detection misses, which is why we measure it with every detector switched off.",
  },
  {
    q: "What is the downside of taint-based containment?",
    a: "It escalates legitimate work. In our AgentDojo replay, session-level taint contained every attack pair but let only about a quarter of benign tasks run without a human. Per-argument taint and read-only exemptions improve that, at the cost of missing some attacks. The trade-off is published on the benchmark page.",
  },
];

export function Body() {
  return (
    <>
      <Takeaways
        items={[
          "No detector catches every prompt injection, and an attacker who can retry will find the gap. Plan for the miss.",
          "Bound what the agent can do instead: explicit grants, an impact tier per tool, and the provenance of every argument.",
          "With every detector switched off, containment still stopped all eight attack scenarios in our benchmark. It also escalates real work, and we publish that too.",
        ]}
      />

      <h2 id="detection-loses">Why prompt injection detection loses</h2>
      <p>
        Prompt injection works because a language model cannot reliably tell instructions it
        should follow from text it should only read. A retrieved web page, a support ticket or
        a tool result can all carry the sentence that changes what the agent does next. The
        natural response is to detect that sentence: a classifier, a regex list, a second
        model that judges the first.
      </p>
      <p>
        Detection is worth having. It is also a contest the defender loses slowly. The attacker
        gets to see the refusal and try again. Researchers testing twelve published defences
        against adaptive attacks reported success rates above 90% once the attacker could
        iterate (Nasr, Carlini, Schulhoff et al., <em>The Attacker Moves Second</em>, 2025). We
        ran the same kind of test against our own detector. An attacker who adapts gets
        73% of the attacks we catch through within 50 attempts. And with the default
        install&apos;s heuristic alone, held-out injection recall is 26.7% at 100% precision
        on the deepset split. That is a speed bump, not a wall.
      </p>
      <p>
        If your agent can send email, move money or delete files, the question is not whether
        an injection gets past the detector. It is what happens when it does.
      </p>

      <h2 id="change-the-question">Ask a different question</h2>
      <p>
        Detection asks: <em>does this text look like an attack?</em> That question has no
        stable answer. Containment asks three questions that do:
      </p>
      <ol>
        <li>
          <strong>Is this agent allowed to call this tool, with these arguments?</strong>{" "}
          Written down before the agent runs. A prompt cannot add to it.
        </li>
        <li>
          <strong>How bad is this tool if it is misused?</strong> Read, write, high impact or
          irreversible.
        </li>
        <li>
          <strong>Where did these argument values come from?</strong> The user, your own code,
          or a document the agent just read.
        </li>
      </ol>
      <p>
        None of them depends on recognising the payload. An email to an attacker&apos;s address
        is refused because the address arrived in untrusted content and the tool is
        irreversible, not because anything read the instruction and found it suspicious.
      </p>

      <h2 id="three-checks">Three checks on every tool call</h2>
      <Diagram
        label="The three containment checks on a tool call"
        caption="Every tool call meets three checks that read declarations, not text. A miss by the detector upstream changes none of them."
      >
        <svg className="dg" viewBox="0 0 780 250" xmlns="http://www.w3.org/2000/svg">
          <rect x="10" y="95" width="150" height="60" rx="10" className="dg-box" />
          <text x="85" y="120" textAnchor="middle" className="dg-strong">email.send</text>
          <text x="85" y="140" textAnchor="middle" className="dg-mono">to=records@exfil…</text>

          <rect x="205" y="20" width="190" height="62" rx="10" className="dg-box-accent" />
          <text x="300" y="45" textAnchor="middle" className="dg-strong">1. Grant</text>
          <text x="300" y="65" textAnchor="middle" className="dg-small">to must match @example.com</text>

          <rect x="205" y="94" width="190" height="62" rx="10" className="dg-box-accent" />
          <text x="300" y="119" textAnchor="middle" className="dg-strong">2. Impact tier</text>
          <text x="300" y="139" textAnchor="middle" className="dg-small">email.send = irreversible</text>

          <rect x="205" y="168" width="190" height="62" rx="10" className="dg-box-accent" />
          <text x="300" y="193" textAnchor="middle" className="dg-strong">3. Provenance</text>
          <text x="300" y="213" textAnchor="middle" className="dg-small">arg came from a fetched page</text>

          <path d="M160 125 L205 51" className="dg-line" />
          <path d="M160 125 L205 125" className="dg-line" />
          <path d="M160 125 L205 199" className="dg-line" />

          <path d="M395 51 L470 115" className="dg-line-stop" />
          <path d="M395 125 L470 125" className="dg-line-stop" />
          <path d="M395 199 L470 135" className="dg-line-stop" />

          <rect x="470" y="70" width="300" height="110" rx="10" className="dg-box-stop" />
          <text x="620" y="98" textAnchor="middle" className="dg-strong dg-t-stop">Refused, three reasons</text>
          <text x="620" y="122" textAnchor="middle" className="dg-mono">capability.constraint_violated</text>
          <text x="620" y="142" textAnchor="middle" className="dg-mono">taint.irreversible_tool</text>
          <text x="620" y="162" textAnchor="middle" className="dg-mono">composition.escalation</text>
        </svg>
      </Diagram>

      <h3>1. Capability grants: default deny</h3>
      <p>
        Each agent holds explicit <Link href="/grants">capability grants</Link>: which tools it
        may call, with limits on the arguments (<code>amount</code> below 1000,{" "}
        <code>to</code> matching your own domain), how tainted the inputs may be, whether a
        person must approve, and when the grant expires. Anything not granted is refused. That
        is not a policy setting you can forget to turn on; a call with no grant is refused
        whatever mode the policy pack is in.
      </p>
      <Figure
        src="/product/refusal.png"
        alt="A payments.transfer call blocked with rule capability.denied: no capability grants this agent the requested tool and action."
        caption={
          <>
            A transfer the agent was never granted, refused under{" "}
            <code>capability.denied</code>. No detector was involved.
          </>
        }
        width={1600}
        height={670}
      />

      <h3>2. Impact tiers</h3>
      <p>
        Each tool is declared <code>read</code>, <code>write</code>,{" "}
        <code>high_impact</code> or <code>irreversible</code>. A tool seen in traffic before
        anyone declared it gets an inferred tier from its name (send, delete, transfer and
        deploy read as irreversible), and an operator confirms or corrects it. The tier is what
        decides how much scrutiny a call gets.
      </p>

      <h3>3. Argument provenance</h3>
      <p>
        Every argument carries where it came from: none (a constant in your code),{" "}
        <code>user</code>, <code>retrieved</code>, <code>tool_result</code>,{" "}
        <code>subagent</code> or <code>memory</code>, in rising order of risk. An irreversible
        tool called with an argument that originated in untrusted content is escalated to a
        person. A lower-impact tool&apos;s output flowing into a higher-impact tool is blocked
        as <code>composition.escalation</code>. This is the check that handles the{" "}
        <strong>lethal trifecta</strong>, Simon Willison&apos;s name for an agent that has
        private data, reads untrusted content and can send data out. Our{" "}
        <Link href="/docs/guides/scan-a-repo">repository scan</Link> flags any agent that holds
        all three.
      </p>

      <h2 id="in-code">What it looks like in code</h2>
      <p>
        Declare the tool and grant it once, from the command line or in review:
      </p>
      <Code>{`agentfox declare tool email.send --impact irreversible
agentfox permit grant support-triage email.send --limit 'to:matches=@example\\.com$' --yes`}</Code>
      <p>
        Then guard the calls in a session, telling it what the agent read along the way. This
        is adapted from the{" "}
        <Link href="/docs/guides/contain-tool-calls">contain tool calls guide</Link>:
      </p>
      <Code lang="python" title="triage.py">{`from agentfox import AgentFox, PolicyViolation

fox = AgentFox(agent="support-triage", environment="development")

with fox.session(intent="Triage a support ticket and reply to the customer.") as s:
    s.guard_tool("web.fetch", {"url": url})
    page = s.tool_result(web_fetch(url), tool="web.fetch")   # untrusted from here on

    # The page told the model to mail the records somewhere else.
    args = {"to": "records@exfil.example", "subject": "Your ticket", "body": "..."}
    try:
        s.guard_tool("email.send", args)
    except PolicyViolation as exc:
        print([r["rule_id"] for r in exc.result.rules_fired])`}</Code>
      <Output>{`['taint.irreversible_tool', 'capability.constraint_violated', 'composition.escalation']`}</Output>
      <p>
        Three independent reasons stop the call, and none of them needed to recognise the
        instruction in the page. If you would rather not touch call sites,{" "}
        <Link href="/docs/guides/python-auto">
          <code>agentfox.auto()</code>
        </Link>{" "}
        patches the supported model SDKs and infers provenance by matching values. One
        warning: <code>@fox.tool</code> defaults to <code>impact=&quot;read&quot;</code>, so a
        destructive tool you forget to declare is treated as a read.
      </p>

      <h2 id="measured">What we measured</h2>
      <p>
        A claim like this is only worth something if you can check it, so the containment
        benchmark runs with <strong>every detector switched off</strong>. Eight constructed
        scenarios, one per containment mechanism, with a compromised agent as the premise:
        8/8 attacks contained with zero detector signal, and 4/4 legitimate calls still allowed.
      </p>
      <StatRow>
        <Stat value="8/8" label="attack scenarios contained with every detector off" source="Containment benchmark, detectors disabled" />
        <Stat value="4/4" label="legitimate calls still allowed in the same run" source="Containment benchmark, detectors disabled" />
        <Stat value="38/38" label="adaptive bypasses of the detector, still contained at the action" source="Adaptive attack benchmark" />
      </StatRow>
      <p>
        The second test is larger and less flattering. We replayed AgentDojo (v1.2.2, 97 user
        tasks) through the enforcement path with provenance inferred from the tool outputs that
        actually ran and detectors off. On AgentDojo, session-level taint contained 588 of 588
        attack pairs. For comparison, grants and impact tiers on their own contain 61 of 702
        attacker write calls: the grant check is the floor, and provenance does most of the
        work. Of the detector bypasses an adaptive attacker found, 38/38 of those bypasses still
        contained at the action.
      </p>
      <Figure
        src="/blog/benchmark-containment.png"
        alt="The AgentFox benchmark page: containment results with detectors disabled, and the AgentDojo replay with its utility cost."
        caption={
          <>
            The full write-up, including what each number does not show, is on the{" "}
            <Link href="/benchmark">benchmark page</Link>.
          </>
        }
        width={1600}
        height={900}
      />

      <InlineCTA
        title="Read the numbers, including the losses"
        body="Five benchmarks with their result files committed. A nightly job fails if a published number no longer matches its source."
        href="/benchmark"
        label="See the benchmarks"
        secondary={{ href: "/coverage", label: "Coverage and gaps" }}
      />

      <h2 id="the-cost">The cost, honestly</h2>
      <p>
        Containment is not free, and the cost is real work getting stopped. With session-level
        taint, only 24 of 97 benign tasks ran without escalating to a human: once an agent has
        read anything untrusted, every irreversible call after it goes to a person. Per-argument
        taint lets far more work through but misses short values and values embedded inside a
        larger argument. Exempting read-only tools helps further, and we designed that
        exemption after seeing the results, which the benchmark page says.
      </p>
      <p>Three other limits are worth stating plainly:</p>
      <ul>
        <li>
          <strong>It is only as good as your declarations.</strong> Declare a destructive tool
          as <code>read</code> and the check believes you.
        </li>
        <li>
          <strong>An escalation is not a block.</strong> The replay counts escalation as
          containment. A person who approves the escalated call lets the attack through, which
          is why <Link href="/docs/guides/approvals">approvals</Link> show the provenance.
        </li>
        <li>
          <strong>A shell is one tool.</strong> For a coding agent, <code>ls</code> and{" "}
          <code>rm</code> are the same tool, so the argument parsing has to do the work. That
          is the subject of <Link href="/blog/claude-code-hooks-security">the hooks post</Link>.
        </li>
      </ul>

      <h2 id="where-to-start">Where to start</h2>
      <ol>
        <li>
          Scan the repository to find agents that hold the lethal trifecta:{" "}
          <code>agentfox scan</code>.
        </li>
        <li>Declare an impact tier for every tool that writes, and every tool that cannot be undone.</li>
        <li>Grant per agent, with argument limits, and let default deny refuse the rest.</li>
        <li>Turn on provenance and run in observe mode first. Read what would have been escalated.</li>
        <li>Keep detection on. It is a speed bump, and speed bumps are useful.</li>
      </ol>
      <p>
        Detection-side techniques are covered in{" "}
        <Link href="/blog/hidden-indirect-prompt-injection">
          three injections a keyword filter misses
        </Link>
        .
      </p>
    </>
  );
}
