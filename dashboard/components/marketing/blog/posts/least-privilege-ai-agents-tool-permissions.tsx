import Link from "next/link";

import type { TocItem } from "@/components/marketing/blog/article";
import { InlineCTA, Takeaways, type FaqItem } from "@/components/marketing/blog/blocks";
import { Code } from "@/components/docs/blocks";

export const toc: TocItem[] = [
  { id: "wrong-unit", label: "The model is the wrong unit of trust" },
  { id: "grant-per-agent", label: "One grant per agent, per tool" },
  { id: "draft-from-traffic", label: "Draft the grants from real traffic" },
  { id: "limit-arguments", label: "Limit the arguments, not just the tool" },
  { id: "impact-and-provenance", label: "Impact tiers and where a value came from" },
  { id: "approvals", label: "Approval for what cannot be undone" },
  { id: "cost", label: "What it costs, measured" },
  { id: "checklist", label: "A checklist" },
];

export const faq: FaqItem[] = [
  {
    q: "Isn't the model's own judgement enough to avoid misusing a tool?",
    a: "Not against an attacker. The model decides what to call based on text it reads, and that text can be written by anyone whose document, web page or tool output the agent sees. Least privilege puts the decision about what may be called with a person, before the agent runs.",
  },
  {
    q: "Do I have to write the grants by hand?",
    a: "No. Run the agent in observe mode first. Every call it makes to a tool it was not granted is listed as tried but not allowed, and you allow each one that should have been, or all of them. Argument limits are then added where the risk is.",
  },
  {
    q: "What about agents that hand work to other agents?",
    a: "A call is checked under the agent that makes it, and an agent that delegates cannot hand on more than it holds. A triage agent that reaches a refund tool only through a refunds agent is tested, and governed, through that path.",
  },
];

export function Body() {
  return (
    <>
      <Takeaways
        items={[
          "Least privilege for AI agents means a person decides, per agent and per tool, what may be called and with what values, before the model ever reads untrusted text.",
          "Draft the grants from observed traffic, then add limits on arguments, impact tiers and provenance rules, and require approval for anything irreversible.",
          "It has a cost we have measured: with default grants, three in four normal AgentDojo tasks needed a person to approve a step. Tune the grants, and the cost drops.",
        ]}
      />

      <h2 id="wrong-unit">The model is the wrong unit of trust</h2>
      <p>
        <strong>Least privilege for AI agents</strong> is the same idea as for any other principal: give
        it the access its job needs and nothing more. The difference is where the decisions are made.
        An agent decides which tool to call by reading text, and some of that text was written by
        strangers: a web page, a customer&apos;s email, the result of another tool. Whoever writes that
        text can, some of the time, choose the call. So &ldquo;the model would never do that&rdquo; is
        not a permission model. The permission has to sit outside the model, where the text cannot
        reach it.
      </p>
      <p>
        That is also the practical answer to the{" "}
        <Link href="/blog/lethal-trifecta-ai-agents">lethal trifecta</Link>: an agent with private
        data, untrusted content and a way to send data out. You rarely get to remove one of the three.
        You can decide, per agent, exactly which sending tools exist and with which arguments.
      </p>

      <h2 id="grant-per-agent">One grant per agent, per tool</h2>
      <p>
        The unit is an agent and a tool. A support agent holds grants for the order lookup and the
        ticket update; it holds nothing for refunds, so a refund call is refused before it reaches the
        payment system, whatever the model was told. A tool nobody granted is not a permission that
        was forgotten; it is a refusal, and it is recorded as one.
      </p>
      <Code lang="bash" title="Granting a tool to one agent">{`agentfox permit grant support-triage orders.lookup --yes
agentfox permit grant support-triage tickets.update --yes
# MCP tools are named per server, so two servers' search tools stay apart
agentfox permit grant support-triage mcp:github/search_issues --yes`}</Code>
      <p>
        Grant a whole server or a wildcard only when every tool behind it should be callable. The
        shortcut is where the privilege creeps back in.
      </p>

      <h2 id="draft-from-traffic">Draft the grants from real traffic</h2>
      <p>
        Nobody knows an agent&apos;s real tool use from its code alone. Run it in observe mode first:
        every call is checked and recorded, nothing is blocked, and the agent&apos;s page lists the
        tools it tried that nobody allowed. Allow each one that should have been, or all of them, and
        the draft is done from what the agent actually does rather than what someone thought it did.
        The scan of the repository fills in the tools it found but nobody allowed yet, for the ones
        that have not been exercised. The walkthrough is on the{" "}
        <Link href="/docs/govern">tool access page</Link>.
      </p>

      <h2 id="limit-arguments">Limit the arguments, not just the tool</h2>
      <p>
        A grant for <code>payments.transfer</code> says the agent may move money. A limit says how
        much. Most real damage is a legitimate tool with an illegitimate value: a refund for the full
        balance, a query over every row, a message to an address the customer never gave. Each grant
        takes constraints on arguments, and a call outside them is refused with the reason spelled out.
      </p>
      <Code lang="json" title="A refusal from a limit, as the audit log records it" copy={false}>{`{
  "tool": "payments.transfer",
  "verdict": "block",
  "rule_id": "capability.constraint_violated",
  "reason": "agent:payments-ops holds a grant for 'payments.transfer', so this is not a missing permission. The grant allows amount below 1000, but this call passed 25000."
}`}</Code>

      <h2 id="impact-and-provenance">Impact tiers and where a value came from</h2>
      <p>
        Two more dimensions keep the grants short. The first is impact: every tool is read-only,
        writes, high impact or irreversible, guessed from its name and description and worth checking
        by hand, because a tool that moves money but is marked read-only is not protected. The second
        is provenance: where each argument value came from. A person typed it, or it came from a
        retrieved document, another tool&apos;s output, or another agent. The two combine into one
        table.
      </p>
      <ul>
        <li>Read-only tools go through.</li>
        <li>A write is held for approval if the value came from another tool&apos;s output or worse.</li>
        <li>High-impact and irreversible tools are held unless the user typed the value.</li>
        <li>
          A value copied out of a lower-impact tool&apos;s output into a higher-impact tool is refused
          outright, because that is the shape of an escalation.
        </li>
      </ul>
      <p>
        If a flow like that is intended, say an address from your own CRM, you mark that tool&apos;s
        output trusted, once, and the rule stands for everything else. This is the mechanism behind the
        result in{" "}
        <Link href="/blog/prompt-injection-containment-not-detection">
          detection is a speed bump
        </Link>
        : on AgentDojo&apos;s 588 attacks the containment holds with every detector off, because the
        attacks need a value from untrusted text to reach a tool that acts.
      </p>

      <InlineCTA
        title="Tool access, step by step"
        body="See what an agent may call, allow what it tried, add a limit, require approval. Every change is written to the audit log."
        href="/docs/govern"
        label="Read the guide"
        secondary={{ href: "/docs/concepts", label: "Core concepts" }}
      />

      <h2 id="approvals">Approval for what cannot be undone</h2>
      <p>
        Some calls should wait for a person every time: a transfer, a deletion, a message to a
        customer. Set the grant to ask first, and the call waits on the approvals queue until someone
        approves or denies it, bound to the exact arguments, so an approval cannot be reused for a
        different amount. Approval is the control of last resort, not the first: a queue that gets
        a hundred requests a day gets rubber-stamped.
      </p>

      <h2 id="cost">What it costs, measured</h2>
      <p>
        Least privilege is not free, and the honest number is on our{" "}
        <Link href="/benchmark">benchmark page</Link>: with the default grants, AgentFox finished 24 of
        AgentDojo&apos;s 97 normal tasks without a person approving a step, where LLM Guard&apos;s
        scanner finished 42. The attacks it stopped went 0 of 588 against 86. That is the trade. It
        moves with the grants: wider grants and trusted sources recover tasks, and the benchmark page
        shows the settings and what each one costs in attacks stopped.
      </p>

      <h2 id="checklist">A checklist</h2>
      <ol>
        <li>Every agent has a named identity and its own grants. No shared &ldquo;the agent&rdquo;.</li>
        <li>Grants were drafted from observed traffic, then reviewed by a person.</li>
        <li>No wildcard grant on a server or tool family that includes a write.</li>
        <li>Every tool that moves money, deletes or sends has an impact tier set by hand.</li>
        <li>Argument limits exist on every tool where the value is the risk.</li>
        <li>Irreversible tools require approval, bound to the exact arguments.</li>
        <li>Values from documents and tool output cannot reach high-impact tools without a person.</li>
        <li>Every refusal is in the audit log with its reason, and someone reads the refusals weekly.</li>
      </ol>
    </>
  );
}
