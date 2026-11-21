import Link from "next/link";

import type { TocItem } from "@/components/marketing/blog/article";
import { InlineCTA, Takeaways, type FaqItem } from "@/components/marketing/blog/blocks";
import { Code } from "@/components/docs/blocks";

export const toc: TocItem[] = [
  { id: "what-they-are-asking", label: "What the reviewer is really asking" },
  { id: "weak-answers", label: "The answers that fail the review" },
  { id: "five-parts", label: "The five parts of a strong answer" },
  { id: "template", label: "A template you can paste" },
  { id: "evidence", label: "The evidence to attach" },
  { id: "owasp", label: "If they ask about OWASP" },
];

export const faq: FaqItem[] = [
  {
    q: "Can we answer that prompt injection is prevented?",
    a: "No. Against an attacker who adapts, published detectors fail more than 90% of the time, and AgentFox's own detector is beaten within 50 attempts. A reviewer who knows the field will discount any answer that claims prevention. Say what is detected, what is contained when detection fails, and what is recorded.",
  },
  {
    q: "Is a system prompt telling the model to ignore instructions in documents a control?",
    a: "It is a mitigation with no measured rate, and most questionnaires now ask for the rate. Keep it, but do not list it as the control that answers the question.",
  },
  {
    q: "What if our agent has no tools?",
    a: "Then prompt injection can only change what the model says, not what it does, and the answer is shorter: detection on inputs and outputs, with the measured catch rate and false-alarm rate, and a log of what was flagged. Most of this post is about agents that act.",
  },
];

export function Body() {
  return (
    <>
      <Takeaways
        items={[
          "The question is not whether you detect prompt injection. It is what happens when detection misses, because it will.",
          "A strong answer has five parts: detection with its measured rates, containment at the tool call, least privilege, an audit trail someone else can verify, and tests that run on every change.",
          "Attach numbers a reviewer can check. Ours are public: 68.3% of held-out injections caught, 11.5% false alarms, and 0 of 588 AgentDojo attacks through with every detector switched off.",
        ]}
      />

      <h2 id="what-they-are-asking">What the reviewer is really asking</h2>
      <p>
        <strong>How do you prevent prompt injection?</strong> is on most security questionnaires that
        mention AI now, usually one line under application security. The person reading your answer has
        read the OWASP lists and probably a write-up or two of an agent that was talked into sending
        data somewhere it should not have gone. They are not asking whether you have heard of the
        attack. They are asking what your agent can still do after an attack has worked, and whether
        you would know.
      </p>
      <p>
        That reframing is the whole post. Prompt injection cannot be prevented in the sense a
        questionnaire usually means: against an attacker who adapts, published detectors fail more than
        90% of the time, and ours is beaten within 50 attempts in our own{" "}
        <Link href="/benchmark">benchmark</Link>. An answer that claims prevention tells a competent
        reviewer that you have not measured it.
      </p>

      <h2 id="weak-answers">The answers that fail the review</h2>
      <ul>
        <li>
          <strong>&ldquo;Our system prompt instructs the model to ignore instructions in retrieved
          content.&rdquo;</strong> A mitigation with no measured rate. It will be read as having no
          control.
        </li>
        <li>
          <strong>&ldquo;We use a prompt injection detector.&rdquo;</strong> Better, but it invites the
          next question: at what catch rate, at what false-alarm rate, and what happens to the one in
          three it misses? If you cannot answer, the detector is not a control either.
        </li>
        <li>
          <strong>&ldquo;Our model provider handles it.&rdquo;</strong> The provider handles the model.
          Your tools, your data and your customer&apos;s account are yours.
        </li>
      </ul>

      <h2 id="five-parts">The five parts of a strong answer</h2>
      <p>
        Each part answers a question the reviewer would otherwise ask next. Write them in this order.
      </p>
      <ol>
        <li>
          <strong>Detection, with rates.</strong> What scans inputs, retrieved documents and tool
          results, and how well. Give the held-out catch rate and the false-alarm rate on harmless
          look-alikes, and say what the numbers were measured on. If you use AgentFox&apos;s defaults,
          those are 68.3% and 11.5% on the sets described on the{" "}
          <Link href="/benchmark">benchmark page</Link>, next to the numbers for the other detectors
          we tested.
        </li>
        <li>
          <strong>Containment when detection misses.</strong> This is the part most answers lack.
          Each agent holds a grant for the tools it may call and the arguments it may pass; a value
          that arrived from a document or a tool result cannot reach a privileged parameter; a call
          outside the grant is refused whether or not anything flagged the text. On AgentDojo&apos;s
          588 attacks against a tool-using agent, that holds with every detector switched off. The
          argument is in{" "}
          <Link href="/blog/prompt-injection-containment-not-detection">
            Prompt injection detection is a speed bump
          </Link>
          .
        </li>
        <li>
          <strong>Least privilege.</strong> The agent can only reach the tools it was granted, with
          limits on arguments (a refund below a threshold, a query touching fewer than so many rows)
          and approval required for anything irreversible. The reviewer wants to hear that the blast
          radius was decided by a person, not by the model.
        </li>
        <li>
          <strong>An audit trail someone else can verify.</strong> Every allowed and refused call,
          with the rule that fired and the policy version, in a hash-chained log with a standalone
          verifier. The point is that the reviewer&apos;s own team could check it without trusting you
          or your vendor; see{" "}
          <Link href="/blog/ai-agent-audit-trail">An AI agent audit trail your auditor can check</Link>
          .
        </li>
        <li>
          <strong>Tests that run on every change.</strong> An attack library run against the agent
          in CI, failing the build when an attack gets through, and probes against the live agent on
          a schedule. Say how often and what the last run showed.
        </li>
      </ol>

      <InlineCTA
        title="The numbers to quote, with their limits"
        body="Every figure in this post has a script, a results file and a list of what it does not show."
        href="/benchmark"
        label="See the benchmarks"
        secondary={{ href: "/docs/reference/owasp", label: "The OWASP mapping" }}
      />

      <h2 id="template">A template you can paste</h2>
      <p>
        Replace the bracketed parts with your own facts. Leave out any sentence you cannot back with a
        number or a document; a shorter true answer beats a longer one with a claim in it.
      </p>
      <Code lang="text" title="Questionnaire answer: how do you prevent prompt injection?" copy>{`We treat prompt injection as a certainty rather than a risk to prevent, and control what an injected instruction can achieve.

1. Detection. Inputs, retrieved documents and tool results are scanned by [detector]. On held-out injection prompts it catches [x]% with a [y]% false-alarm rate on harmless look-alikes; the measurement is at [URL].

2. Containment. Each agent holds an explicit grant for the tools it may call and the argument values it may pass. Values that arrived from documents or tool output cannot reach privileged parameters, and any call outside the grant is refused regardless of whether the text was flagged. [On the AgentDojo benchmark this stops 588 of 588 injection attacks with detection disabled.]

3. Least privilege. Tool access is granted per agent, with argument limits [examples] and human approval for irreversible actions [examples].

4. Audit. Every allowed and refused call is written to a hash-chained audit log with the rule that fired and the policy version in force. The log can be verified with a standalone tool without access to our systems.

5. Testing. An attack library runs against the agent in CI and fails the build when an attack succeeds; live probes run [schedule]. Last run: [date, result].`}</Code>

      <h2 id="evidence">The evidence to attach</h2>
      <p>
        Questionnaires are scored on attachments more than prose. Three things close the question:
      </p>
      <ul>
        <li>The benchmark or test report the rates in part 1 come from, with its date.</li>
        <li>
          One audit entry for a refused call, redacted, showing the agent, the tool, the rule and the
          reason. One real entry is worth a page of description.
        </li>
        <li>The CI job definition that runs the attack tests, or its last output.</li>
      </ul>
      <p>
        If you run AgentFox, the first is the <Link href="/benchmark">benchmark page</Link>, the
        second is any entry on the audit page, and the third is the workflow on the{" "}
        <Link href="/docs/test/ci">CI guide</Link>.
      </p>

      <h2 id="owasp">If they ask about OWASP</h2>
      <p>
        Some questionnaires ask the question as &ldquo;how do you address ASI01 and ASI02 of the OWASP
        Top 10 for Agentic Applications&rdquo;. ASI01 is goal hijack, the injection itself; ASI02 is
        tool misuse, what the hijacked agent does. Parts 1 and 2 above map onto them directly, and our{" "}
        <Link href="/docs/reference/owasp">item-by-item mapping</Link> says which is enforced out of
        the box and which is covered in part. Quote that status honestly: a reviewer trusts a vendor
        that says &ldquo;partial&rdquo; where it is partial.
      </p>
    </>
  );
}
