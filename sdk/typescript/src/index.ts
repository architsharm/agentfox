/**
 * AgentFox client for TypeScript and JavaScript. Dependency-free: uses the global `fetch`.
 *
 *   const fox = new AgentFox({ baseUrl: "http://localhost:8080", agent: "support-triage" });
 *   const decision = await fox.guardInput(userText);
 *   if (decision.stopped) return decision.userMessage ?? "Sorry, I can't help with that.";
 */

import type {
  AgentFoxOptions,
  Approval,
  ContentOptions,
  GuardContentRequest,
  GuardResponseBody,
  GuardResult,
  GuardToolCallRequest,
  OutputOptions,
  ToolCallOptions,
  WrapToolOptions,
} from "./types.js";

export type * from "./types.js";

/** Applied verdicts after which the request did not go through as asked. */
export const STOPPING_VERDICTS: ReadonlySet<string> = new Set(["block", "escalate", "abstain"]);

/** Any non-2xx answer from the gateway. */
export class AgentFoxHttpError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`AgentFox gateway answered ${status}`);
    this.name = "AgentFoxHttpError";
  }
}

/** Base of the errors thrown because a decision stopped a call. */
export class AgentFoxError extends Error {
  constructor(
    message: string,
    readonly result: GuardResult,
  ) {
    super(message);
    this.name = "AgentFoxError";
  }
  get traceId(): string | null {
    return this.result.traceId;
  }
}

/** A decision blocked the call. */
export class PolicyViolation extends AgentFoxError {
  constructor(result: GuardResult) {
    super(result.reason || "blocked by policy", result);
    this.name = "PolicyViolation";
  }
}

/** A decision held the call for a person. Retry with `approvalId` once it is approved. */
export class ApprovalRequired extends AgentFoxError {
  constructor(result: GuardResult) {
    super(result.reason || "human approval required", result);
    this.name = "ApprovalRequired";
  }
  get approvalId(): string | null {
    return this.result.approvalId;
  }
}

/** Turn a guard response body into a `GuardResult`. */
export function toResult(body: GuardResponseBody): GuardResult {
  const verdict = body.verdict ?? body.applied_verdict ?? "allow";
  return {
    verdict,
    effectiveVerdict: body.effective_verdict ?? body.would_be_verdict ?? "allow",
    mode: body.mode ?? "observe",
    blocked: verdict === "block",
    escalated: verdict === "escalate",
    stopped: STOPPING_VERDICTS.has(verdict),
    rulesFired: body.rules_fired ?? [],
    entities: body.entities ?? [],
    userMessage: body.user_message ?? null,
    fix: body.fix ?? null,
    approvalId: body.approval_id ?? null,
    traceId: body.trace_id ?? null,
    decisionId: body.decision_id ?? null,
    reason: body.reason ?? "",
    content: body.content ?? null,
    explainUrl: body.explain_url ?? null,
    raw: body,
  };
}

function compact<T extends object>(value: T): T {
  return Object.fromEntries(
    Object.entries(value).filter(([, v]) => v !== undefined),
  ) as T;
}

export class AgentFox {
  readonly baseUrl: string;
  readonly agent: string;
  readonly environment?: string;
  private readonly apiKey?: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(options: AgentFoxOptions) {
    if (!options.baseUrl) throw new Error("AgentFox: baseUrl is required");
    if (!options.agent) throw new Error("AgentFox: agent is required");
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.agent = options.agent;
    this.apiKey = options.apiKey;
    this.environment = options.environment;
    this.timeoutMs = options.timeoutMs ?? 30_000;
    const f = options.fetch ?? globalThis.fetch;
    if (!f) throw new Error("AgentFox: no global fetch; pass options.fetch");
    this.fetchImpl = f;
  }

  /** Check user input. `POST /v1/guard/input`. */
  async guardInput(content: string, opts: ContentOptions = {}): Promise<GuardResult> {
    return this.guardContent("/v1/guard/input", content, "input", opts);
  }

  /** Check model output. `POST /v1/guard/output`. */
  async guardOutput(content: string, opts: OutputOptions = {}): Promise<GuardResult> {
    return this.guardContent("/v1/guard/output", content, "output", opts);
  }

  /** Authorise a tool call before running it. `POST /v1/guard/tool_call`. */
  async guardToolCall(
    tool: string,
    args: Record<string, unknown>,
    provenance: Record<string, string> = {},
    opts: ToolCallOptions = {},
  ): Promise<GuardResult> {
    const body: GuardToolCallRequest = compact({
      agent: this.agent,
      tool,
      arguments: args,
      provenance,
      intent: opts.intent,
      prior_tools: opts.priorTools,
      prior_steps: opts.priorSteps,
      session_id: opts.sessionId,
      environment: opts.environment ?? this.environment,
      approval_id: opts.approvalId,
    });
    return toResult(await this.request<GuardResponseBody>("POST", "/v1/guard/tool_call", body));
  }

  /**
   * Wrap a tool so every call is authorised first. The tool takes one arguments object.
   * A stopped call throws `PolicyViolation` or `ApprovalRequired`, unless `onBlock` is given.
   */
  wrapTool<A extends Record<string, unknown>, R>(
    fn: (args: A) => R | Promise<R>,
    options: WrapToolOptions<A, R>,
  ): (args: A) => Promise<R> {
    return async (args: A): Promise<R> => {
      const result = await this.guardToolCall(
        options.tool,
        args,
        options.provenance ?? {},
        options.options ?? {},
      );
      if (result.stopped) {
        if (options.onBlock) return options.onBlock(result, args);
        throw result.escalated ? new ApprovalRequired(result) : new PolicyViolation(result);
      }
      return fn(args);
    };
  }

  /** An approval's current state. `GET /api/approvals/{id}`; an agent key may read its own. */
  async approval(approvalId: string): Promise<Approval> {
    return this.request<Approval>("GET", `/api/approvals/${encodeURIComponent(approvalId)}`);
  }

  /** Poll until a person decides. Returns `approved`, `denied`, `expired`, or `pending` on timeout. */
  async waitForApproval(
    approvalId: string,
    { timeoutMs = 1_800_000, intervalMs = 2_000 }: { timeoutMs?: number; intervalMs?: number } = {},
  ): Promise<string> {
    const deadline = Date.now() + Math.max(0, timeoutMs);
    for (;;) {
      const status = String((await this.approval(approvalId)).status ?? "pending");
      if (status !== "pending") return status;
      const remaining = deadline - Date.now();
      if (remaining <= 0) return "pending";
      await new Promise((resolve) => setTimeout(resolve, Math.min(intervalMs, remaining)));
    }
  }

  private async guardContent(
    path: string,
    content: string,
    surface: string,
    opts: OutputOptions,
  ): Promise<GuardResult> {
    const body: GuardContentRequest = compact({
      agent: this.agent,
      content,
      surface,
      taint_source: opts.taintSource,
      intent: opts.intent,
      session_id: opts.sessionId,
      trace_id: opts.traceId,
      environment: opts.environment ?? this.environment,
      context: opts.context,
      usage: opts.usage,
    });
    return toResult(await this.request<GuardResponseBody>("POST", path, body));
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { accept: "application/json" };
    if (body !== undefined) headers["content-type"] = "application/json";
    if (this.apiKey) headers.authorization = `Bearer ${this.apiKey}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      const text = await response.text();
      let parsed: unknown = text;
      try {
        parsed = text ? JSON.parse(text) : null;
      } catch {
        // not JSON; keep the text for the error
      }
      if (!response.ok) throw new AgentFoxHttpError(response.status, parsed);
      return parsed as T;
    } finally {
      clearTimeout(timer);
    }
  }
}

export default AgentFox;
