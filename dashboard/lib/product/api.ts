/**
 * API client.
 *
 * The dashboard is a client of the same public API the CLI and SDK use (principle
 * X-5) — no privileged back-channel, no database access from this process. That
 * constraint is what keeps the API honest: anything the UI can show, a script can
 * fetch.
 */

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { apiBase, env } from "@/lib/env";

const BASE = apiBase();

// In MVP self-host there is no IdP wired (PRD §6.3); the control plane accepts a
// development identity header when AGENTFOX_ENVIRONMENT is a dev environment, or a
// bearer token everywhere else (auth_mode=token). Both paths are supported here
// because the value of a demo of a governance product is undercut by the demo itself
// running with authentication turned off — a live deployment sets AGENTFOX_API_TOKEN
// and gets the real path; local dev with no token set keeps working exactly as before.
const USER = env("USER") || "admin@example.com";
const TOKEN = env("API_TOKEN");
//: This is the P2-4 SSO seam, connected: app/api/auth/github/callback/route.ts mints
//: a real per-user token on sign-in and sets it here. Checked ahead of the static
//: env var, so a signed-in user's own token — not a shared service token — is what
//: the gateway sees, and its tenant scoping applies to everything the UI shows them.
export const SESSION_COOKIE = "agentfox_session";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly path: string,
  ) {
    super(message);
  }
}

async function authHeaders(): Promise<Record<string, string>> {
  const sessionToken = (await cookies()).get(SESSION_COOKIE)?.value;
  if (sessionToken) return { Authorization: `Bearer ${sessionToken}` };
  if (TOKEN) return { Authorization: `Bearer ${TOKEN}` };
  return { "X-AgentFox-User": USER };
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(await authHeaders()),
      ...(init?.headers || {}),
    },
    // Governance data is live data; a cached control status is a wrong control status.
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(body.slice(0, 400) || res.statusText, res.status, path);
  }
  return res.json() as Promise<T>;
}

/**
 * Turns whatever a failed `api()` call threw into the props `<ApiDown>` needs.
 *
 * The status is the whole point: without it every failure reads as "the server
 * is down", including an expired session (401) and a missing record (404). A
 * network-level failure has no status at all, which is the case ApiDown treats
 * as genuinely unreachable.
 */
export function apiErrorProps(e: unknown): { error: string; status?: number } {
  const error = String((e as any)?.message || e);
  return e instanceof ApiError ? { error, status: e.status } : { error };
}

/** Fetch that renders an inline error rather than blanking the page. */
export async function safeApi<T = any>(path: string, fallback: T): Promise<T> {
  try {
    return await api<T>(path);
  } catch (e) {
    // A signed-in session the gateway no longer accepts is not "no data": every page
    // would render its empty state ("Nothing is waiting", "No decisions yet") over
    // records that exist. Send the person to sign in again instead.
    if (e instanceof ApiError && e.status === 401 && (await cookies()).get(SESSION_COOKIE)?.value) {
      redirect("/login?session=expired");
    }
    return fallback;
  }
}

export const post = <T = any>(path: string, body: unknown) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });
