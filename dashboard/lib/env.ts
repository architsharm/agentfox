/**
 * Environment variables, read the way the gateway reads them: `AGENTFOX_<name>`
 * first, then the pre-rename `NOMETRIA_<name>` as a deprecated fallback.
 *
 * The fallback exists so a deployment whose variables still carry the old prefix
 * (Vercel, Render, a self-hoster's `.env`) keeps working until they are renamed.
 * Using it logs one warning per name, on the server, naming the variable to rename.
 * An empty value counts as unset.
 *
 * Server-side only, like every caller: the lookup is dynamic, so nothing here is
 * inlined into the client bundle (see next.config.mjs).
 */

const warned = new Set<string>();

export function env(name: string): string | undefined {
  const current = process.env[`AGENTFOX_${name}`];
  if (current) return current;
  const legacy = process.env[`NOMETRIA_${name}`];
  if (legacy) {
    if (!warned.has(name)) {
      warned.add(name);
      console.warn(
        `NOMETRIA_${name} is deprecated and will stop being read; rename it to AGENTFOX_${name}.`,
      );
    }
    return legacy;
  }
  return undefined;
}

/** Test hook: forget which legacy names were already warned about. */
export function resetLegacyEnvWarnings(): void {
  warned.clear();
}

/** The gateway's base URL for server-to-server calls. */
export function apiBase(): string {
  return env("API_URL") || "http://127.0.0.1:8080";
}
