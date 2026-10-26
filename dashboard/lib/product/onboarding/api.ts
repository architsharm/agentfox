"use client";

import * as store from "./store";
import { requestError } from "./connect";
import type {
  AttackResult,
  OnboardingKey,
  OnboardingState,
  Structure,
  SuggestedGuardrail,
  TestRun,
} from "./types";

/**
 * The one module the onboarding screens talk to. Two implementations behind one
 * shape: `mock` (fixtures, localStorage, no network) for `?mock=1`, and `http`
 * for everything else. Phase 2 swaps what `http` calls; the screens don't change.
 */
export type OnboardingApi = {
  getState(): Promise<OnboardingState>;
  saveState(state: OnboardingState): Promise<OnboardingState>;
  reset(): Promise<OnboardingState>;
  getKey(): Promise<OnboardingKey>;
  /** Revoke the key and make a new one, shown in full that once. */
  rotateKey(): Promise<OnboardingKey>;
  /** `live`: Connect's status panel, which waits for the agent to report in. Other steps read the map as it stands. */
  getStructure(opts?: { live?: boolean }): Promise<{ connected: boolean; runnerConnected?: boolean; structure: Structure }>;
  /** Save the map after the user added or removed an agent or tool. */
  saveStructure(structure: Structure): Promise<Structure>;
  startTest(phase: "before" | "after"): Promise<TestRun>;
  getTest(id: string): Promise<TestRun>;
  latestTest(phase: "before" | "after"): Promise<TestRun | null>;
  /** Every attack in a run: what it sent and what the agent did. */
  getResults(id: string): Promise<AttackResult[]>;
  getGuardrails(): Promise<SuggestedGuardrail[]>;
  saveGuardrails(items: SuggestedGuardrail[]): Promise<SuggestedGuardrail[]>;
};

const MOCK_STORAGE = "agentfox.onboarding.mock.v1";
/** Long enough for a loading state to be seen, short enough not to drag. */
const MOCK_LATENCY_MS = 250;

function load(): store.Session {
  try {
    return store.parseSession(localStorage.getItem(MOCK_STORAGE));
  } catch {
    return store.EMPTY_SESSION;
  }
}

function save(session: store.Session) {
  try {
    localStorage.setItem(MOCK_STORAGE, JSON.stringify(session));
  } catch {
    // Private windows can refuse storage; the flow still runs, it just won't resume.
  }
}

const wait = <T,>(value: T) => new Promise<T>((r) => setTimeout(() => r(value), MOCK_LATENCY_MS));

export const mockApi: OnboardingApi = {
  getState: () => wait(load().state),
  saveState: (state) => {
    const session = store.saveState(load(), state);
    save(session);
    return wait(session.state);
  },
  reset: () => {
    save(store.EMPTY_SESSION);
    return wait(store.EMPTY_SESSION.state);
  },
  getKey: () => wait({ value: store.onboardingKey(), createdNow: false }),
  rotateKey: () => wait({ value: store.onboardingKey(), createdNow: true, hasKey: true }),
  getStructure: (opts) => {
    if (!opts?.live) return wait(store.currentStructure(load()));
    const { session, result } = store.pollStructure(load(), Date.now());
    save(session);
    return wait(result);
  },
  saveStructure: (structure) => {
    save(store.saveStructure(load(), structure));
    return wait(structure);
  },
  startTest: (phase) => {
    const { session, run } = store.startRun(load(), phase, Date.now());
    save(session);
    return wait(run);
  },
  getTest: async (id) => {
    const run = store.readRun(id, Date.now());
    if (!run) throw new Error("That test run doesn't exist.");
    return run; // no latency: this is polled every half second
  },
  latestTest: (phase) => wait(store.latestRun(load(), phase, Date.now())),
  getResults: () => wait([]),
  getGuardrails: () => wait(store.guardrails(load())),
  saveGuardrails: (items) => {
    save(store.saveGuardrails(load(), items));
    return wait(items);
  },
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
      cache: "no-store",
    });
  } catch {
    throw new Error(requestError(null));
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(requestError(res.status, body));
  }
  return res.json() as Promise<T>;
}

export const httpApi: OnboardingApi = {
  getState: () => call("/api/onboarding/state"),
  saveState: (state) => call("/api/onboarding/state", { method: "PATCH", body: JSON.stringify(state) }),
  reset: () => call("/api/onboarding/state", { method: "DELETE" }),
  getKey: () => call("/api/onboarding/key"),
  rotateKey: () => call("/api/onboarding/key/rotate", { method: "POST" }),
  getStructure: (opts) => call(`/api/onboarding/structure${opts?.live ? "?live=1" : ""}`),
  saveStructure: (structure) =>
    call<{ structure: Structure }>("/api/onboarding/structure", { method: "PUT", body: JSON.stringify({ structure }) }).then(
      (r) => r.structure,
    ),
  startTest: (phase) => call("/api/onboarding/tests", { method: "POST", body: JSON.stringify({ phase }) }),
  getTest: (id) => call(`/api/onboarding/tests/${encodeURIComponent(id)}`),
  latestTest: (phase) => call(`/api/onboarding/tests?phase=${phase}`),
  getResults: (id) =>
    call<{ results: AttackResult[] }>(`/api/onboarding/tests/${encodeURIComponent(id)}/results`).then((r) => r.results),
  getGuardrails: () => call("/api/onboarding/guardrails"),
  saveGuardrails: (items) => call("/api/onboarding/guardrails", { method: "POST", body: JSON.stringify(items) }),
};

export function onboardingApi(mock: boolean): OnboardingApi {
  return mock ? mockApi : httpApi;
}
