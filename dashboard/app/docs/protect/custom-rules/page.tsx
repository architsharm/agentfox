import type { Metadata } from "next";
import Link from "next/link";

import { Code, NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { Tab, Tabs } from "@/components/docs/tabs";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Custom rules",
  description:
    "Write your own guardrails: blocked words and topics, value limits, approval limits by amount, rules imported from other tools, and questions the agent should not answer.",
  path: "/docs/protect/custom-rules",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Custom rules</h1>
      <p className="docs-lede">
        Add a rule of your own, watch what it would do, then start blocking with it.
      </p>

      <Steps topLevel>
        <Step title="Pick what you want to do">
          <p>
            On <strong>Policies</strong>, press <strong>New rule</strong>. Pick a card: block words or a
            pattern, keep off a topic, keep on topic, a value crosses a line, approve above an amount, stop
            a risky sequence, and more.
          </p>
          <Screenshot {...SCREENS.addRule} />
        </Step>

        <Step title="Say where it applies and what it does">
          <p>
            Fill in the form: what to look for, where (the user&apos;s message, the reply, a tool&apos;s
            arguments or its result), and what to do when it matches. For a tool call, the rule runs before
            the tool does, so <strong>Ask a human</strong> holds the call on Approvals.
          </p>
        </Step>

        <Step title="Watch, then start blocking">
          <p>
            Every rule you write is saved watching, in the <strong>Your rules</strong> library. Open it from{" "}
            <strong>Policies → Libraries</strong> to see what each rule would have done, then press{" "}
            <strong>Start blocking</strong>. If Your rules is already blocking, a rule you add later still
            starts watching on its own: open it and press <strong>Start blocking this rule</strong> on its{" "}
            <strong>Tune</strong> tab, which replays the last 7 days first.
          </p>
          <Screenshot {...SCREENS.yourRules} />
        </Step>
      </Steps>

      <h2 id="limits">Approval limits by amount</h2>
      <p>
        &quot;Credits under $50 go through, up to $5,000 need a finance lead, above that never&quot; is an
        approval limit. Each amount gets exactly one outcome, with no gap at the boundaries. In the app,
        choose <strong>Approve above an amount</strong>. From the CLI, write it as a file and test values
        before it runs:
      </p>
      <Code>{`agentfox policy rules apply credit-ladder.yaml
agentfox policy rules test billing-credit-ladder "50,50.01,5000.01"`}</Code>
      <p>
        A missing or unreadable amount is sent for approval, never let through. The file format, and{" "}
        <code>credit-ladder.yaml</code> itself, are in the{" "}
        <Link href="/docs/reference/policies#business-rules">policy reference</Link>.
      </p>

      <h2 id="import">Import rules from another tool</h2>
      <Tabs>
        <Tab label="In the app">
          <p>
            Press <strong>New rule</strong>, then <strong>Bring rules you already have</strong>. Choose
            Guardrails AI, or Agent governance YAML or a policy manifest. The preview marks every rule as
            translated, translated with a note, or not translated with the reason. Untick what you do not
            want and import.
          </p>
        </Tab>
        <Tab label="CLI">
          <Code>{`agentfox policy import support.yaml
agentfox policy import support.yaml --apply`}</Code>
        </Tab>
      </Tabs>
      <p>
        Imported rules start watching. When several match, the strongest effect wins, so an allow never
        overrides a block. Check whether calls no rule matches pass: the preview says so first.
      </p>
      <p>An agent-governance rule file you can paste as it is:</p>
      <Code>{`apiVersion: governance.toolkit/v1
name: payables-guard
default_action: allow
rules:
  - name: no-vendor-delete
    condition: "tool_name == 'delete_vendor'"
    action: deny
  - name: big-payments
    condition: "tool_name == 'pay_vendor' and amount > 25000"
    action: require_approval
  - name: no-iban-in-replies
    condition: "output contains 'IBAN'"
    action: deny`}</Code>
      <p>
        A rule with no <code>stage</code> checks tool calls, unless its condition reads the reply
        (<code>output</code>, <code>response</code>) or the user&apos;s message (<code>input</code>,{" "}
        <code>prompt</code>, <code>query</code>): then it checks that. The imported policy opens from the
        import&apos;s result. On its page, <strong>Start blocking</strong> replays it over the last 7 days
        first, and <strong>Remove</strong> stops it applying.
      </p>

      <h2 id="answers">Make the agent say &quot;I don&apos;t know&quot;</h2>
      <p>
        On the agent&apos;s <strong>Access</strong> page, fill in <strong>What it may answer</strong>: the
        data it answers from, how far back that data goes, the topics it must not answer, and the kinds of
        question it may answer. A question outside that is refused before the model is called, with a
        sentence you can show the user.
      </p>
      <Tabs>
        <Tab label="In the app">
          <p>Saved from the app, the boundary watches: refusals are recorded, not applied.</p>
        </Tab>
        <Tab label="CLI">
          <p>Try real questions first, then switch it to block.</p>
          <Code>{`agentfox test boundary support-triage "Will volume go up next quarter?"
agentfox declare boundary support-triage --systems help-center,tickets \\
  --answerable fact,procedure --mode enforce`}</Code>
        </Tab>
      </Tabs>

      <NextSteps
        items={[
          { href: "/docs/protect", label: "Guardrails", why: "libraries, Watch and Block" },
          { href: "/docs/reference/policies", label: "Policy language", why: "rule YAML, limit files, import mapping" },
        ]}
      />
    </article>
  );
}
