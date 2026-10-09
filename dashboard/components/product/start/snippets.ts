/**
 * Every "paste this" on Get started and Settings > Connections, built from one
 * place so the two pages cannot drift. Each snippet has this deployment's gateway
 * URL and the chosen agent already in it; the key is read from AGENTFOX_TOKEN so
 * nothing secret ends up in a snippet someone pastes into a ticket.
 */

export type Snippet = { label: string; code: string };

export type PathKey = "http" | "python" | "typescript" | "openai" | "claude-code" | "codex" | "otlp";

export const PATHS: { key: PathKey; label: string }[] = [
  { key: "http", label: "HTTP" },
  { key: "python", label: "Python" },
  { key: "typescript", label: "TypeScript" },
  { key: "openai", label: "OpenAI-compatible" },
  { key: "claude-code", label: "Claude Code" },
  { key: "codex", label: "Codex" },
  { key: "otlp", label: "OpenTelemetry" },
];

/** Paths that run in the user's process and write to the database it is configured with. */
export const SAME_DB: PathKey[] = ["claude-code", "codex"];

export const SAME_DB_NOTE =
  "Runs on your machine and records to the AgentFox database it is configured with. It shows up here when that is this gateway's database, as in a self-hosted install.";

export const PATH_NOTE: Record<PathKey, string> = {
  http: "Ask before each tool call. Branch on verdict: allow, redact, escalate or block.",
  python: "Check each message and tool call from your agent's code.",
  typescript: "Check each message and tool call from your agent's code.",
  openai: "Point your existing client at the gateway. Every model call is checked and traced.",
  "claude-code": "Hooks check Claude Code's shell commands, edits and MCP calls before they run.",
  codex: "Hooks check Codex's shell commands, edits and MCP calls before they run.",
  otlp: "Send the traces you already export. Observes only; nothing is blocked.",
};

export function snippetsFor(path: PathKey, gateway: string, agent: string): Snippet[] {
  const a = agent || "my-agent";
  switch (path) {
    case "http":
      return [
        {
          label: "Check a tool call",
          code: `curl -s -X POST ${gateway}/v1/guard/tool_call \\
  -H "Authorization: Bearer $AGENTFOX_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"agent": "${a}",
       "tool": "payments.transfer",
       "arguments": {"amount": 250},
       "provenance": {"amount": "user"}}'`,
        },
      ];
    case "python":
      return [
        { label: "Install", code: "pip install agentfox" },
        {
          label: "In your agent",
          code: `import os
from agentfox import AgentFox

fox = AgentFox(
    agent="${a}",
    base_url="${gateway}",
    api_key=os.environ["AGENTFOX_TOKEN"],
)

decision = fox.check(user_text)
if decision["verdict"] in ("block", "escalate"):
    ...`,
        },
      ];
    case "typescript":
      return [
        { label: "Install", code: "npm install @agentfox/sdk" },
        {
          label: "In your agent",
          code: `import { AgentFox } from "@agentfox/sdk";

const fox = new AgentFox({
  baseUrl: "${gateway}",
  agent: "${a}",
  apiKey: process.env.AGENTFOX_TOKEN,
});

const input = await fox.guardInput(userText);
if (input.stopped) return input.userMessage;`,
        },
      ];
    case "openai":
      return [
        {
          label: "Python",
          code: `from openai import OpenAI

client = OpenAI(
    base_url="${gateway}/v1",
    default_headers={"X-AgentFox-Agent": "${a}"},
)`,
        },
        {
          label: "TypeScript",
          code: `import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "${gateway}/v1",
  defaultHeaders: { "X-AgentFox-Agent": "${a}" },
});`,
        },
      ];
    case "claude-code":
      return [
        {
          label: "In the repository",
          code: `pip install agentfox
agentfox admin hooks install --agent ${a} --write`,
        },
      ];
    case "codex":
      return [
        {
          label: "In the repository",
          code: `pip install agentfox
agentfox admin hooks install --harness codex --agent ${a} --write
agentfox admin hooks daemon`,
        },
      ];
    case "otlp":
      return [
        {
          label: "Exporter settings",
          code: `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${gateway}/v1/traces
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer%20$AGENTFOX_TOKEN"
OTEL_SERVICE_NAME=${a}`,
        },
      ];
  }
}
