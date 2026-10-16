/**
 * Features (`/api/features`, `/api/agents/{slug}/features`): what the workspace turns
 * on for every project, and what one project changed. Types and the small decisions
 * the editor makes, kept apart from it so they can be tested.
 */

export type Level = "off" | "on" | "low" | "medium" | "high";

export type ProtectionFeature = {
  key: string;
  title: string;
  graded: boolean;
  pack: string;
  installed: boolean;
  available: boolean;
  workspace: Level;
  workspace_mode: "blocking" | "watching" | null;
  open_to_projects: boolean;
  protected: boolean;
  /** This project's own value; null: it inherits the workspace's. */
  project: Level | null;
  project_mode: "blocking" | "watching" | null;
  effective: Level;
  needs: string | null;
};

export type CheckFeature = {
  key: string;
  label: string | null;
  group: string;
  group_title: string;
  source: string;
  where: string[];
  installed: boolean;
  always_on: boolean;
  workspace: boolean;
  project: boolean | null;
  effective: boolean;
};

export type Features = {
  agent: string | null;
  levels: Level[];
  protections: ProtectionFeature[];
  checks: CheckFeature[];
};

const RANK: Record<Level, number> = { off: 0, low: 1, on: 2, medium: 2, high: 3 };

/** The choices a protection offers. */
export function levelsFor(p: ProtectionFeature): Level[] {
  return p.graded ? ["off", "low", "medium", "high"] : ["off", "on"];
}

export const LEVEL_LABEL: Record<Level, string> = { off: "Off", on: "On", low: "Low", medium: "Medium", high: "High" };

/**
 * Why a project may not pick this level, or null when it may. Stricter than the
 * workspace is always allowed; lower only where the workspace opened it to projects.
 */
export function lockedReason(p: ProtectionFeature, level: Level): string | null {
  if (RANK[level] >= RANK[p.workspace]) return null;
  if (p.protected) return "This protection cannot be lowered for a single project.";
  if (!p.open_to_projects) return "The workspace does not let projects lower this. Change it in workspace Features.";
  return null;
}

/** How many switches this project changed from the workspace. */
export function changedCount(f: Features): number {
  return f.protections.filter((p) => p.project !== null).length + f.checks.filter((c) => c.project !== null).length;
}

/** Checks by group, installed ones first within each. */
export function checkGroups(checks: CheckFeature[]): { key: string; title: string; checks: CheckFeature[] }[] {
  const groups = new Map<string, { key: string; title: string; checks: CheckFeature[] }>();
  for (const c of checks) {
    if (!groups.has(c.group)) groups.set(c.group, { key: c.group, title: c.group_title, checks: [] });
    groups.get(c.group)!.checks.push(c);
  }
  for (const g of groups.values()) g.checks.sort((a, b) => Number(b.installed) - Number(a.installed) || a.key.localeCompare(b.key));
  return [...groups.values()];
}
