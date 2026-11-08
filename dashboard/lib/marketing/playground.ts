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
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
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
    throw new ApiError(res.status, body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}
