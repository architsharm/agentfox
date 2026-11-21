/**
 * The decision half of the OpenClaw plugin, kept free of OpenClaw imports so it can be
 * tested on its own. `index.ts` registers these two handlers with OpenClaw.
 *
 * Every tool call OpenClaw is about to run is sent to an AgentFox gateway's
 * `POST /v1/guard/tool_call`, and the gateway's applied verdict is turned into
 * OpenClaw's `before_tool_call` result: nothing (run it), `block`, or `requireApproval`.
 *
 * Provenance: a `before_tool_call` handler does not see the conversation, so the plugin
 * keeps the last few tool results of each session (from `after_tool_call`) and sends
 * them as `messages`. The gateway then finds an argument's value in them, so an email
 * address copied out of a fetched web page is treated as untrusted, not as the user's.
 */

export interface AgentFoxPluginConfig {
  /** The AgentFox gateway, e.g. `http://agentfox:8080`. */
  baseUrl: string;
  /** An AgentFox agent key (`nom_agt_…`). Without one, calls are recorded as shadow traffic. */
  apiKey?: string;
  /** The agent's slug in AgentFox. Default: `openclaw`, or `openclaw-<agentId>` for a named OpenClaw agent. */
  agent?: string;
  environment?: string;
  /** What to do when AgentFox cannot be reached or errors: `closed` blocks the call, `open` runs it. Default `closed`. */
  failMode?: "closed" | "open";
  /**
   * Who approves a held call. `agentfox` (default): the call is refused with a link, an
   * approver decides in the AgentFox dashboard, and the same call retried runs once.
   * `openclaw`: OpenClaw's own approval prompt, which the person chatting can answer.
   */
  approvals?: "agentfox" | "openclaw";
  /** Time to wait for AgentFox, in ms. Default 10000 (OpenClaw allows a hook 15 s). */
  timeoutMs?: number;
  /** Tool results kept per session for provenance. Default 20. */
  resultsKept?: number;
  /** Approval prompt timeout when `approvals` is `openclaw`, in ms. Default 120000. */
  approvalTimeoutMs?: number;
}

/** The parts of OpenClaw's `before_tool_call` / `after_tool_call` event the plugin reads. */
export interface ToolEvent {
  toolName: string;
  params: Record<string, unknown>;
  runId?: string;
  toolCallId?: string;
  result?: unknown;
  error?: string;
}

/** The parts of OpenClaw's hook context the plugin reads. */
export interface ToolContext {
  agentId?: string;
  sessionKey?: string;
  sessionId?: string;
  runId?: string;
  abortSignal?: AbortSignal;
}

/** OpenClaw's `before_tool_call` result, the subset the plugin returns. */
export interface BeforeToolCallResult {
  block?: boolean;
  blockReason?: string;
  requireApproval?: {
    title: string;
    description: string;
    severity?: "info" | "warning" | "critical";
    timeoutMs?: number;
    allowedDecisions?: Array<"allow-once" | "allow-always" | "deny">;
  };
}

interface GuardBody {
  verdict?: string;
  applied_verdict?: string;
  effective_verdict?: string;
  reason?: string;
  user_message?: string | null;
  approval_id?: string | null;
  explain_url?: string;
  rules_fired?: Array<{ id?: string; rule_id?: string }>;
}

/** Verdicts that stop a call, as the gateway and the TypeScript SDK define them. */
const STOPPING = new Set(["block", "escalate", "abstain"]);
/** Cap on one remembered tool result, so a large page cannot balloon every request. */
const MAX_RESULT_CHARS = 8_000;
/** Sessions remembered at once; the oldest is dropped first. */
const MAX_SESSIONS = 500;

type Fetch = typeof fetch;

export function createGuard(config: AgentFoxPluginConfig, fetchImpl: Fetch = globalThis.fetch) {
  if (!config?.baseUrl) throw new Error("agentfox: config.baseUrl is required");
  const baseUrl = config.baseUrl.replace(/\/+$/, "");
  const failMode = config.failMode ?? "closed";
  const approvals = config.approvals ?? "agentfox";
  const timeoutMs = config.timeoutMs ?? 10_000;
  const kept = Math.max(0, config.resultsKept ?? 20);
  const results = new Map<string, Array<Record<string, unknown>>>();

  const agentFor = (ctx: ToolContext) =>
    config.agent ?? (ctx.agentId && ctx.agentId !== "main" ? `openclaw-${ctx.agentId}` : "openclaw");
  const sessionFor = (ctx: ToolContext) => ctx.sessionKey ?? ctx.sessionId;

  async function guard(event: ToolEvent, ctx: ToolContext): Promise<GuardBody> {
    const session = sessionFor(ctx);
    const body = {
      agent: agentFor(ctx),
      tool: event.toolName,
      arguments: event.params ?? {},
      provenance: {},
      messages: session ? results.get(session) : undefined,
      session_id: session,
      environment: config.environment,
      // Register a tool the first time AgentFox sees it, instead of holding it as unknown.
      declare: { name: event.toolName },
      // A call an approver granted in AgentFox runs once when retried unchanged:
      // OpenClaw has no way to carry an approval id back on the retry.
      redeem_approved: approvals === "agentfox",
      in_process: "enforced",
    };
    const timeout = AbortSignal.timeout(timeoutMs);
    const signal = ctx.abortSignal ? AbortSignal.any([ctx.abortSignal, timeout]) : timeout;
    const response = await fetchImpl(`${baseUrl}/v1/guard/tool_call`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(config.apiKey ? { authorization: `Bearer ${config.apiKey}` } : {}),
      },
      body: JSON.stringify(body, (_k, v) => (v === undefined ? undefined : v)),
      signal,
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(`AgentFox returned HTTP ${response.status}${text ? `: ${text.slice(0, 200)}` : ""}`);
    }
    return (await response.json()) as GuardBody;
  }

  async function beforeToolCall(event: ToolEvent, ctx: ToolContext): Promise<BeforeToolCallResult | undefined> {
    let decision: GuardBody;
    try {
      decision = await guard(event, ctx);
    } catch (err) {
      if (failMode === "open") return undefined;
      const why = err instanceof Error ? err.message : String(err);
      return { block: true, blockReason: `AgentFox could not check this call, so it did not run (${why}).` };
    }
    // Gate on the applied verdict: a rule still in Watch mode records what it would do.
    const verdict = decision.verdict ?? decision.applied_verdict ?? "allow";
    if (!STOPPING.has(verdict)) return undefined;

    const said = (decision.user_message || decision.reason || `AgentFox stopped ${event.toolName}`).trim();
    const why = /[.!?]$/.test(said) ? said : `${said}.`;
    if (verdict !== "escalate") return { block: true, blockReason: why };

    if (approvals === "openclaw") {
      return {
        requireApproval: {
          title: `AgentFox: allow ${event.toolName}?`,
          description: why,
          severity: "warning",
          timeoutMs: config.approvalTimeoutMs ?? 120_000,
          allowedDecisions: ["allow-once", "deny"],
        },
      };
    }
    const where = decision.explain_url ? ` Review it: ${decision.explain_url}.` : " Review it in AgentFox under Approvals.";
    return {
      block: true,
      blockReason: `${why} This call is waiting for an approver in AgentFox.${where} Once it is approved, ask me to try again and it will run once.`,
    };
  }

  /** Remember a finished call's result for the session, so later arguments can be traced to it. */
  function afterToolCall(event: ToolEvent, ctx: ToolContext): void {
    const session = sessionFor(ctx);
    if (!session || kept === 0 || event.result === undefined) return;
    const raw = typeof event.result === "string" ? event.result : safeJson(event.result);
    if (!raw) return;
    const list = results.get(session) ?? [];
    list.push({
      role: "tool",
      tool_call_id: event.toolCallId ?? `${event.toolName}-${list.length}`,
      name: event.toolName,
      content: raw.slice(0, MAX_RESULT_CHARS),
    });
    if (list.length > kept) list.splice(0, list.length - kept);
    results.delete(session); // re-insert so this session counts as the newest
    results.set(session, list);
    if (results.size > MAX_SESSIONS) results.delete(results.keys().next().value as string);
  }

  return { beforeToolCall, afterToolCall, agentFor };
}

function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value);
  } catch {
    return "";
  }
}
