/**
 * The words the dashboard uses, in one place.
 *
 * Internal identifiers (`capability.denied`, `escalate`, `tool_result`) stay in the
 * API and the audit log. Screens show these instead, so the same thing is called
 * the same name on every page.
 */

export type Outcome = "allowed" | "masked" | "held" | "blocked";

export const OUTCOMES: { key: Outcome; label: string }[] = [
  { key: "allowed", label: "Allowed" },
  { key: "masked", label: "Masked" },
  { key: "held", label: "Held" },
  { key: "blocked", label: "Blocked" },
];

export function outcomeOf(verdict?: string | null): Outcome {
  switch (verdict) {
    case "block":
      return "blocked";
    case "escalate":
      return "held";
    case "redact":
    case "mask":
    case "tokenize":
      return "masked";
    default:
      return "allowed";
  }
}

/** A rule's action, as the customer would say it. */
export const ACTIONS: Record<string, string> = {
  allow: "Allow",
  redact: "Mask",
  mask: "Mask",
  tokenize: "Mask",
  abstain: "Refuse",
  block: "Block",
  escalate: "Ask a human",
};

/** Actions offered when changing a rule. */
export const ACTION_CHOICES: { effect: string; label: string }[] = [
  { effect: "block", label: "Block" },
  { effect: "escalate", label: "Ask a human" },
  { effect: "redact", label: "Mask" },
  { effect: "allow", label: "Log only" },
];

/** Detection sensitivity as a customer thinks of it; each is a detection threshold. */
export const SENSITIVITY: { key: string; label: string; minScore: number }[] = [
  { key: "low", label: "Low", minScore: 0.9 },
  { key: "medium", label: "Medium", minScore: 0.7 },
  { key: "high", label: "High", minScore: 0.5 },
];

/** The sensitivity level nearest a threshold. */
export function sensitivityOf(minScore: number | null): string | null {
  if (minScore === null) return null;
  return SENSITIVITY.reduce((a, b) => (Math.abs(b.minScore - minScore) < Math.abs(a.minScore - minScore) ? b : a)).key;
}

export const MODES: Record<string, string> = {
  observe: "Watching",
  enforce: "Enforcing",
};

export const IMPACT: Record<string, string> = {
  read: "Read only",
  write: "Writes",
  high_impact: "High impact",
  irreversible: "Irreversible",
};

/** How far a tool may trust where its argument values came from. */
export const TRUST: { key: string; label: string }[] = [
  { key: "none", label: "System only" },
  { key: "user", label: "User input" },
  { key: "retrieved", label: "+ documents" },
  { key: "tool_result", label: "+ tool output" },
  { key: "subagent", label: "+ other agents" },
  { key: "memory", label: "Anything" },
];

export const RANGES = [
  { key: "24h", label: "24h" },
  { key: "7d", label: "7d" },
  { key: "30d", label: "30d" },
  { key: "90d", label: "90d" },
] as const;

export type RangeKey = (typeof RANGES)[number]["key"];

/** A range in words, for labels: "Requests · 30 days". */
export const RANGE_WORDS: Record<RangeKey, string> = { "24h": "24 hours", "7d": "7 days", "30d": "30 days", "90d": "90 days" };

export function rangeOf(value?: string | null): RangeKey {
  return (RANGES.find((r) => r.key === value)?.key || "7d") as RangeKey;
}

// --- Rules -------------------------------------------------------------------

export type Category = { key: string; label: string };

export const CATEGORIES: Category[] = [
  { key: "custom", label: "Your rules" },
  { key: "attacks", label: "Prompt attacks" },
  { key: "data", label: "Sensitive data" },
  { key: "actions", label: "Risky actions" },
  { key: "content", label: "Harmful content" },
  { key: "quality", label: "Wrong results" },
  { key: "cost", label: "Cost & loops" },
  { key: "compliance", label: "Compliance" },
  { key: "platform", label: "Platform safety" },
];

const RULE_TITLES: Record<string, string> = {
  "injection.direct": "Jailbreaks & prompt injection",
  "injection.indirect": "Injection in documents or tool results",
  "injection.system_prompt_leak": "System prompt extraction",
  "injection.memory_and_agent_message": "Injection via memory or other agents",
  "injection.adopted_in_reasoning": "Injected instructions in reasoning",
  "injection.in_tool_arguments": "Injected instructions in tool calls",
  "secrets.block": "Secrets & API keys",
  "secrets.credential_file": "Credential files",
  "secrets.in_tool_arguments": "Secrets sent to tools",
  "pii.outbound_redact": "Personal data in replies",
  "pii.inbound_tokenize": "Personal data sent to models",
  "pii.high_sensitivity": "ID numbers & payment cards",
  "pii.memory_and_agent_message": "Personal data in memory or between agents",
  "safety.harm": "Harmful or toxic content",
  "schema.violation": "Reply in the wrong format",
  "pipeline.degraded_high_risk": "High-risk agent with degraded checks",
  "eu.art14.human_oversight": "Human sign-off on irreversible actions",
  "eu.art14.no_covert_action": "Acting without telling the user",
  "eu.art15.no_degraded_enforcement": "Degraded protection on high-risk agents",
  "eu.art15.injection_resistance": "Hijack attempts on high-risk agents",
  "eu.art10.special_category_data": "Special-category data to third parties",
  "eu.art50.impersonation": "AI claiming to be human",
  "eu.art5.prohibited_tier": "Prohibited AI systems",
  "taint.irreversible_tool": "Irreversible actions on untrusted data",
  "taint.high_impact_tool": "High-impact actions on untrusted data",
  "taint.write_from_tool_result": "Writes copied from tool output",
  "capability.denied": "Tools the agent wasn't given",
  "capability.constraint_violated": "Calls outside allowed limits",
  "capability.approval_required": "Actions that need approval",
  "intent.undeclared_irreversible": "Irreversible action with no task",
  "budget.exceeded": "Spending or usage limit",
  "loop.runaway": "Runaway loops",
  "completion.unverified_claim": "Done without proof",
  "completion.irreversible_unconfirmed": "Irreversible action not confirmed",
  "tool.not_declared": "Unknown or made-up tools",
  "action.remote_code_execution": "Running downloaded code",
  "action.supply_chain_publish": "Publishing packages",
  "action.infrastructure_mutation": "Changing live infrastructure",
  "action.history_rewrite": "Destroying history",
  "control_plane.tamper": "Disabling AgentFox",
  "cascade.reaches_destructive": "Triggers a destructive action",
  "cascade.reaches_notification": "Triggers an unrecallable message",
  "cascade.cycle": "Trigger loops",
  "cascade.blast_radius": "Large blast radius",
  "access.unscoped_table": "Queries beyond the caller's rows",
  "access.undeclared_table": "Queries on undeclared tables",
  "intent.misaligned": "Actions off the user's task",
  "code.insecure": "Insecure code",
  "grounding.unsupported": "Answers not backed by sources",
};

/** A rule's name. Custom rules are named by their author: pass the rule's description. */
export function ruleTitle(ruleId: string, description?: string): string {
  if (RULE_TITLES[ruleId]) return RULE_TITLES[ruleId];
  // A fired custom rule carries its name in its reason: "<name> — your rule".
  if (ruleId.startsWith("custom.") && description) return description.split(" — your rule")[0];
  const tail = ruleId.split(".").slice(1).join(" ") || ruleId;
  const words = tail.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function ruleCategory(ruleId: string): string {
  const head = ruleId.split(".")[0];
  if (head === "custom") return "custom";
  if (head === "injection") return "attacks";
  if (head === "pii" || head === "secrets") return "data";
  if (head === "safety") return "content";
  if (head === "eu" || head === "disclosure") return "compliance";
  if (head === "budget" || head === "loop") return "cost";
  if (head === "schema" || head === "completion" || head === "grounding" || ruleId === "tool.not_declared" || head === "answerability")
    return "quality";
  if (head === "control_plane" || head === "pipeline") return "platform";
  return "actions";
}

export function categoryLabel(key: string): string {
  return CATEGORIES.find((c) => c.key === key)?.label || key;
}

export function severityRank(s?: string | null): number {
  return { critical: 0, high: 1, medium: 2, low: 3 }[s || ""] ?? 4;
}

const DETECTORS: Record<string, string> = {
  "injection.heuristic": "Prompt injection",
  "injection.classifier": "Prompt injection (model)",
  "pii.native": "Personal data",
  "pii.presidio": "Personal data (Presidio)",
  "secrets.native": "Secrets",
  "safety.lexicon": "Harmful content",
  "safety.classifier": "Harmful content (model)",
  "schema.json": "Output format",
  "custom.lists": "Your words & patterns",
  "custom.topics": "Topics (model)",
  "custom.models": "Your models",
  "code.insecure": "Insecure code",
  "grounding.nli": "Grounding (model)",
  "injection.similarity": "Prompt injection (similarity)",
  "injection.judgment": "Prompt injection (judge)",
  "pii.judgment": "Personal data (judge)",
  "safety.granite": "Harmful content (Granite Guardian)",
  "safety.restricted": "Harmful content (restricted model)",
  "rails.nemo": "NeMo Guardrails",
  "rails.guardrails_ai": "Guardrails AI",
};

export function detectorName(key: string): string {
  return DETECTORS[key] || key;
}

/** A dimension value the backend could not attribute. */
export function dimLabel(key: string): string {
  return key === "(unknown)" ? "Not recorded" : key;
}

/** Where in a request a check ran. */
export const SURFACES: Record<string, string> = {
  input: "User message",
  output: "Agent reply",
  completion: "Task completion",
  tool_call: "Tool call",
  tool_args: "Tool call",
  tool_result: "Tool result",
  retrieved: "Retrieved content",
  memory_write: "Memory write",
  agent_message: "Agent-to-agent message",
  reasoning: "Reasoning",
  mcp: "MCP call",
};

/** "Would block" etc., for a rule that is only watching. */
export const WOULD: Record<string, string> = {
  block: "Would block",
  escalate: "Would hold",
  redact: "Would mask",
  mask: "Would mask",
  tokenize: "Would mask",
};
