import Link from "next/link";

import type { TocItem } from "@/components/marketing/blog/article";
import { Figure, InlineCTA, Takeaways, type FaqItem } from "@/components/marketing/blog/blocks";

/**
 * Every number here is from the accepted abstract of the IEEE BigData 2026 paper listed on
 * /research, which is fixed once accepted. The paper's table names each system; this post
 * does not, because the per-hook evidence stays private until the maintainers have had time
 * to respond to the reports.
 */
export const toc: TocItem[] = [
  { id: "short", label: "The short answer" },
  { id: "coded", label: "What we coded" },
  { id: "where", label: "Where fail-open sits" },
  { id: "escapes", label: "Six ways a failure escapes control" },
  { id: "ours", label: "The bug in our own guardrail" },
  { id: "ask", label: "What to ask a guardrail vendor" },
];

export const faq: FaqItem[] = [
  {
    q: "What does fail open mean for an AI agent guardrail?",
    a: "When the detector behind the guardrail raises an error or times out, the call it was checking proceeds as if it had passed. Of 16 guardrail systems we coded, 5 do this by default on a detector error, 7 raise the error to the caller, 3 block, and 1 mixes both.",
  },
  {
    q: "Which kinds of guardrail fail open most?",
    a: "Agent hooks, gateways and the integrations inside hubs whose own core fails closed. 7 of 22 NeMo Guardrails integrations and 7 of 52 LiteLLM detector hooks allow the call on a detector error. Detector libraries and framework cores mostly raise or block.",
  },
  {
    q: "Did AgentFox fail open?",
    a: "Yes, in one case: at the commit we coded, a detector that raised was allowed even with fail_mode set to closed, because the switch covered timeouts and not errors. We found it during the study and fixed it; the paper reports it as found.",
  },
  {
    q: "How reliable is the coding?",
    a: "All coding was done by LLM agents, no person checked every row. 27 of the 98 rows were confirmed by fault injection, and a second agent run recoded 19 random rows with a Cohen's kappa of 0.63, which measures run-to-run consistency only.",
  },
];

export function Body() {
  return (
    <>
      <Takeaways
        items={[
          "On a detector error, 5 of 16 guardrail systems let the call proceed by default, 7 raise, 3 block and 1 mixes both.",
          "Fail-open defaults sit in agent hooks, gateways and hub integrations, not in the detector libraries: 7 of 22 NeMo integrations and 7 of 52 LiteLLM hooks allow on error.",
          "Nine systems have a detector path with no time bound at all. One of the fail-open bugs was ours, under a fail mode set to closed, and it is fixed.",
        ]}
      />

      <h2 id="short">The short answer</h2>
      <p>
        A guardrail decides whether a prompt, an output or a tool call may proceed. The question
        this post answers is what it does when it cannot decide: the classifier raises, the
        moderation API times out, the judge returns something that does not parse. A guardrail
        that fails open in that moment is one an attacker only has to make busy. We coded the
        shipped defaults of 16 guardrail libraries, gateways, frameworks and agent hooks and found
        that <strong>on a detector error, 5 let the call proceed, 7 raise to the caller, 3 block
        and 1 mixes both</strong>. The paper, accepted at the Trustworthy and Aligned AI workshop
        of IEEE BigData 2026, is on the <Link href="/research">research page</Link>.
      </p>

      <h2 id="coded">What we coded</h2>
      <p>
        Sixteen systems at pinned commits, 98 rows, with the error case and the timeout case coded
        separately for each detector or integration. Fifteen are open source; Claude Code&apos;s hooks
        were coded from their documentation. All coding was done by LLM agents and no human checked
        every row, which the paper says in its first paragraph. Two checks stand in for that: 27 rows
        were confirmed by fault injection, making the detector fail and watching what the system did,
        and a second agent run recoded 19 random rows with a Cohen&apos;s kappa of 0.63 (95% interval
        0.40 to 0.85), a measure of run-to-run consistency and nothing more.
      </p>

      <h2 id="where">Where fail-open sits</h2>
      <Figure
        src="/blog/guardrail-fail-modes.png"
        alt="Stacked bars of the default on detector error by component: libraries mostly raise, framework cores and gateway cores split between closed and open, NeMo and LiteLLM hub integrations mostly closed with 7 open each, and all four agent hooks open."
        width={690}
        height={470}
        caption="Default on a detector error, by where the component sits. Open means the call proceeds."
      />
      <p>
        The pattern is not by vendor but by layer. Detector libraries mostly raise: the caller gets
        an exception and has to decide. Framework cores block. The open defaults concentrate in
        three places: <strong>agent hooks</strong>, where all four coded hook runners let the call
        through when the hook fails; <strong>gateway cores</strong>, three of five; and the{" "}
        <strong>integrations inside hubs</strong> whose own core fails closed, where 7 of 22 NeMo
        Guardrails integrations and 7 of 52 LiteLLM detector hooks allow on error. An operator who
        reads &quot;fails closed&quot; on the hub and then wires in a detector through it may be
        running a check that does not hold.
      </p>

      <h2 id="escapes">Six ways a failure escapes control</h2>
      <p>The paper lists six, each with execution evidence. In short:</p>
      <ul>
        <li>
          <strong>No time bound.</strong> Nine systems have a detector path that waits forever, so a
          slow detector is not a failure, it is an outage of the agent.
        </li>
        <li>
          <strong>A timeout that does not bound latency.</strong> One service sets the status code to
          timed out but returns only after the scanner ends.
        </li>
        <li>
          <strong>The check runs beside the action.</strong> One SDK runs input guardrails in parallel
          with the agent&apos;s turn by default; with a tool that records its calls, a guardrail that
          tripped after half a second tripped after the tool had run.
        </li>
        <li>
          <strong>Failures labelled as successes.</strong> Two scanners in one library return a
          fallback result when their LLM call fails and mark it a success, so a caller checking the
          status cannot tell a failed check from a passed one.
        </li>
        <li>
          <strong>Partial open paths</strong> inside systems that are closed on the main path.
        </li>
        <li>
          <strong>A declared fail mode that does not cover errors.</strong> That one was ours.
        </li>
      </ul>

      <h2 id="ours">The bug in our own guardrail</h2>
      <p>
        AgentFox is one of the sixteen, and the paper says so with the conflict of interest. At the
        commit we coded, a detector that raised was allowed even with <code>fail_mode</code> set to{" "}
        <code>closed</code>: the switch covered a detector that timed out, not one that errored. We
        found it during the study, fixed it, and report it as found. The shipped default is still open,
        with a 40 ms budget per check, because an unreachable detector should not take a production
        agent down by default; the point is that <code>closed</code> now means what it says, and a
        failed check is recorded as failed. The setting is described in the{" "}
        <Link href="/docs/reference/config">configuration reference</Link>.
      </p>

      <h2 id="ask">What to ask a guardrail vendor</h2>
      <p>The paper&apos;s recommendations are four, and they double as questions for any vendor:</p>
      <ol>
        <li>
          <strong>Is the fail mode declared, per check, for errors and timeouts separately?</strong>{" "}
          Kubernetes admission webhooks and Envoy&apos;s authorization filter default to fail closed and
          say so in their schema. A check that guards a state-changing tool call should default
          closed; one on a read-only step may default open, in writing.
        </li>
        <li>
          <strong>Is the verdict three-valued?</strong> Allow, deny, and unknown. A detector that could
          not answer must not be reported as one that passed.
        </li>
        <li>
          <strong>Does the timeout bound latency?</strong> Not the status code, the wall clock.
        </li>
        <li>
          <strong>Does a failed check reach the audit record?</strong> With the detector, the cause and
          the decision taken, so an auditor can see every call that went through unchecked.
        </li>
      </ol>
      <pre>{`detectors:
  injection_classifier:
    timeout_ms: 150      # time to a decision
    on_timeout: deny     # allow | deny | escalate
    on_error: deny
    on_malformed: deny   # 200 body, no verdict
  pii_service:
    timeout_ms: 400
    on_timeout: allow    # chosen and audited
    on_error: escalate
verdict_values: [allow, deny, unknown]
audit:
  on_unknown: record     # detector, cause, decision`}</pre>
      <p>
        The paper&apos;s table names each system and its class. The per-hook evidence stays private
        until the maintainers have had time to respond to the reports, and the data will be released
        after that. Where we lose is in the same table: our default was open, and our closed mode had
        a hole.
      </p>

      <InlineCTA
        title="See what your guardrail does when a check fails"
        body="AgentFox records every check that could not run, with the detector and the cause, next to the ones that did. Run it in watch mode and read the audit record."
        href="/docs/protect"
        label="Guardrails: watch first, then block"
      />
    </>
  );
}
