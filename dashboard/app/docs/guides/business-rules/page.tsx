import type { Metadata } from "next";
import Link from "next/link";
import { Callout, Code, InTheApp, NextSteps, Output, Step, Steps, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Business rules",
  description:
    "Threshold ladders that pick exactly one outcome for a number, the guardrail catalogue, compiling a written policy, and finding where two teams' rules disagree.",
  path: "/docs/guides/business-rules",
});

const CLI = "/docs/reference/cli#cmd-";

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Guide</p>
      <h1>Business rules</h1>
      <p className="docs-lede">
        Turn a rule like &quot;credits under $50 go through, up to $500 need a check, above
        that a finance lead approves&quot; into a threshold ladder. Each value gets exactly one
        outcome, and you can test it before it runs.
      </p>

      <h2>When to use this</h2>
      <p>
        Use a ladder when the decision depends on where a number falls: a credit or discount
        amount, an export&apos;s row count, a number of days. You could write it as three
        ordinary policy rules, but that fails in two quiet ways. <code>lt 50</code> and{" "}
        <code>gt 50</code> leave exactly 50 uncovered. And because policy rules all fire and
        the strongest wins, a higher band can never be more lenient than a lower one. A ladder
        has bands that are half-open by construction, so it has no gaps or overlaps. It selects
        one outcome per value, and it adds <code>verify</code>: run a check, then decide.
      </p>
      <TaskTable
        rows={[
          { task: "Author or update a ladder from YAML", run: "agentfox policy rules apply", href: `${CLI}policy-rules-apply` },
          { task: "See the resolved bands", run: "agentfox policy rules show", href: `${CLI}policy-rules-show` },
          { task: "Try values without running anything", run: "agentfox policy rules test", href: `${CLI}policy-rules-test` },
          { task: "Find where two teams' ladders disagree", run: "agentfox policy rules check", href: `${CLI}policy-rules-check` },
          { task: "See every kind of guardrail that exists", run: "agentfox policy catalogue", href: `${CLI}policy-catalogue` },
          { task: "Map a sentence to a guardrail kind", run: "agentfox policy rules suggest", href: `${CLI}policy-rules-suggest` },
          { task: "Compile a written policy", run: "agentfox policy compile", href: `${CLI}policy-compile` },
          { task: "See the decision path stage by stage", run: "agentfox policy rules graph", href: `${CLI}policy-rules-graph` },
        ]}
      />

      <h2>A credit approval ladder, end to end</h2>
      <p>
        The agent is <code>billing-ops</code>. It credits customer accounts through a tool
        called <code>billing.credit</code>, which takes an <code>amount</code> in dollars.
        Everything below ran in a fresh project after <code>agentfox init</code>.
      </p>

      <Steps>
        <Step title="Write the ladder">
          <Code lang="yaml" title="credit-ladder.yaml">{`key: billing-credit-ladder
name: Account credit approval
description: How much credit billing-ops may grant without a person.
tool: billing.credit
field: arguments.amount
unit: USD
owner: finance
mode: observe
bands:
  - upto: 50
    outcome: allow
    reason: small goodwill credit
  - upto: 500
    outcome: verify
    verify:
      check: billing.credit_history
      expect: {credits_last_90d: {op: lt, value: 3}}
      on_fail: escalate
  - upto: 5000
    outcome: escalate
    approver_role: finance-lead
  - outcome: block
    reason: credits above $5,000 go through the finance system, not an agent`}</Code>
          <ul>
            <li>
              <code>field</code> is a dotted path into the request. For a tool call, the
              arguments are under <code>arguments</code>.
            </li>
            <li>
              <code>unit</code> is one of <code>USD</code>, <code>EUR</code>,{" "}
              <code>GBP</code>, <code>JPY</code>, <code>USD_CENTS</code>,{" "}
              <code>EUR_CENTS</code>, <code>GBP_CENTS</code>, <code>count</code> or{" "}
              <code>days</code>. Use <code>count</code> for row counts.
            </li>
            <li>
              Each band covers everything above the previous band&apos;s <code>upto</code>, up
              to and including its own. Bands must ascend, and the last band must have no{" "}
              <code>upto</code>, so every value lands somewhere.
            </li>
            <li>
              <code>outcome</code> is <code>allow</code>, <code>verify</code>,{" "}
              <code>escalate</code>, <code>block</code> or <code>redact</code>. A{" "}
              <code>verify</code> band must say what to check. <code>on_pass</code> (default{" "}
              <code>allow</code>), <code>on_fail</code> and <code>on_error</code> (both default{" "}
              <code>escalate</code>) say what follows.
            </li>
            <li>
              <code>tool</code> limits the ladder to one tool. Leave it out and the ladder
              applies to every tool call that carries the field.
            </li>
          </ul>
        </Step>

        <Step title="Apply it, and read back what you wrote">
          <Code>{`agentfox policy rules apply credit-ladder.yaml`}</Code>
          <Output>{`✓ billing-credit-ladder — 4 bands on arguments.amount (USD)
    (−∞, 50]  →  allow
    (50, 500]  →  verify via billing.credit_history, on fail → escalate
    (500, 5000]  →  escalate approver: finance-lead
    (5000, ∞]  →  block
  observe mode — the outcome is recorded, not applied.`}</Output>
          <Code>{`agentfox policy rules show billing-credit-ladder`}</Code>
          <Output>{`billing-credit-ladder  finance · observe
  How much credit billing-ops may grant without a person.
    (−∞, 50]  →  allow
    (50, 500]  →  verify via billing.credit_history, on fail → escalate
    (500, 5000]  →  escalate approver: finance-lead
    (5000, ∞]  →  block`}</Output>
          <p>
            Applying the same key again replaces the ladder and bumps its version.{" "}
            <code>--mode</code> overrides the file&apos;s <code>mode</code>.{" "}
            <code>--agent</code> scopes the ladder to one registered agent.{" "}
            <code>show</code> with no key lists every ladder.
          </p>
        </Step>

        <Step title="Test values on both sides of every boundary">
          <Code>{`agentfox policy rules test billing-credit-ladder "50,50.01,500,4999,5000.01"`}</Code>
          <Output>{`  value      outcome     why
  50         allow       small goodwill credit
  50.01      verify      arguments.amount = 50.01 USD, between 50 (exclusive) and 500 → v
  500        verify      arguments.amount = 500 USD, between 50 (exclusive) and 500 → ver
  4999       escalate    arguments.amount = 4999 USD, between 500 (exclusive) and 5000 →
  5000.01    block       credits above $5,000 go through the finance system, not an agent`}</Output>
          <p>
            <code>agentfox test rule</code> is the same command. Values that the ladder cannot
            read escalate rather than pass:
          </p>
          <Code>{`agentfox test rule billing-credit-ladder '$120,120 EUR,-5,abc'`}</Code>
          <Output>{`  value      outcome     why
  $120       verify      arguments.amount = 120 USD, between 50 (exclusive) and 500 → ver
  120 EUR    escalate    value is in EUR but the ladder is in USD; refusing to convert —
  -5         escalate    negative value -5 — the bands were written for positives
  abc        escalate    'abc' is not a number`}</Output>
          <p>
            A request that does not carry the field at all also escalates. A missing field is
            never a way past the ladder.
          </p>
        </Step>

        <Step title="Watch it decide real tool calls">
          <p>
            Ladders run on the tool-argument surface. The agent needs a grant for the tool
            first; without one, every call is refused by default-deny before the ladder
            matters. See <Link href="/docs/guides/contain-tool-calls">Contain tool calls</Link>.
          </p>
          <Code>{`agentfox declare tool billing.credit --impact write --description "Credit a customer account"
agentfox permit grant billing-ops billing.credit --yes
agentfox policy rules apply credit-ladder.yaml --mode enforce`}</Code>
          <Code lang="python" title="credit_agent.py">{`from agentfox import AgentFox, ApprovalRequired, PolicyViolation

nom = AgentFox(agent="billing-ops")

for amount in (25, 120, 900, 8000):
    with nom.session(intent="resolve a billing complaint") as s:
        try:
            r = s.guard_tool("billing.credit", {"account": "acct_42", "amount": amount})
            print(f"{amount:>5}  {r.verdict:<9} {r.reason}")
        except ApprovalRequired as e:
            print(f"{amount:>5}  approval  {e.result.reason}  (approval {e.result.approval_id})")
        except PolicyViolation as e:
            print(f"{amount:>5}  blocked   {e.result.reason}")`}</Code>
          <Output>{`   25  allow     no policy rule matched
  120  verify    arguments.amount = 120 USD, between 50 (exclusive) and 500 → verify
  900  approval  arguments.amount = 900 USD, between 500 (exclusive) and 5000 → escalate  (approval apr_01m46a0bpx5gr3knnz)
 8000  blocked   credits above $5,000 go through the finance system, not an agent`}</Output>
          <p>
            <code>escalate</code> creates an approval in the queue (see{" "}
            <Link href="/docs/guides/approvals">Approvals</Link>). The fired rule&apos;s id is{" "}
            <code>business.&lt;key&gt;</code>, and its <code>evidence</code> is the full ladder
            decision.
          </p>
          <Callout kind="note" title="What decides whether the outcome is applied">
            The ladder&apos;s own <code>mode</code>. The run above applied the ladder with{" "}
            <code>--mode enforce</code>, so every band was applied. In <code>observe</code>{" "}
            (the default) the outcome is recorded as the effective verdict and in the
            decision&apos;s fired rules, with <code>mode: observe</code>, and the call
            proceeds, whatever mode the policy packs are in. A ladder never loosens a
            security verdict: a block from a policy stands even under an{" "}
            <code>allow</code> band.
          </Callout>
        </Step>

        <Step title="Run the check for a verify band">
          <p>
            AgentFox does not own your tools, so it does not call the check itself. A{" "}
            <code>verify</code> result hands you the check to run; you supply a runner, and{" "}
            <code>run_verification</code> applies <code>expect</code> and the{" "}
            <code>on_pass</code>/<code>on_fail</code>/<code>on_error</code> outcomes. A runner
            that raises, or no runner at all, gives <code>on_error</code>. A check that could
            not run has not passed.
          </p>
          <Code lang="python" title="verify_band.py">{`from agentfox import AgentFox
from agentfox.capabilities.business import VerifySpec, run_verification

nom = AgentFox(agent="billing-ops")

def run_check(check: str, arguments: dict) -> dict:
    # Your code: look up the account's credit history.
    return {"credits_last_90d": 4}

with nom.session(intent="resolve a billing complaint") as s:
    r = s.guard_tool("billing.credit", {"account": "acct_42", "amount": 120})
    if r.verdict == "verify":
        rule = next(f for f in r.rules_fired if f["rule_id"].startswith("business."))
        outcome = run_verification(VerifySpec(**rule["evidence"]["verify"]), run_check)
        print(outcome.outcome, "-", outcome.detail)`}</Code>
          <Output>{`escalate - billing.credit_history: credits_last_90d=4 fails lt 3`}</Output>
        </Step>
      </Steps>

      <Callout kind="note" title="Security still wins">
        A ladder can only tighten a decision. If a security rule blocks a call, for example
        because its argument came from a web page, an <code>allow</code> band does not
        override it. Here a $25 credit, inside the <code>allow</code> band, carried text the
        session had marked as retrieved:
        <Output>{`ApprovalRequired | The granting capability requires human approval for this action.`}</Output>
      </Callout>

      <h2>When two teams disagree</h2>
      <p>
        Support wrote its own limit on the same field: allow up to $100, then escalate to a
        support lead.
      </p>
      <Code lang="yaml" title="support-credit.yaml">{`key: support-credit-limit
tool: billing.credit
field: arguments.amount
unit: USD
owner: support
bands:
  - upto: 100
    outcome: allow
  - outcome: escalate
    approver_role: support-lead`}</Code>
      <Code>{`agentfox policy rules apply support-credit.yaml
agentfox policy rules check`}</Code>
      <Output>{`1 conflict(s) across 2 rule(s)

  high contradiction
    at arguments.amount = 50.01 (USD), 'billing-credit-ladder' says verify and
'support-credit-limit' says allow. The stricter wins, but one of the two authors believes something
that is not happening
    between billing-credit-ladder and support-credit-limit`}</Output>
      <p>
        At run time, when several ladders match, the strictest outcome wins. <code>check</code>{" "}
        exists because that hides a disagreement between two people. It tests every boundary
        of every ladder on the same tool and field, and reports one contradiction per pair.
        Ladders on the same field in different units are reported as <code>critical</code>{" "}
        instead:
      </p>
      <Output>{`  critical unit-mismatch
    ladders on 'arguments.amount' declare different units ['USD', 'USD_CENTS'] — one team's 100 is
another's 1.00, and no precedence rule makes that safe`}</Output>
      <p>
        <code>agentfox policy rules check</code> exits 1 when it finds a conflict, and 0 with{" "}
        <code>✓ 1 rule(s), no conflicts</code> otherwise, so it works as a CI step.{" "}
        <code>--json</code> prints the conflicts as a list with <code>code</code>,{" "}
        <code>severity</code>, <code>detail</code>, <code>between</code>, <code>field</code>{" "}
        and <code>at_value</code>.
      </p>
      <p>
        <code>agentfox policy lint</code> is a different check. It lints the policy hierarchy
        (the security and containment packs, and their org, team, agent and environment
        layers) and does not look at ladders. With the two conflicting ladders above it
        printed <code>no policy issues</code>. See the{" "}
        <Link href="/docs/reference/policies">policy language reference</Link>.
      </p>

      <h2>What can be expressed: the catalogue</h2>
      <p>
        Before you write YAML, check that the rule you have in mind is a kind AgentFox can
        enforce. There are 22 kinds. Ladders are one; others include approval requirements,
        entitlement filters, knowledge boundaries and PII detection.
      </p>
      <Code>{`agentfox policy catalogue --intent require_human`}</Code>
      <Output>{`  kind                    intent           stage           decides
  threshold_ladder        require human    tool_args       Which of several outcomes applies, based on where a number falls.
  approval_requirement    require human    tool_args       Whether a named role must approve before the action proceeds.
  escalation_policy       require human    conversation    When a conversation must be handed to a person.

  3 kind(s). \`agentfox policy rules explain <kind>\` for parameters and an example.`}</Output>
      <p>
        Leave out <code>--intent</code> for all of them, or add <code>--json</code>.{" "}
        <code>agentfox policy rules catalogue</code> is the same command.{" "}
        <code>agentfox policy rules explain</code> gives one kind&apos;s parameters, what the
        request must carry for it to work, and an example:
      </p>
      <Code>{`agentfox policy rules explain threshold_ladder`}</Code>
      <Output>{`╭─ threshold_ladder ───────────────────────────────────────────────────────────╮
│ Threshold ladder                                                             │
│ Which of several outcomes applies, based on where a number falls.            │
│                                                                              │
│ intent  require_human                                                        │
│ nature  deterministic                                                        │
│ stage   tool_args                                                            │
│ yields  allow, verify, escalate, block, redact                               │
╰──────────────────────────────────────────────────────────────────────────────╯

  Needs the request to carry:
    · a numeric field on the request
    · an explicit unit or currency
    Without these it is configured but inert.

  Parameters:
    field  dotted path, e.g. arguments.amount
    unit  USD | EUR | GBP | JPY | *_CENTS | count | days
    bands  ordered; each has \`upto\` (inclusive) and an outcome; the last omits 
\`upto\`

  Example:
  …`}</Output>
      <p>
        <code>agentfox policy rules suggest</code> maps one sentence to likely kinds. It
        matches signals in the wording deterministically; it is not a model. Treat it as a
        starting point:
      </p>
      <Code>{`agentfox policy rules suggest "Credits over $500 need sign-off from a finance lead."
agentfox policy rules suggest "Do not answer questions about legal matters."
agentfox policy rules suggest "Be courteous to customers."`}</Code>
      <Output>{`  approval_requirement  0.17 · Whether a named role must approve before the action proceeds.
  threshold_ladder  0.08 · Which of several outcomes applies, based on where a number falls.
…
  knowledge_boundary  0.50 · Whether the question is answerable from what this agent can reach.
…
No guardrail kind matched that wording.
  Browse them with \`agentfox policy catalogue\`. A policy we cannot express is worth knowing about early.`}</Output>
      <p>
        <code>agentfox policy rules graph</code> lists every guardrail in the order it runs,
        by stage (input, retrieval, tool_args, output, conversation, offline). Your ladders
        appear under <code>tool_args</code>:
      </p>
      <Output>{`tool_args
    action_analysis             What a generated SQL, shell or HTTP artefact would actua
    approval_requirement        Whether a named role must approve before the action proc
    billing-credit-ladder       arguments.amount in USD, 4 bands finance
    capability_scope            Whether this identity may call this tool with these argu
    …
    support-credit-limit        arguments.amount in USD, 2 bands support
    …
  24 guardrail(s) across 6 stages.`}</Output>

      <h2>Compile a written policy</h2>
      <p>
        <code>agentfox policy compile</code> reads a <code>.txt</code> or <code>.md</code>{" "}
        policy and writes the rules it can. It lists every assumption it made, the questions
        it needs answered, and the sentences it cannot express.
      </p>
      <Code title="billing-policy.md" lang="markdown">{`# Billing assistant policy

Credits under $50 are auto-approved. Credits between $50 and $500 must run a fraud check before proceeding, and credits over $500 require approval from the finance team.

Never include an email address or phone number in a reply.

Do not answer questions about legal matters.

Agents must always be courteous to customers.`}</Code>
      <Code>{`agentfox policy compile billing-policy.md`}</Code>
      <Output>{`╭─────────────────────────────────── Compiled billing-policy.md ───────────────────────────────────╮
│ 60% of the governance in this document compiled without a question.                              │
│ 2 rule(s) ready · 1 to answer · 1 not expressible                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯

billing-policy-pii-detection  confidence 0.85
 kind       pii_detection
 entities   ['EMAIL_ADDRESS', 'PHONE_NUMBER']
 redaction  mask

billing-policy-billing-credit  confidence 0.70
 kind   threshold_ladder
 tool   billing.credit
 field  arguments.amount
 unit   USD
 mode   observe
          ≤ 50  allow
         ≤ 500  verify via risk.check
         above  escalate → finance
  assumed governs the tool 'billing.credit'
          inferred from the wording; no tool was named explicitly
  assumed verification calls 'risk.check'
          the policy says to validate but does not name the check
  assumed each threshold is inclusive — 'under $10' and 'from $10' both put 10 in the lower band
          the wording leaves the endpoint open and only one reading leaves no gap

Needs a decision
  blocking This reads like knowledge boundary. What should systems_of_record, coverage_months,
answerable_types be?
    the guardrail is clear from the wording but its settings are not stated, and a rule with empty
settings enforces nothing
    from: Do not answer questions about legal matters.

not expressible as a guardrail: Agents must always be courteous to customers.`}</Output>
      <p>
        Read the assumptions before you accept anything. Here the tool name was inferred and
        the check is a placeholder called <code>risk.check</code>. &quot;Under $50&quot; was
        read as including 50.
      </p>
      <p>
        <code>--json</code> prints the same result as data: <code>rules</code>,{" "}
        <code>review</code>, <code>unmappable</code>, <code>ignored</code>,{" "}
        <code>auto_rate</code> and <code>governance_sentences</code>. For this document,{" "}
        <code>auto_rate</code> was 0.6 over 5 governance sentences. The heading was ignored,
        and the courtesy sentence was unmappable.
      </p>
      <p>
        <code>--apply</code> saves the threshold ladders, in observe mode, and nothing else:
      </p>
      <Code>{`agentfox policy compile billing-policy.md --apply`}</Code>
      <Output>{`…
Saved 1 ladder(s) in observe mode. Run agentfox policy rules check, then promote with agentfox
policy rules apply <ladder.yaml> --mode enforce.
  1 other rule(s) are not threshold ladders and were not saved — author them with their own
commands.`}</Output>
      <p>
        The PII rule and the knowledge boundary have to be authored with their own commands
        (for the boundary, <code>agentfox declare boundary</code>; see{" "}
        <Link href="/docs/guides/rag">Retrieval and answers</Link>). Without{" "}
        <code>--apply</code>, the compiler only reads the document; it writes nothing. To get
        suggestions for a single sentence, use <code>agentfox policy rules suggest</code>.
      </p>
      <Callout kind="note" title="How much compiles">
        Compilation is deterministic; no model reads your document. Measured on the
        repository&apos;s test documents, 86% of a tuned document and 64% of a held-out one
        compile without a question. Prose with no parseable structure, like the courtesy
        sentence above, is reported as not expressible rather than guessed at. A
        model-assisted path for those sentences is not built.
      </Callout>

      <InTheApp path="/app/policies">Policies → Rules</InTheApp>

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong>
            <code>band 1 ends at 50.0, at or below the previous band&apos;s 100.0 — bands must ascend</code>.
          </strong>{" "}
          Order the bands by <code>upto</code>, smallest first.
        </li>
        <li>
          <strong><code>the final band must omit &apos;upto&apos;</code>.</strong> The last band is
          open-ended so every value is covered. Make it <code>block</code> or{" "}
          <code>escalate</code> if large values should not pass.
        </li>
        <li>
          <strong>
            <code>unit must be one of (&apos;USD&apos;, …), got &apos;dollars&apos;</code>
          </strong>{" "}
          and <strong><code>a &apos;verify&apos; band must declare what to check</code></strong>.
          The file is validated before anything is saved.
        </li>
        <li>
          <strong>Every call is blocked, including small ones.</strong> The reason starts{" "}
          <code>no resolved identity for the caller, so it holds no grants (default deny)</code>.
          Register the agent (run it once), declare the tool and grant it.
        </li>
        <li>
          <strong>Bands are reported but nothing happens.</strong> No enforcing policy governs
          the call; see the warning in the walkthrough.
        </li>
        <li>
          <strong><code>unknown agent &apos;research-bot&apos;</code></strong> from{" "}
          <code>rules apply --agent</code>: nothing is saved, and the message lists the
          agents that exist. Register a new one with{" "}
          <code>agentfox agents register research-bot</code>.
        </li>
        <li>
          <strong><code>unknown rule &apos;…&apos;</code> from <code>test</code></strong> and{" "}
          <strong><code>unknown kind &apos;…&apos;</code> from <code>explain</code></strong>.
          The second one lists the valid kinds.
        </li>
        <li>
          <strong>A ladder carries a band you did not mean.</strong> Count thresholds
          (&quot;over 10,000 rows&quot;) become their own <code>count</code> ladder, separate
          from money ones, but the compiler still guesses the tool and the field. Check every
          band&apos;s <code>reason</code> in <code>--json</code> output before{" "}
          <code>--apply</code>, and prefer writing the YAML yourself for anything that moves
          money.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>A ladder bands one numeric field, on tool arguments only. It cannot read inputs or outputs.</li>
        <li>AgentFox does not run <code>verify</code> checks; your code runs them.</li>
        <li>
          <code>compile --apply</code> saves threshold ladders only. Compiled rules of other
          kinds are shown, not saved.
        </li>
        <li>The compiler is deterministic and covers structured prose. It does not use a model.</li>
        <li>
          Business rules are partial overall; see <Link href="/docs/limits">Limits</Link>.
        </li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/guides/approvals", label: "Approvals and the kill switch", why: "Where an escalate band's approvals land, and who works them." },
          { href: "/docs/guides/contain-tool-calls", label: "Contain tool calls", why: "Grants and declarations, which must allow the call before a ladder decides it." },
          { href: "/docs/reference/policies", label: "Policy language", why: "The security policy hierarchy that policy lint checks." },
          { href: "/docs/guides/red-team-and-evals", label: "Red team and evals in CI", why: "Run policy rules check next to your other CI gates." },
        ]}
      />
    </article>
  );
}
