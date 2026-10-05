import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Output } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Support",
  description: "What to run before you file an issue, what to attach, and what never to paste.",
  path: "/docs/support",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Operate</p>
      <h1>Support</h1>
      <p className="docs-lede">
        Run three commands, attach what they print, reduce the problem to made-up values, and
        keep secrets and production data out of the report.
      </p>

      <h2>When to use this</h2>
      <p>
        When AgentFox does something you did not expect: a call allowed that should have been
        refused, a refusal you cannot explain, a command that fails. Check{" "}
        <Link href="/docs/limits">Limits</Link> first; the behaviour may be a known gap.
      </p>

      <h2>Run these first</h2>
      <Code>{`agentfox --version
agentfox admin version
agentfox doctor
agentfox policy list`}</Code>
      <Output>{`agentfox 0.3.1
╭───────────────────────────────────────╮
│ AgentFox 0.3.1                        │
│ control catalog   0.1.0-draft (draft) │
│ policy engine     native              │
│ default provider  echo                │
│ default mode      observe             │
│ fail mode         open                │
│ latency budget    300ms               │
│ egress allowed    False               │
╰───────────────────────────────────────╯
Runtime check
  ✓    database            reachable — 1 agent(s), 44 trace(s)
…
policy               version  mode     rules
baseline             v1       observe  13
eu-ai-act-high-risk  v1       observe  7
tool-containment     v1       enforce  25`}</Output>
      <ul>
        <li>
          <code>--version</code> is what every issue template asks for. From a clone, add the
          commit (<code>git rev-parse --short HEAD</code>).
        </li>
        <li>
          <code>admin version</code> is everything that takes part in a decision: catalog
          version, policy engine, default mode, fail mode, latency budget, egress.
        </li>
        <li>
          <code>doctor</code> grades the configuration. <code>agentfox doctor --json</code>{" "}
          gives one record per check if you prefer to paste JSON.
        </li>
        <li>
          <code>policy list</code> shows which packs are bound and whether each observes or
          enforces, which explains most &quot;why was this (not) blocked&quot; questions.
        </li>
      </ul>

      <h2>For a surprising verdict</h2>
      <ul>
        <li>
          The verdict and the <code>rules_fired</code> list, or the text of the{" "}
          <code>agentfox.Blocked</code> exception. It names the rule and the provenance of each
          argument.
        </li>
        <li>
          The grant (<code>agentfox permit list &lt;agent&gt;</code>) and the tool&apos;s
          declaration (<code>agentfox declare list tools</code>).
        </li>
        <li>
          What is in force for the agent: <code>agentfox policy effective --agent &lt;agent&gt;</code>.
        </li>
        <li>Your <code>taint_scope</code>; it changes many verdicts (<Link href="/docs/concepts#taint-scope">Concepts</Link>).</li>
        <li>
          A reduced reproduction: the smallest tool call, with made-up values, that gives the
          verdict. A <code>curl</code> to <code>/v1/guard/tool_call</code> against a scratch
          database is ideal.
        </li>
      </ul>
      <p>
        Reproduce against a scratch database so you are not sharing yours:
      </p>
      <Code>{`export AGENTFOX_STATE_DIR="$(mktemp -d)"
agentfox init`}</Code>

      <h2>Never paste</h2>
      <Callout kind="warning" title="A GitHub issue is public">
        <ul>
          <li>API tokens (<code>nom_api_…</code>), provider keys, <code>AGENTFOX_AUDIT_SIGNING_KEY</code>,{" "}
            <code>AGENTFOX_SERVICE_AUTH_SECRET</code>, <code>AGENTFOX_TOKEN_ENCRYPTION_KEY</code>, a database URL with a password.</li>
          <li>Real prompts, model responses, tool arguments, retrieved documents, or customer data.</li>
          <li>Rows from the audit chain, the database file, or an evidence package. They contain everything above.</li>
          <li>Real names, email addresses, account numbers and internal URLs. Replace them with obvious placeholders such as <code>ada@example.com</code>.</li>
        </ul>
      </Callout>
      <p>
        The default <code>redact_at_capture</code> masks detected secrets and personal data in
        the audit log, but it only masks what its detectors find. Read anything before you
        paste it.
      </p>

      <h2>Where to send it</h2>
      <p>
        Bugs and questions: GitHub issues and discussions, linked from{" "}
        <Link href="/support">Support</Link>. A security vulnerability goes through
        GitHub&apos;s private security advisories, never a public issue.
      </p>

      <NextSteps
        items={[
          { href: "/docs/limits", label: "Limits", why: "check whether it is a known gap" },
          { href: "/docs/install#doctor", label: "agentfox doctor", why: "what each line means" },
          { href: "/docs/reference/cli", label: "CLI reference", why: "every command and flag" },
        ]}
      />
    </article>
  );
}
