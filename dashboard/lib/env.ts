/**
 * Environment variables, read the way the gateway reads them: `AGENTFOX_<name>`.
 * An empty value counts as unset.
 *
 * Server-side only, like every caller: the lookup is dynamic, so nothing here is
 * inlined into the client bundle (see next.config.mjs).
 */

export function env(name: string): string | undefined {
  return process.env[`AGENTFOX_${name}`] || undefined;
}

/** The gateway's base URL for server-to-server calls. */
export function apiBase(): string {
  return env("API_URL") || "http://127.0.0.1:8080";
}
