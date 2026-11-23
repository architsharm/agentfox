/**
 * The /templates pages: example agents, each with the policy it runs under and the
 * calls that policy runs, holds or refuses. The data is templates.json, which
 * tests/repo/test_template_pages.py replays through the product, so every verdict a
 * page prints is one the enforcer gave. The nav, the sitemap and llms.txt read this
 * list through lib/marketing/nav.ts.
 */

import data from "./templates.json";

export type Verdict = "allow" | "escalate" | "block";

export type TemplateCall = {
  tool: string;
  arguments: Record<string, unknown>;
  verdict: Verdict;
  /** A rule the decision records; the test checks it fired. */
  rule?: string;
};

export type AgentTemplate = {
  slug: string;
  name: string;
  title: string;
  description: string;
  lead: string;
  intent: string;
  /** CLI lines, printed as the policy and run as-is by the test. */
  policy: string[];
  attack: TemplateCall & { story: string; untrusted: string };
  calls: TemplateCall[];
  docs: { href: string; label: string };
};

export const TEMPLATES = data as AgentTemplate[];

export const VERDICT_LABEL: Record<Verdict, string> = {
  allow: "Runs",
  escalate: "Held for a person",
  block: "Refused",
};

export const templatePath = (slug: string) => `/templates/${slug}`;

export function findTemplate(slug: string): AgentTemplate {
  const found = TEMPLATES.find((t) => t.slug === slug);
  if (!found) throw new Error(`no template page for ${slug}`);
  return found;
}

export type ToolRow = { tool: string; impact: string; grant: string };

/** The tools table, read from the policy's own `declare tool` and `permit grant` lines. */
export function toolRows(policy: string[]): ToolRow[] {
  const rows = new Map<string, ToolRow>();
  for (const line of policy) {
    const words = line.split(/\s+/);
    if (words[1] === "declare" && words[2] === "tool") {
      rows.set(words[3], { tool: words[3], impact: words[words.indexOf("--impact") + 1], grant: "Not granted: refused" });
    }
    if (words[1] === "permit" && words[2] === "grant") {
      const row = rows.get(words[4]);
      if (!row) continue;
      const limits = words.flatMap((w, i) => (w === "--limit" ? [words[i + 1]] : []));
      row.grant = [
        words.includes("--requires-approval") ? "Granted, every call held for a person" : "Granted",
        ...limits.map((l) => `limit ${l}`),
      ].join(", ");
    }
  }
  return [...rows.values()];
}
