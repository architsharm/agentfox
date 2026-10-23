import type { OnboardingState, OnboardingStep, Structure, SuggestedGuardrail } from "./types";

export const STEPS: { step: OnboardingStep; label: string; desc: string }[] = [
  { step: "connect", label: "Connect", desc: "Create your project key" },
  { step: "install", label: "Install", desc: "Run one command" },
  { step: "structure", label: "Detect", desc: "Your agents and tools" },
  { step: "test", label: "Test", desc: "Run known attacks, safely" },
  { step: "protect", label: "Protect", desc: "Turn on basic guardrails" },
  { step: "retest", label: "Retest", desc: "See the difference" },
];

export const STEP_ORDER: OnboardingStep[] = STEPS.map((s) => s.step);

export function isStep(value: unknown): value is OnboardingStep {
  return typeof value === "string" && (STEP_ORDER as string[]).includes(value);
}

export function stepIndex(step: OnboardingStep): number {
  return STEP_ORDER.indexOf(step);
}

export function nextStep(step: OnboardingStep): OnboardingStep | null {
  return STEP_ORDER[stepIndex(step) + 1] ?? null;
}

export function prevStep(step: OnboardingStep): OnboardingStep | null {
  return STEP_ORDER[stepIndex(step) - 1] ?? null;
}

export const INITIAL_STATE: OnboardingState = {
  currentStep: "connect",
  completedSteps: [],
  skipped: false,
  completedAt: null,
};

/** The state after finishing `step`: it is marked done and the user moves on. */
export function completeStep(state: OnboardingState, step: OnboardingStep): OnboardingState {
  const completedSteps = state.completedSteps.includes(step)
    ? state.completedSteps
    : [...state.completedSteps, step].sort((a, b) => stepIndex(a) - stepIndex(b));
  const next = nextStep(step);
  return {
    ...state,
    completedSteps,
    currentStep: next ?? step,
    skipped: false,
    completedAt: next ? state.completedAt : new Date().toISOString(),
  };
}

/** Path for a step, carrying the mock flag so a flow on fixtures stays on fixtures. */
export function stepHref(step: OnboardingStep, mock: boolean): string {
  return `/app/onboarding/${step}${mock ? "?mock=1" : ""}`;
}

export function riskyToolCount(structure: Structure): number {
  return structure.tools.filter((t) => t.risk === "high").length;
}

/**
 * Basic guardrails that fit what was found. The three tool-specific ones only
 * appear when a tool of that kind exists; the last two always apply.
 */
export function suggestGuardrails(structure: Structure): SuggestedGuardrail[] {
  const agentName = (id: string) => structure.agents.find((a) => a.id === id)?.name ?? id;
  const systemKind = (id?: string) => structure.systems.find((s) => s.id === id)?.kind ?? "";
  const high = structure.tools.filter((t) => t.risk === "high");
  const where = (tools: Structure["tools"]) =>
    tools.map((t) => `${t.name} · ${agentName(t.agentId)}`).join(", ");

  const money = high.filter((t) => systemKind(t.systemId) === "payments");
  const personal = high.filter((t) => systemKind(t.systemId) === "crm");
  const dbWrite = high.filter((t) => systemKind(t.systemId) === "database");
  const allAgents = structure.agents.map((a) => a.name).join(", ");

  const out: SuggestedGuardrail[] = [];
  if (money.length)
    out.push({ id: "refund-approval", sentence: "Refunds over $100 need a person", appliesTo: where(money), enabled: true });
  if (personal.length)
    out.push({ id: "block-bulk-export", sentence: "Block bulk customer exports", appliesTo: where(personal), enabled: true });
  for (const tool of dbWrite)
    out.push({
      id: `block-sql-delete-${tool.agentId}`,
      sentence: `Block DELETE / DROP from ${agentName(tool.agentId)}`,
      appliesTo: where([tool]),
      enabled: true,
    });
  out.push({ id: "prompt-attacks", sentence: "Catch prompt attacks", appliesTo: `All agents · ${allAgents}`, enabled: true });
  out.push({
    id: "hide-personal-data",
    sentence: "Hide personal data and secrets in replies",
    appliesTo: `All agents · ${allAgents}`,
    enabled: true,
  });
  return out;
}
