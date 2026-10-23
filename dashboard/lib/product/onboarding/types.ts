/**
 * Onboarding data shapes. The UI is built against these; mock fixtures and the
 * HTTP stubs both produce them, so swapping in real endpoints changes nothing
 * on screen.
 */

export type OnboardingStep = "connect" | "install" | "structure" | "test" | "protect" | "retest";

export type OnboardingState = {
  currentStep: OnboardingStep;
  completedSteps: OnboardingStep[];
  skipped: boolean;
  completedAt: string | null;
};

export type Risk = "high" | "outside" | "read_only";

export type Structure = {
  /** Who talks to it. */
  sources: { id: string; label: string; detail?: string }[];
  agents: { id: string; name: string; model: string; sourceIds: string[]; addedByUser?: boolean }[];
  tools: {
    id: string;
    name: string;
    agentId: string;
    risk: Risk;
    whatItDoes: string;
    systemId?: string;
    args?: string[];
    /** Added on See structure rather than found in code. */
    addedByUser?: boolean;
  }[];
  /** What the tools touch: Stripe, CRM, Postgres. */
  systems: { id: string; name: string; kind: string }[];
};

export type AttackType = "prompt_injection" | "data_leak" | "unsafe_tool_use" | "jailbreak";

export type TestRun = {
  id: string;
  status: "running" | "done" | "failed";
  phase: "before" | "after";
  total: number;
  gotThrough: number;
  byType: { type: AttackType; label: string; total: number; gotThrough: number; done: number }[];
  feed: { id: string; result: "got_through" | "resisted" | "error"; sentence: string }[];
  worst?: { headline: string; attack: string; toolCall: string; owasp: string[] };
  /** Not in the brief's shape: how long the run has left, for "About N left". */
  remainingMs?: number | null;
  /** Queued, but no `agentfox init` is connected to run it. */
  waitingForRunner?: boolean;
  /** Attacks that couldn't run (the agent's model errored). */
  errors?: number;
  /** Why a failed run failed. */
  error?: string | null;
};

/** One attack's outcome, for the full report. */
export type AttackResult = {
  id: string;
  type: AttackType;
  gotThrough: boolean;
  error: string | null;
  sentence: string;
  attack: string;
  toolCall: string;
  owasp: string[];
};

export type SuggestedGuardrail = {
  id: string;
  sentence: string;
  appliesTo: string;
  enabled: boolean;
};

/** A key the user pastes into `agentfox init --key`. Always retrievable, never "shown once". */
export type OnboardingKey = { value: string; createdNow: boolean };

/** The four states every step can be forced into from the dev panel. */
export type ForcedState = "loading" | "empty" | "error" | "success";
