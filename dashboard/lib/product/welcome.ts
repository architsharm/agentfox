/**
 * The pure parts of the welcome page (app/(product)/app/welcome): which repository
 * to offer first, what a scan's result says in one line, and the one command that
 * finishes setup on the user's machine. Kept out of the components so they can be
 * tested without rendering anything.
 */

export type Repo = {
  full_name: string;
  private: boolean;
  default_branch: string;
  description: string;
  updated_at: string;
  scanned?: boolean;
};

/**
 * Most recently updated first: the repository someone is working on this week is
 * the one they came to check, not the alphabetically first of a hundred.
 */
export function sortRepos(repos: Repo[]): Repo[] {
  return [...repos].sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
}

/**
 * Where AgentFox is installed from for `agentfox up`. From git rather than PyPI
 * while the published release predates `up`, the same choice scripts/quickscan.sh
 * makes, so the command works the day this page ships.
 */
export const INSTALL_SPEC = "git+https://github.com/architsharm/agentfox";

/** The hosted product's own address: `up --target cloud` links back to it. */
const CLOUD_HOST = "useagentfox.com";

/**
 * `agentfox up`, already answered: the gateway, the key and observe mode are filled
 * in, and `--yes` takes the recommendations for the rest, so the terminal asks
 * nothing. The agent is left to `up`, which names it after the repository's folder,
 * as it does when run on its own. The key travels as `AGENTFOX_API_TOKEN` (which `up`
 * reads) rather than a flag, the same way every other snippet on these pages passes
 * it. `siteUrl` is the address this dashboard is being served at.
 */
export function upCommand({ gateway, token, siteUrl }: { gateway: string; token: string; siteUrl: string }): string {
  let target = "self-hosted";
  try {
    if (new URL(siteUrl).hostname === CLOUD_HOST) target = "cloud";
  } catch {
    // An unparseable site URL is a self-hosted deployment's own name.
  }
  return [
    `AGENTFOX_API_TOKEN=${token} \\`,
    `  uvx --from ${INSTALL_SPEC} \\`,
    `  agentfox up --target ${target} --api-url ${gateway} --mode observe --yes`,
  ].join("\n");
}

export type Highlights = {
  model_calls: number;
  ungoverned_model_calls: number;
  tools: number;
  mcp_servers: string[];
  trifectas: { file: string; detail: string }[];
  skills: number;
  skill_issues: { skill: string; path: string; type: string; severity: string }[];
};

/**
 * The scan's result as rows for the welcome page. A row is shown only when there is
 * something to say, and `tone` is "bad" only for what a security owner would act on.
 * An empty repository is "inconclusive" when nothing it could read was code, which
 * is not the same as clean and must not look like it.
 */
export function scanRows(summary: any): { label: string; value: string; tone: "bad" | "warn" | "ok" | "neutral" }[] {
  const h: Highlights | undefined = summary?.highlights;
  const rows: { label: string; value: string; tone: "bad" | "warn" | "ok" | "neutral" }[] = [];
  if (!h) return rows;
  if (h.model_calls) {
    rows.push({
      label: "Model calls",
      value: h.ungoverned_model_calls ? `${h.model_calls} (${h.ungoverned_model_calls} ungoverned)` : `${h.model_calls}, all governed`,
      tone: h.ungoverned_model_calls ? "warn" : "ok",
    });
  }
  if (h.tools) rows.push({ label: "Tools", value: String(h.tools), tone: "neutral" });
  if (h.mcp_servers.length) rows.push({ label: "MCP servers", value: h.mcp_servers.join(", "), tone: "neutral" });
  if (h.trifectas.length) {
    rows.push({ label: "Lethal trifectas", value: String(h.trifectas.length), tone: "bad" });
  }
  if (h.skills) {
    const flagged = new Set(h.skill_issues.map((i) => i.skill)).size;
    rows.push({
      label: "Skills",
      value: flagged ? `${h.skills} (${flagged} flagged: planted instructions or risky commands)` : `${h.skills}, none flagged`,
      tone: flagged ? "bad" : "ok",
    });
  }
  const frameworks: string[] = summary?.frameworks || [];
  if (frameworks.length) rows.push({ label: "Built on", value: frameworks.join(", "), tone: "neutral" });
  return rows;
}
