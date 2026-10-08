import Link from "next/link";
import { CodeSnippet } from "@/components/product/start/CodeSnippet";

/**
 * "How do I hook my agent up" — one choice, then the exact thing to paste.
 *
 * The checklist below this used to be the only answer, and it mixed an HTTP
 * endpoint, a Python one-liner, a pip install and a CLI command in one list, so a
 * developer had to work out which of them applied to them. Here they pick how
 * their agent is built, and get one snippet with this deployment's gateway URL
 * already in it.
 *
 * The in-process paths (Python `auto()`, Claude Code hooks) record to the
 * database their own process is configured with. They only show up on this
 * dashboard when that is the same database its gateway uses — true for a
 * self-hosted install, not for the hosted one — so each says so rather than
 * letting a hosted user paste it and wait for a request that never arrives.
 */
export const PATHS = [
  { key: "http", label: "Any language (HTTP)" },
  { key: "proxy", label: "OpenAI-compatible client" },
  { key: "python", label: "Python, in-process" },
  { key: "claude-code", label: "Claude Code" },
  { key: "scan", label: "Scan a repo or API" },
] as const;

export type PathKey = (typeof PATHS)[number]["key"];

const SAME_DB_NOTE =
  "Runs inside your process and records to the AgentFox database it is configured with (AGENTFOX_DATABASE_URL). It appears here when that is the database this dashboard's gateway uses, as in a self-hosted install. On the hosted product, use HTTP or the OpenAI-compatible client instead.";

export function ConnectGuide({ path, gateway }: { path: PathKey; gateway: string }) {
  return (
    <div className="panel body connect-guide">
      <div className="chipbar" role="tablist" aria-label="How your agent is built">
        {PATHS.map((p) => (
          <Link
            key={p.key}
            href={p.key === "http" ? "/app/start" : `/app/start?path=${p.key}`}
            className={path === p.key ? "chip active" : "chip"}
            role="tab"
            aria-selected={path === p.key}
            scroll={false}
          >
            {p.label}
          </Link>
        ))}
      </div>

      {path === "http" && (
        <>
          <p className="small">
            Before your agent runs a tool, ask whether it may. Works from any language. Branch on{" "}
            <span className="mono">verdict</span>: <span className="mono">allow</span>,{" "}
            <span className="mono">redact</span>, <span className="mono">escalate</span> (wait for a
            person) or <span className="mono">block</span>.
          </p>
          <CodeSnippet
            label="Check a tool call"
            code={`curl -s -X POST ${gateway}/v1/guard/tool_call \\
  -H "Authorization: Bearer $AGENTFOX_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"agent": "my-agent",
       "tool": "payments.transfer",
       "arguments": {"amount": 250},
       "provenance": {"amount": "user"},
       "intent": "refund a duplicate charge"}'`}
          />
          <p className="small muted">
            Also available: <span className="mono">/v1/guard/input</span>,{" "}
            <span className="mono">/v1/guard/output</span>, <span className="mono">/v1/guard/memory_write</span>,{" "}
            <span className="mono">/v1/guard/agent_message</span> and <span className="mono">/v1/mcp/call</span>.
          </p>
        </>
      )}

      {path === "proxy" && (
        <>
          <p className="small">
            Point your existing client at the gateway and change nothing else. Every model call is
            traced and checked, and the decision comes back in <span className="mono">x-agentfox-*</span>{" "}
            response headers.
          </p>
          <CodeSnippet
            label="Python"
            code={`from openai import OpenAI

client = OpenAI(
    base_url="${gateway}/v1",
    default_headers={"X-AgentFox-Agent": "my-agent"},
)`}
          />
          <CodeSnippet
            label="TypeScript"
            code={`import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "${gateway}/v1",
  defaultHeaders: { "X-AgentFox-Agent": "my-agent" },
});`}
          />
          <p className="small muted">
            A held call returns HTTP 428 with an approval id. Approve it on Approvals, then resend with
            the header <span className="mono">X-AgentFox-Approval</span>.
          </p>
        </>
      )}

      {path === "python" && (
        <>
          <p className="small">One line in your entry point traces every OpenAI, Anthropic, LiteLLM and LangChain call in the process.</p>
          <CodeSnippet label="Install" code="pip install agentfox" />
          <CodeSnippet
            label="In your entry point"
            code={`import agentfox

agentfox.auto(agent="my-agent")`}
          />
          <p className="small muted">{SAME_DB_NOTE}</p>
        </>
      )}

      {path === "claude-code" && (
        <>
          <p className="small">
            Governs Claude Code itself: writes the hooks, registers the agent, and grants its built-in
            tools so ordinary work is not refused. Destructive commands still are.
          </p>
          <CodeSnippet
            label="In the repository"
            code={`pip install agentfox
agentfox admin hooks install --agent my-coding-agent --write`}
          />
          <p className="small muted">{SAME_DB_NOTE}</p>
        </>
      )}

      {path === "scan" && (
        <p className="small">
          Not ready to change code? Connect a GitHub repository or point at a hosted API&rsquo;s
          OpenAPI document. Read only: source is parsed, never run, and nothing goes live until you
          approve it. <Link href="/app/start?tab=connect">Open Settings → Connections →</Link>
        </p>
      )}

      {(path === "http" || path === "proxy") && (
        <p className="small muted" style={{ marginBottom: 0 }}>
          Your code needs an API key in <span className="mono">AGENTFOX_TOKEN</span>.{" "}
          <Link href="/app/start?tab=tokens">Create one in Settings → API keys</Link> — it is shown once.
        </p>
      )}
    </div>
  );
}
