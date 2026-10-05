import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Output } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Claude Code harness",
  description:
    "Skills, slash commands, subagents, a safety hook and a read-only MCP server that let a coding agent drive AgentFox.",
  path: "/docs/harness",
});

const COMMANDS: [string, string][] = [
  ["/agentfox:tour", "A safe offline tour of AgentFox in a throwaway database."],
  ["/agentfox:start [path]", "Govern this codebase: scan, init, add agentfox.auto() in observe mode, report."],
  ["/agentfox:status", "Read-only posture: runtime health, open findings, policy modes, stopped agents."],
  ["/agentfox:findings", "Triage open findings into a grouped, prioritised action list."],
  ["/agentfox:policy", "Draft, validate, lint and simulate a policy change. Promotion only on explicit approval."],
  ["/agentfox:guardrail", "Turn a written business rule into an executable guardrail, in observe mode."],
  ["/agentfox:gate", "Set up an eval regression gate and a governance CI workflow."],
  ["/agentfox:redteam", "Red-team an agent with the built-in probes and propose fixes."],
  ["/agentfox:evidence", "Verify the audit chain, report framework posture, export an evidence package."],
  ["/agentfox:contain", "Incident response: facts, containment (with confirmation), blast radius, evidence."],
  ["/agentfox:proposals", "Review the improvement loop's proposals and what each needs before it can happen."],
  ["/agentfox:harness-check", "Check the harness markdown against the live CLI, repository paths and docs map."],
];

const SKILLS: [string, string][] = [
  ["using-agentfox", "Entry point. Holds the safety rules and routes to the right task skill."],
  ["tour-product", "An offline tour in a throwaway database."],
  ["onboard-codebase", "From ungoverned to observed: scan, init, auto() in observe, first traffic, report."],
  ["integrate-guardrails", "Beyond the one-liner: tool impact, untrusted-content marking, LangGraph, FastAPI, MCP, the gateway proxy, with a test that a tainted irreversible call escalates."],
  ["declare-agent-controls", "Knowledge boundaries, source authority, principals, escalation, row-scoped tables."],
  ["triage-findings", "Grouped findings with a recommended move each; suppress or resolve only with agreement."],
  ["author-policy", "Draft, validate, lint and simulate policy YAML; promote only on approval."],
  ["business-guardrails", "A written business rule as a guardrail in observe mode, tested and checked for conflicts."],
  ["eval-gate", "A regression gate and a CI workflow that also fails on ungoverned calls and a broken chain."],
  ["red-team", "The built-in probes against real grants and bindings, then fixes and a re-run."],
  ["audit-evidence", "Verify and checkpoint the chain, compute posture, export a package."],
  ["incident-response", "Establish what happened, quarantine or kill with confirmation, map blast radius, preserve evidence."],
  ["operate-improvement-loop", "Read, decide, canary, roll back and freeze proposals."],
  ["operate-deployment", "Run the gateway and dashboard, harden auth and secrets, migrations, tokens."],
  ["develop-agentfox", "For contributors to the AgentFox repository itself."],
];

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Operate</p>
      <h1>Claude Code harness</h1>
      <p className="docs-lede">
        A Claude Code plugin that packages AgentFox as skills, slash commands, subagents, a
        safety hook and a read-only MCP server, so a coding agent can do the work without
        you learning the CLI first.
      </p>

      <h2>When to use this</h2>
      <p>
        Use it when you would rather say &quot;get my support agent governed&quot; than type
        the commands, or when you want a coding agent to wire AgentFox into a codebase. It
        drives the same <code>agentfox</code> CLI documented here, so everything it does you
        can also do by hand. It is not the same thing as the Claude Code <em>hooks</em> that
        govern a coding agent&apos;s own tool calls; those are on{" "}
        <Link href="/docs/guides/coding-agents">Coding agents</Link>.
      </p>

      <h2>Install</h2>
      <p>The harness calls the CLI, so AgentFox must be installed where Claude Code runs:</p>
      <Code>{`pip install agentfox`}</Code>
      <p>Then add the plugin from GitHub:</p>
      <Code>{`claude plugin marketplace add architsharm/agentfox
claude plugin install agentfox@agentfox`}</Code>
      <p>Or try it from a local clone without installing anything into Claude Code:</p>
      <Code>{`claude --plugin-dir ./harness`}</Code>
      <p>Both manifests validate with Claude Code&apos;s own checker:</p>
      <Code>{`claude plugin validate ./harness
claude plugin validate .`}</Code>
      <Output>{`Validating plugin manifest: …/harness/.claude-plugin/plugin.json

✔ Validation passed
Validating marketplace manifest: …/.claude-plugin/marketplace.json

✔ Validation passed`}</Output>
      <p>
        Other coding agents (Codex, Cursor, Gemini CLI, Aider) can use the same material: point
        them at <code>harness/AGENTS.md</code>. The skills are plain markdown.
      </p>
      <p>
        The plugin finds the CLI through <code>harness/scripts/agentfox.sh</code>: an{" "}
        <code>agentfox</code> on <code>PATH</code> first, then <code>uv run</code> or a local{" "}
        <code>.venv</code> in a source checkout. If none is found it prints the install line
        and exits 127.
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
          {COMMANDS.map(([c, d]) => (
            <tr key={c}>
              <td>
                <code>{c}</code>
              </td>
              <td>{d}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        Start with <code>/agentfox:tour</code> to see the product in a scratch database, then{" "}
        <code>/agentfox:start</code> in your repository. That is the same path as the{" "}
        <Link href="/docs/quickstart">Quickstart</Link>.
      </p>

      <h2>Skills</h2>
      <p>
        The commands load these. Claude Code also loads them on its own when a request matches
        their description, so &quot;red-team my agent&quot; works without the slash command.
      </p>
      <table>
        <thead>
          <tr>
            <th>Skill</th>
            <th>Covers</th>
          </tr>
        </thead>
        <tbody>
          {SKILLS.map(([s, d]) => (
            <tr key={s}>
              <td>
                <code>{s}</code>
              </td>
              <td>{d}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Subagents</h2>
      <table>
        <thead>
          <tr>
            <th>Subagent</th>
            <th>Stays inside</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>governance-auditor</code></td>
            <td>Read-only posture review ending in a written report. Never changes state.</td>
          </tr>
          <tr>
            <td><code>policy-author</code></td>
            <td>Drafts, validates, lints and simulates policy. Never promotes to enforce.</td>
          </tr>
          <tr>
            <td><code>integration-engineer</code></td>
            <td>Wires AgentFox into application code, in observe mode, with tests.</td>
          </tr>
        </tbody>
      </table>

      <h2>The safety hook</h2>
      <p>
        A <code>PreToolUse</code> hook on Bash turns every command that changes what gets
        blocked into a permission prompt with a plain-language reason. Anything else passes
        through untouched. For example:
      </p>
      <Code>{`echo '{"tool_name":"Bash","tool_input":{"command":"agentfox policy enforce baseline"}}' \\
  | python3 harness/scripts/guard_blocking_commands.py`}</Code>
      <Output>{`{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": "AgentFox harness: this command promotes a policy to ENFORCE \\u2014 matching production traffic starts being blocked. Confirm the user asked for exactly this."}}`}</Output>
      <p>
        It asks before: <code>policy enforce</code> and <code>policy observe</code>;{" "}
        <code>agents kill</code>, <code>quarantine</code> and <code>resume</code>;{" "}
        <code>policy proposals apply</code>, <code>rollback</code>, and{" "}
        <code>verify --failed</code>; <code>demo</code> and <code>admin seed</code> (they write
        demo data into the configured database); <code>admin db downgrade</code>;{" "}
        <code>admin auth issue</code> and <code>revoke</code>; any rule, boundary or escalation written with{" "}
        <code>--mode enforce</code>; <code>scan --submit</code>; and the equivalent{" "}
        <code>curl</code> calls to the control-plane API. The old command names are matched
        too. It never blocks outright, and a command it cannot parse goes through.
      </p>

      <h2 id="mcp">The read-only MCP server</h2>
      <p>
        The plugin starts an MCP server over stdio. Any other MCP client can run the same
        process:
      </p>
      <Code>{`agentfox serve mcp`}</Code>
      <p>It exposes 27 tools, all of which read or analyse:</p>
      <Code>{`agentfox admin mcp tools`}</Code>
      <Output>{`agentfox_doctor                 Reports whether this deployment is configured the way you think it is: database, traffic, authentication, detectors, modes
agentfox_findings               Returns what the platform has found (ungoverned calls, shadow agents, policy gaps) as JSON, newest first
agentfox_finding_occurrences    Findings ranked by how many times the same underlying problem has recurred, …
agentfox_agents                 Returns every agent, registered or shadow, plus an inventory summary …
agentfox_agent_lineage          Shows what an agent can reach (tools, data, other agents) up to a depth: its blast radius
agentfox_policy_list            Lists policies with their version, enforcement mode (observe or enforce) and rule count
…
agentfox_audit_verify           Verifies the tamper-evident audit chain, optionally over a sequence range
…
agentfox_guard_text             Evaluates text for an agent on one surface (input, output, retrieved, tool_result) against the policy in force, without calling a model and without recording a decision`}</Output>
      <p>
        Nothing there enforces a policy, stops an agent, issues a token, seeds data, or
        decides, applies or rolls back a proposal. The server says so in its instructions to
        the client, and asks for a person to run those with the CLI. It reads the same
        database as the CLI in that environment, so set <code>AGENTFOX_STATE_DIR</code> or{" "}
        <code>AGENTFOX_DATABASE_URL</code> for it the same way.{" "}
        <code>AGENTFOX_MCP_LOG_LEVEL</code> sets its log level.
      </p>
      <Callout kind="note">
        The plugin&apos;s <code>.mcp.json</code> starts the server with the older spelling{" "}
        <code>mcp serve</code>, which still works as an alias of <code>serve mcp</code>.
      </Callout>

      <h2>Troubleshooting</h2>
      <ul>
        <li>
          <b>&quot;agentfox is not installed&quot;</b> from a command: install it in the
          environment Claude Code was started from, or start Claude Code inside your venv.
        </li>
        <li>
          <b>The tour changed your data</b>: it should not; it uses a throwaway database. If
          you ran <code>agentfox demo</code> yourself, set <code>AGENTFOX_STATE_DIR</code> to a
          scratch directory first.
        </li>
        <li>
          <b>The MCP server shows different findings from the CLI</b>: the two processes see
          different environments, so they read different databases.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>
          The hook does not prompt on <code>agentfox permit grant</code>. The command asks for
          confirmation itself, but <code>--yes</code> skips that, so read grants an agent
          proposes before it runs them.
        </li>
        <li>The plugin is a guide for a coding agent, not a control. It governs nothing at runtime.</li>
        <li>The safety hook only sees Bash commands in a Claude Code session with the plugin enabled.</li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/guides/coding-agents", label: "Coding agents", why: "govern the coding agent's own tool calls with hooks" },
          { href: "/docs/quickstart", label: "Quickstart", why: "the path /agentfox:start follows" },
          { href: "/docs/reference/cli", label: "CLI reference", why: "every command the harness runs" },
        ]}
      />
    </article>
  );
}
