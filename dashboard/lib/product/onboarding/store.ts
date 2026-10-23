import {
  MOCK_KEY,
  STRUCTURE,
  parseRunId,
  runId,
  simulateConnect,
  simulateRun,
} from "./fixtures";
import { INITIAL_STATE, isStep, suggestGuardrails } from "./steps";
import type { OnboardingState, Structure, SuggestedGuardrail, TestRun } from "./types";

/**
 * One onboarding session's stored facts, and the operations on them. Pure: the
 * caller loads a session, applies an operation, and saves what comes back.
 * Mock mode keeps it in localStorage; the HTTP stubs keep it in a cookie.
 * Phase 2 replaces the stubs with real endpoints and this file goes with them.
 */
export type Session = {
  state: OnboardingState;
  connectStartedAt: number | null;
  runs: { before?: string; after?: string };
  guardrails: SuggestedGuardrail[] | null;
  /** The map after the user added or removed something on See structure. */
  structure: Structure | null;
};

export const EMPTY_SESSION: Session = {
  state: INITIAL_STATE,
  connectStartedAt: null,
  runs: {},
  guardrails: null,
  structure: null,
};

/** Accepts anything (a cookie, localStorage) and returns a valid session or a fresh one. */
export function parseSession(raw: unknown): Session {
  try {
    const value = typeof raw === "string" ? JSON.parse(raw) : raw;
    if (!value || typeof value !== "object" || !isStep(value.state?.currentStep)) return EMPTY_SESSION;
    return {
      state: {
        currentStep: value.state.currentStep,
        completedSteps: (value.state.completedSteps || []).filter(isStep),
        skipped: Boolean(value.state.skipped),
        completedAt: value.state.completedAt ?? null,
      },
      connectStartedAt: typeof value.connectStartedAt === "number" ? value.connectStartedAt : null,
      runs: {
        before: typeof value.runs?.before === "string" ? value.runs.before : undefined,
        after: typeof value.runs?.after === "string" ? value.runs.after : undefined,
      },
      guardrails: Array.isArray(value.guardrails) ? value.guardrails : null,
      structure: value.structure && Array.isArray(value.structure.tools) ? value.structure : null,
    };
  } catch {
    return EMPTY_SESSION;
  }
}

export function saveState(session: Session, state: OnboardingState): Session {
  return { ...session, state: parseSession({ state }).state };
}

/** The live map from the agent. The connect clock starts on the first poll. */
export function pollStructure(session: Session, now: number) {
  const started = session.connectStartedAt ?? now;
  return {
    session: session.connectStartedAt == null ? { ...session, connectStartedAt: started } : session,
    result: simulateConnect(now - started),
  };
}

/** The map as it stands, for every step after Connect: with the user's own edits. */
export function currentStructure(session: Session = EMPTY_SESSION): { connected: boolean; structure: Structure } {
  return { connected: true, structure: session.structure ?? STRUCTURE };
}

export function saveStructure(session: Session, structure: Structure): Session {
  return { ...session, structure };
}

export function startRun(session: Session, phase: "before" | "after", now: number) {
  const id = runId(phase, now);
  return { session: { ...session, runs: { ...session.runs, [phase]: id } }, run: simulateRun(id, phase, 0) };
}

export function readRun(id: string, now: number): TestRun | null {
  const parsed = parseRunId(id);
  return parsed ? simulateRun(id, parsed.phase, now - parsed.startedAt) : null;
}

export function latestRun(session: Session, phase: "before" | "after", now: number): TestRun | null {
  const id = session.runs[phase];
  return id ? readRun(id, now) : null;
}

export function guardrails(session: Session): SuggestedGuardrail[] {
  return session.guardrails ?? suggestGuardrails(session.structure ?? STRUCTURE);
}

export function saveGuardrails(session: Session, items: SuggestedGuardrail[]): Session {
  return { ...session, guardrails: items };
}

export function onboardingKey(): string {
  return MOCK_KEY;
}
