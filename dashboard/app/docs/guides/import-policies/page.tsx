import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, Step, Steps, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Import existing policies",
  description:
    "Bring agent-governance rule YAML or a policy manifest over unchanged: see what every rule becomes, what cannot be translated and why, then import it watching.",
  path: "/docs/guides/import-policies",
});

const cli = (path: string) => `/docs/reference/cli#cmd-${path}`;

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Guide</p>
      <h1>Import existing policies</h1>
      <p className="docs-lede">
        Policies written for the Agent Governance Toolkit can be imported as they are. Each
        rule is translated into a typed AgentFox policy rule, translated with a note where
        the meaning shifts, or listed as not translatable with the reason. Nothing is dropped
        silently, and no deny comes out weaker.
      </p>

      <h2>When to use this</h2>
      <p>
        You already have rule files (<code>apiVersion: governance.toolkit/v1</code>, with{" "}
        <code>rules</code> and <code>default_action</code>) or policy manifests (
        <code>agent_control_specification_version</code>, bound to a Rego bundle), and want them
        evaluated by the deterministic AgentFox engine, with simulation before enforcement.
      </p>
      <TaskTable
        rows={[
          { task: "See what a file would become", run: "agentfox policy import FILE", href: "#plan" },
          { task: "Import it, watching", run: "agentfox policy import FILE --apply", href: "#apply" },
          { task: "Import over HTTP", run: "POST /api/import/agent-governance", href: "#api" },
        ]}
      />
      <InTheApp path="/app/policies?tab=library&sec=import">
        Policies → Library → Import → Agent governance YAML or policy manifest
      </InTheApp>

      <h2 id="plan">Read the plan first</h2>
      <Steps>
        <Step title="Run the import without --apply">
          <Code title="support.yaml">{`apiVersion: governance.toolkit/v1
name: support-agent
default_action: deny
rules:
  - name: allow-reads
    condition: "tool_name startswith 'read_'"
    action: allow
  - name: big-refunds-need-approval
    condition: "amount > 500 and tool_name == 'refund'"
    action: require_approval
  - name: owner-only
    condition: "user.id == resource.owner"
    action: deny`}</Code>
          <Code>{`agentfox policy import support.yaml`}</Code>
          <Output>{`default (imported-support-agent): Unmatched calls are blocked by the \`default-deny\` rule on tool_args.
status          rule                       effect    why
with note       allow-reads                allow     an exception to the default deny: calls it matches are
                                                     not blocked by the default-deny rule (other block rules
                                                     still apply)
with note       big-refunds-need-approval  escalate  context field \`amount\` is read as the tool-call argument
                                                     \`amount\`; when the field is missing or not a number their
                                                     deny rule fires and this one does not; escalates to the
                                                     approval queue
not translated  owner-only                 —         compares two fields (\`user.id == resource.owner\`); a
                                                     condition here compares a field with a value, and their
                                                     evaluator does not recognise this syntax: there it
                                                     matches every call for a deny rule and no call for an
                                                     allow rule
  0 translated, 2 with a note, 1 not translated; 0 text pattern(s) become custom rules
  lint: no policy issues`}</Output>
          <p>
            The plan is also printed as JSON with <code>--json</code>, and comes with the
            result of the policy linter run on what would be saved.
          </p>
        </Step>
        <Step title="Check the default">
          <p>
            <code>default_action: allow</code> means a call no rule matches passes. The plan
            puts that first, as <strong>Unmatched calls pass</strong>, because it is easy to miss
            in a long file. <code>default_action: deny</code> becomes a <code>default-deny</code>{" "}
            block rule, with the allow rules carved out of it where they test only the tool or
            agent name.
          </p>
        </Step>
        <Step title="Read what was not translated">
          <p>Every rule the plan marks not translated is absent from the import. Common reasons:</p>
          <ul>
            <li>
              A comparison of two fields, such as <code>user.role == resource.owner</code>. A
              condition here compares a field with a value. The source evaluator cannot compare
              two fields either: it treats them as unrecognised syntax, so such a deny there
              matches every call. Fields both known to the engine (tool, agent, surface,
              environment) are translated.
            </li>
            <li>Negations (<code>not ...</code>), rate limits, and conditions on the call&apos;s context or budget.</li>
            <li>More than one argument comparison in one condition.</li>
            <li>Cedar policies, annotations (classifier calls) and conditional verdict rules in Rego.</li>
          </ul>
        </Step>
      </Steps>

      <h2>How meaning carries over</h2>
      <ul>
        <li>
          <code>deny</code> becomes <strong>block</strong>, <code>require_approval</code> becomes{" "}
          <strong>escalate</strong> (the approvals queue), <code>warn</code> and{" "}
          <code>log</code> are recorded when they fire.
        </li>
        <li>
          Priorities do not carry over. When several rules match, the strongest effect wins, so
          an allow never overrides a block. That is stricter than first-match-by-priority, and
          the plan says so on each allow rule.
        </li>
        <li>
          Conditions are parsed, not pattern-matched: <code>==</code>, <code>!=</code>,{" "}
          <code>in [...]</code>, <code>contains</code>, <code>startswith</code>,{" "}
          <code>endswith</code>, numeric comparisons, <code>and</code> and <code>or</code>. An{" "}
          <code>or</code> or an <code>in</code> list on the tool becomes one rule per branch.
        </li>
        <li>
          A regular expression or substring test on message text becomes a custom pattern rule
          that only detects; the imported policy rule acts on that detection.
        </li>
        <li>
          A manifest is checked against the published JSON Schemas before anything else. Each
          Rego policy bound to an intervention point is read for its decision rules (
          <code>deny contains msg if {"{ ... }"}</code>, <code>escalations</code>,{" "}
          <code>allows</code> …); <code>input</code>, <code>output</code>,{" "}
          <code>pre_tool_call</code> and <code>post_tool_call</code> map to the input, output,
          tool-argument and tool-result surfaces. Rego is never executed.
        </li>
      </ul>

      <h2 id="apply">Import, watching</h2>
      <Code>{`agentfox policy import support.yaml --apply
agentfox policy import manifest.yaml --bundle ./rego --apply`}</Code>
      <p>
        Imported policies are saved in <code>observe</code>: they record what they would have
        done and block nothing. A policy that is already live keeps its mode; the new version
        waits. To enforce, replay recorded traffic first with{" "}
        <Link href={cli("policy-simulate")}>
          <code>agentfox policy simulate</code>
        </Link>
        , then promote it.
      </p>
      <Callout kind="note" title="Manifests need their Rego">
        A manifest names a bundle directory; the CLI reads it from beside the manifest, or from{" "}
        <code>--bundle</code>. In the web app, upload the <code>.rego</code> files with the
        manifest. A <code>bundle_url</code> is never fetched.
      </Callout>

      <h2 id="api">Over HTTP</h2>
      <Code>{`curl -s -X POST localhost:8080/api/import/agent-governance/plan \\
  -H 'content-type: application/json' \\
  -d '{"source": "<the YAML>", "files": {"policy.rego": "<the Rego>"}}'`}</Code>
      <p>
        The plan lists <code>items</code> (each with <code>status</code>, <code>effect</code>,{" "}
        <code>notes</code> and <code>reason</code>), <code>default_action</code>,{" "}
        <code>unmatched_pass</code>, <code>schema_errors</code> and <code>lint</code>. Post the
        same body to <code>/api/import/agent-governance</code> to apply it; <code>skip</code>{" "}
        takes positions in <code>items</code> to leave out.
      </p>

      <NextSteps
        items={[
          { href: "/docs/guides/tuning", label: "Tune detectors", why: "simulate and canary before enforcing" },
          { href: "/docs/app/policies", label: "Policies and tuning", why: "the screens the import lands on" },
        ]}
      />
    </article>
  );
}
