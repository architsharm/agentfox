/**
 * The playground's calls to the gateway's public `/api/playground/*` routes.
 *
 * Every call has a deadline. Without one, a request the gateway never answers
 * (a serverless cold start that hangs, a dropped connection) leaves the page on
 * "Setting up your sandbox…" for as long as the browser cares to wait, with no
 * error and no button to try again. With one, it ends in the same recoverable
 * state as any other network failure.
 */

/** Creating a sandbox: long enough for a cold gateway; a warm one answers in under a second. */
export const SANDBOX_TIMEOUT_MS = 20_000;

/** Everything else, including a turn that waits on a model. */
export const PLAYGROUND_TIMEOUT_MS = 60_000;

/** A response the gateway sent, carrying its own plain-English `detail`. */
export class ApiError extends Error {
  status: number;
  /** From a 429: how long until trying again can work. */
  retryAfterSeconds?: number;
  constructor(status: number, message: string, retryAfterSeconds?: number) {
    super(message);
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export async function playgroundCall<T = any>(
  apiBase: string,
  path: string,
  init?: RequestInit,
  timeoutMs: number = PLAYGROUND_TIMEOUT_MS,
): Promise<T> {
  const res = await fetch(`${apiBase}${path}`, {
    ...init,
    signal: init?.signal ?? AbortSignal.timeout(timeoutMs),
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const retry = Number(body.retry_after_seconds ?? res.headers.get("Retry-After"));
    throw new ApiError(
      res.status,
      typeof body.detail === "string" ? body.detail : `${res.status} ${res.statusText}`,
      Number.isFinite(retry) && retry > 0 ? retry : undefined,
    );
  }
  return res.json();
}

/**
 * What to show a visitor when a call fails. The gateway's own sentence for a
 * response it sent; otherwise a plain one, never the browser's "Failed to fetch",
 * "Load failed" or "signal timed out", which read as the page being broken.
 */
export function failureMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  const name = (e as { name?: string } | null)?.name;
  if (name === "TimeoutError" || name === "AbortError") {
    return "The sandbox took too long to answer. Try again.";
  }
  return "The sandbox could not be reached. Check your connection and try again.";
}

/** "in about 12 minutes", from a 429's `retry_after_seconds`. */
export function retryPhrase(seconds?: number): string {
  if (!seconds || seconds <= 60) return "in a minute";
  const minutes = Math.ceil(seconds / 60);
  return minutes < 60 ? `in about ${minutes} minutes` : "in about an hour";
}

/* --- Explaining a verdict ------------------------------------------------- */

export type FiredRule = { rule_id: string; effect?: string; reason?: string; mode?: string };

/**
 * Rules that cite a regulation rather than detect anything: the EU AI Act pack's
 * `eu.art15.injection_resistance` fires on the same injection `injection.direct`
 * already caught. Worth showing, but behind a disclosure, not in the sentence.
 */
const CITATION = /^(eu|nist|iso|soc2|gdpr|hipaa)\./i;
const CITATION_REASON = /^(EU AI Act|NIST|ISO\/IEC|SOC 2|GDPR|HIPAA)\b/;

function sentence(text: string): string {
  const t = text.trim().replace(/[.;\s]+$/, "");
  return t ? `${t.charAt(0).toUpperCase()}${t.slice(1)}.` : "";
}

/** "airline-cs: blocked words: your rule" -> "It matched this agent's blocked words." */
function customReason(reason: string): string {
  const named = reason
    .split(":")
    .map((p) => p.trim())
    .filter((p) => p && p !== "your rule");
  const what = named.length > 1 ? named[named.length - 1] : named[0] || "rules";
  return `It matched this agent's ${what}.`;
}

/**
 * One plain sentence for why a verdict happened, and the regulation citations
 * that fired with it.
 *
 * The gateway's own `reason` joins every fired rule's reason with "; ", so an
 * injection read "…in user input.; System-prompt extraction attempt.; EU AI
 * Act Art. 15 - …; Prompt-injection … in user input." — the same rule twice
 * (once watching from the baseline, once from the agent's own layer) and a
 * citation in the middle. This keeps the first check that fired, says how many
 * others agreed, and moves the citations out of the sentence.
 */
export function explainVerdict(v: { reason?: string; rules_fired?: FiredRule[] }): {
  sentence: string;
  citations: string[];
} {
  const seen = new Set<string>();
  const checks: FiredRule[] = [];
  const citations: string[] = [];
  for (const r of v.rules_fired || []) {
    if (!r?.rule_id || seen.has(r.rule_id)) continue;
    seen.add(r.rule_id);
    if (CITATION.test(r.rule_id) || CITATION_REASON.test(r.reason || "")) {
      citations.push(sentence(r.reason || r.rule_id));
    } else {
      checks.push(r);
    }
  }
  if (checks.length === 0) {
    const first = (v.reason || "").split(/;\s*/)[0] || "";
    return { sentence: sentence(first), citations };
  }
  const lead = checks[0];
  let text = lead.rule_id.startsWith("custom.")
    ? customReason(lead.reason || "")
    : sentence(lead.reason || lead.rule_id);
  const others = checks.length - 1;
  if (others > 0) {
    text = `${text.replace(/\.$/, "")} (and ${others} more check${others === 1 ? "" : "s"}).`;
  }
  return { sentence: text, citations };
}
