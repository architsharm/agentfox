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

/**
 * The gateway URL as the user's own code should reach it — what the setup
 * snippets on Get started print. `API_URL` is often an internal address
 * (127.0.0.1, a private service name) that would be wrong in a customer's code,
 * so a deployment whose gateway is public under another name sets
 * `AGENTFOX_PUBLIC_API_URL`.
 */
export function publicApiBase(): string {
  return (env("PUBLIC_API_URL") || apiBase()).replace(/\/+$/, "");
}
