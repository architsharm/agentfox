/**
 * Environment variables, read the way the gateway reads them: `AGENTFOX_<name>`.
 * An empty value counts as unset.
 *
 * The pre-rename `NOMETRIA_<name>` is no longer read. A deployment that still sets
 * only the old name would otherwise fall back to a default without a word, so that
 * case logs one warning per name, on the server, naming the variable to rename.
 *
 * Server-side only, like every caller: the lookup is dynamic, so nothing here is
 * inlined into the client bundle (see next.config.mjs).
 */

const warned = new Set<string>();

export function env(name: string): string | undefined {
  const current = process.env[`AGENTFOX_${name}`];
  if (current) return current;
  if (process.env[`NOMETRIA_${name}`] && !warned.has(name)) {
    warned.add(name);
    console.warn(
      `NOMETRIA_${name} is set but no longer read; rename it to AGENTFOX_${name}.`,
    );
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
