import type { Metadata } from "next";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Harness",
  description: "Skills, slash commands, and a read-only MCP server for a coding agent.",
  path: "/docs/harness",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Start</p>
      <h1>Harness</h1>
      <p>
        The harness packages the product as skills, slash commands, subagents, and
        safety hooks, so a coding agent can govern an agent without you memorising the
        CLI first. It drives the <code>agentfox</code> CLI, so the product has to be
        installed where that agent runs.
      </p>
      <pre>
        <code>{`pip install "git+https://github.com/architsharm/agentfox.git"`}</code>
      </pre>

      <h2>Claude Code</h2>
      <pre>
        <code>{`claude plugin marketplace add architsharm/agentfox
claude plugin install agentfox@agentfox`}</code>
      </pre>
      <p>From a local clone, with nothing installed into Claude Code:</p>
      <pre>
        <code>claude --plugin-dir ./harness</code>
      </pre>
      <p>
        Any other agent (Codex, Cursor, Gemini CLI, Aider) can be pointed at{" "}
        <code>harness/AGENTS.md</code>. The skills are plain markdown.
      </p>

      <h2>Slash commands</h2>
      <table>
        <thead>
          <tr>
            <th>Command</th>
            <th>What it does</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>/agentfox:tour</code></td>
            <td>An offline tour in a scratch database.</td>
          </tr>
          <tr>
            <td><code>/agentfox:start</code></td>
            <td>Scan the code, add <code>agentfox.auto()</code> in observe, and show what it sees.</td>
          </tr>
          <tr>
            <td><code>/agentfox:status</code></td>
            <td>Read-only posture: doctor, open findings, policy modes, agent states.</td>
          </tr>
          <tr>
            <td><code>/agentfox:findings</code></td>
            <td>Grouped triage, with a recommended action for each finding.</td>
          </tr>
          <tr>
            <td><code>/agentfox:policy</code></td>
            <td>Draft, validate, lint, and simulate. Promotion only when you say so.</td>
          </tr>
          <tr>
            <td><code>/agentfox:guardrail</code></td>
            <td>A business rule in plain English, written as a guardrail in observe mode.</td>
          </tr>
          <tr>
            <td><code>/agentfox:gate</code></td>
            <td>An eval regression gate and a CI workflow.</td>
          </tr>
          <tr>
            <td><code>/agentfox:redteam</code></td>
            <td>Adversarial probes, the results explained, fixes proposed.</td>
          </tr>
          <tr>
            <td><code>/agentfox:evidence</code></td>
            <td>Verify the audit chain and export a package.</td>
          </tr>
          <tr>
            <td><code>/agentfox:contain</code></td>
            <td>Quarantine, with confirmation, plus blast radius and evidence.</td>
          </tr>
          <tr>
            <td><code>/agentfox:proposals</code></td>
            <td>What the improvement loop wants to change. Applying anything needs you.</td>
          </tr>
        </tbody>
      </table>

      <h2>MCP server</h2>
      <p>
        The plugin starts <code>agentfox mcp serve</code>, which exposes 27 read-only
        tools: posture, findings, proposals, policy validate and simulate, audit verify,
        compliance status, and a few analysers. Nothing there decides, applies, or rolls
        back a change. Other MCP clients can run the same process:
      </p>
      <pre>
        <code>agentfox mcp serve</code>
      </pre>

      <h2>What it will not do on its own</h2>
      <p>
        Three subagents stay inside a lane. <code>governance-auditor</code> is read-only
        and ends in a written report. <code>policy-author</code> drafts and simulates
        and never promotes. <code>integration-engineer</code> wires guardrails in
        observe mode.
      </p>
      <p>
        A safety hook turns every command that changes what gets blocked into a
        permission prompt with a plain-language reason. That covers{" "}
        <code>policy enforce</code>, <code>agents kill</code>, <code>demo</code>,{" "}
        <code>proposals apply</code>, <code>proposals rollback</code>,{" "}
        <code>--mode enforce</code>, and <code>--submit</code>.
      </p>
    </article>
  );
}
