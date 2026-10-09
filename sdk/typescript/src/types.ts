/**
 * Wire types for the AgentFox guard endpoints.
 *
 * Request bodies mirror `GuardContentRequest` and `GuardToolCallRequest` in
 * `src/agentfox/apps/gateway/routes/inline.py`; the response mirrors
 * `EnforcementResult.to_json()` plus the `applied_verdict` / `would_be_verdict`
 * aliases the gateway adds (`gateway/verdicts.py`).
 */

/** `allow`, `block`, `escalate`, `redact`, `mask`, `tokenize`, `abstain`, ... */
export type Verdict = string;

export interface RuleFired {
  rule_id: string;
  effect?: string;
  reason?: string;
  message?: string;
  on_block?: string;
  [key: string]: unknown;
}

/** The JSON body `/v1/guard/input`, `/v1/guard/output` and `/v1/guard/tool_call` return. */
export interface GuardResponseBody {
  verdict: Verdict;
  applied_verdict?: Verdict;
  effective_verdict: Verdict;
  would_be_verdict?: Verdict;
  mode: string;
  content: string | null;
  decision_id: string | null;
  trace_id: string | null;
  approval_id: string | null;
  policy_version: string | null;
  rules_fired: RuleFired[];
  entities: string[];
  findings: Record<string, unknown>[];
  taint: Record<string, unknown>;
  latency_ms: number;
  degraded: string[];
  reason: string;
  explanation: Record<string, unknown>;
  suppressed: Record<string, unknown>[];
  latency_budget: Record<string, unknown>;
  user_message: string | null;
  fix: { instruction: string } | null;
  explain_url?: string;
}

/** Body of `POST /v1/guard/input` and `POST /v1/guard/output`. */
export interface GuardContentRequest {
  agent: string;
  content: string;
  surface?: string;
  taint_source?: string;
  intent?: string;
  session_id?: string;
  trace_id?: string;
  environment?: string;
  context?: string[];
  completion?: Record<string, unknown>;
  usage?: Usage;
}

/** What a model call cost: tokens and model name, or a price you already know. */
export interface Usage {
  model?: string;
  input_tokens?: number;
  output_tokens?: number;
  cost_usd?: number;
}

/** Body of `POST /v1/guard/tool_call`. */
export interface GuardToolCallRequest {
  agent: string;
  tool: string;
  arguments: Record<string, unknown>;
  provenance: Record<string, string>;
  intent?: string;
  prior_tools?: string[];
  prior_steps?: Record<string, unknown>[];
  session_id?: string;
  environment?: string;
  approval_id?: string;
}

/** A guard decision, with camelCase names and the two verdicts kept apart. */
export interface GuardResult {
  /** What happened to this request (the applied verdict). Gate on this one. */
  verdict: Verdict;
  /** What the bound policy says should happen. In observe mode, the one that did not take effect. */
  effectiveVerdict: Verdict;
  mode: string;
  /** `verdict === "block"`. */
  blocked: boolean;
  /** `verdict === "escalate"`: held for a person; see `approvalId`. */
  escalated: boolean;
  /** The applied verdict stops the request: block, escalate or abstain. */
  stopped: boolean;
  rulesFired: RuleFired[];
  entities: string[];
  /** The deciding rule's message, safe to show the end user. */
  userMessage: string | null;
  /** When a re-ask rule fired on an output: the correction to send the model. */
  fix: { instruction: string } | null;
  approvalId: string | null;
  traceId: string | null;
  decisionId: string | null;
  reason: string;
  /** The rewritten text when the applied verdict redacts, masks or tokenizes. */
  content: string | null;
  explainUrl: string | null;
  /** The response body as the gateway sent it. */
  raw: GuardResponseBody;
}

export interface AgentFoxOptions {
  /** The gateway, e.g. `http://localhost:8080`. */
  baseUrl: string;
  /** An agent key (`Authorization: Bearer ...`). Optional; without it traffic is recorded as shadow traffic. */
  apiKey?: string;
  /** The agent's slug. */
  agent: string;
  /** `production` unless set. */
  environment?: string;
  /** Request timeout in milliseconds. Default 30000. */
  timeoutMs?: number;
  /** A `fetch` to use instead of the global one. */
  fetch?: typeof fetch;
}

export interface ContentOptions {
  intent?: string;
  sessionId?: string;
  /** Tie an input check and its output check into one trace. */
  traceId?: string;
  environment?: string;
  /** Where the content came from: `user` (default), `retrieved`, `tool_result`, ... */
  taintSource?: string;
}

export interface OutputOptions extends ContentOptions {
  /** The passages the answer was built from, for the grounding checks. */
  context?: string[];
  /** The model call's tokens, so the run shows what it cost. */
  usage?: Usage;
}

export interface ToolCallOptions {
  intent?: string;
  sessionId?: string;
  environment?: string;
  /** Tools already called in this run, oldest first. */
  priorTools?: string[];
  /** Step history (tool, arguments, observation) for loop detection. */
  priorSteps?: Record<string, unknown>[];
  /** Retry of a call a person approved: it runs once. */
  approvalId?: string;
}

export interface WrapToolOptions<A, R> {
  /** The AgentFox tool key, e.g. `payments.refund`. */
  tool: string;
  /** Where each argument came from, by path: `{ "to": "retrieved" }`. */
  provenance?: Record<string, string>;
  /** Called on a stopped call instead of throwing; its return value is returned. */
  onBlock?: (result: GuardResult, args: A) => R | Promise<R>;
  /** Options sent with every check. */
  options?: ToolCallOptions;
}

export interface Approval {
  id: string;
  status: "pending" | "approved" | "denied" | "expired" | "used" | string;
  reason?: string;
  tool?: string;
  arguments?: Record<string, unknown>;
  [key: string]: unknown;
}
