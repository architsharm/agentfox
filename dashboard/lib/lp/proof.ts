/**
 * Every number the landing-page variants quote, in one place, each with the file
 * it comes from. A page imports from here rather than typing a figure, so the
 * three variants and the benchmark page cannot disagree with each other or drift
 * from the benchmark write-ups they cite.
 *
 * Rule for editing: change a number here only after the cited README changes.
 */

import { REPO_URL } from "@/lib/site";

const blob = (path: string) => `${REPO_URL}/blob/main/${path}`;

export const SOURCES = {
  agentdojoH2H: blob("benchmarks/head_to_head/README.md"),
  containment: blob("benchmarks/containment/README.md"),
  latencyH2H: blob("benchmarks/latency/head_to_head/README.md"),
  latency: blob("benchmarks/latency/README.md"),
  injection: blob("benchmarks/REPORT.md"),
  agentSecurity: blob("benchmarks/agent_security/README.md"),
  actionSafety: blob("benchmarks/action_safety/README.md"),
} as const;

export type Row = {
  name: string;
  value: number;
  /** What the bar's label prints. */
  label: string;
  note?: string;
  ours?: boolean;
};

/** AgentDojo v1.2.2: 588 attack pairs whose injection issues a write or irreversible call. */
export const AGENTDOJO = {
  attacks: 588,
  benignTasks: 97,
  gotThrough: [
    { name: "No guardrail", value: 588, label: "588" },
    { name: "LLM Guard", value: 86, label: "86", note: "14.6%" },
    { name: "AgentFox", value: 0, label: "0", ours: true },
  ] satisfies Row[],
  benignCompleted: { llmGuard: 42, agentfox: 24 },
  /** llm-guard: one scan per tool output. AgentFox full: the call check plus a check of its result. */
  perToolCallMs: { llmGuard: 72, agentfox: 16, containmentOnly: 7 },
  source: SOURCES.agentdojoH2H,
};

/** Same 880 messages, one M1 Pro, CPU only, one request at a time. Short messages, p50 ms. */
export const LATENCY_H2H: (Row & { checks: string; p95: number })[] = [
  { name: "Meta Prompt Guard 2 (22M)", value: 25.5, p95: 29.9, label: "25 ms", checks: "Injection" },
  { name: "LLM Guard, injection scanner", value: 56.1, p95: 66.2, label: "56 ms", checks: "Injection" },
  {
    name: "AgentFox default",
    value: 63.1,
    p95: 77.6,
    label: "63 ms",
    checks: "Injection, PII, secrets, unsafe content, code",
    ours: true,
  },
  { name: "Guardrails AI, jailbreak validator", value: 99.4, p95: 107, label: "99 ms", checks: "Jailbreak" },
  { name: "LLM Guard, nine default scanners", value: 249, p95: 316, label: "249 ms", checks: "Several" },
  { name: "OpenAI moderation (hosted)", value: 387, p95: 484, label: "387 ms", checks: "Harm categories" },
  { name: "NeMo Guardrails, self-check rail", value: 758, p95: 1049, label: "758 ms", checks: "One LLM policy check" },
];

/** 41,520 recorded checks replayed from 109 real agent repositories. */
export const LATENCY_FIELD = {
  repos: 109,
  checks: 41520,
  deterministicP50: 2.3,
  defaultP50: 57.4,
  defaultP95: 302,
  toolCallMs: 3,
  source: SOURCES.latency,
};

/**
 * False positives (NotInject, 339 benign) and recall (deepset held-out, 60 attacks),
 * each model alone at its published default threshold. AgentFox is the shipped
 * enforcing verdict (PIGuard plus the heuristic).
 */
export const FALSE_FLAGS = {
  notInject: 339,
  rows: [
    { name: "LLM Guard's model (ProtectAI DeBERTa v2)", flagged: "42.2%", caught: "31.7%" },
    { name: "Meta Prompt Guard 2 (86M)", flagged: "3.5%", caught: "20.0%" },
    { name: "AgentFox", flagged: "11.5%", caught: "68.3%", ours: true },
  ],
  toolOutputs: { total: 339, llmGuard: 82, agentfox: 0 },
  source: SOURCES.injection,
};

/** Structural agent attacks, against an independently installed llm-guard. */
export const AGENT_TIERS = [
  {
    test: "One attack split across 3 messages",
    llmGuard: "Flagged all 3 fragments on their own",
    agentfox: "Caught the assembled attack only",
  },
  {
    test: "Attacks hidden in tool output (10 attacks, 10 harmless)",
    llmGuard: "9 of 10 caught, 81.8% precision",
    agentfox: "10 of 10 caught, 66.7% precision",
  },
  {
    test: "Attacks in tool arguments (5 attacks, 5 harmless)",
    llmGuard: "Cannot check structured arguments",
    agentfox: "5 of 5 blocked",
  },
  {
    test: "Agent exceeding its permissions (6 scenarios)",
    llmGuard: "No permission model",
    agentfox: "5 of 6 correct",
  },
];

export const ACTION_SAFETY = {
  destructiveSql: "100%",
  sqlInjectionRecall: "89.3%",
  source: SOURCES.actionSafety,
};

/** The command that reruns each comparison, as its README gives it. */
export const RERUN = {
  agentdojo: "PYTHONPATH=src .venv/bin/python -m benchmarks.head_to_head.run_agentdojo_h2h",
  latency: "python benchmarks/latency/head_to_head/run_agentfox.py agentfox-L2",
  falseflags: "uv run python -m benchmarks.generalization.run_generalization_benchmark",
  agents: "uv run python -m benchmarks.agent_security.tier_b_indirect_injection",
} as const;

export const METHOD_NOTE =
  "Apple M1 Pro laptop, CPU only, uv-managed Python 3.12, one request at a time. Times exclude the agent's own model call.";
