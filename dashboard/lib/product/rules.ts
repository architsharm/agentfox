import { safeApi } from "@/lib/product/api";

export type PackInfo = {
  key: string;
  name: string;
  description: string;
  mode: string | null;
  boundVersion: number | null;
  latestVersion: number | null;
  liveBody: string;
  versions: any[];
  rules: any[];
};

export type RulePack = {
  key: string;
  name: string;
  mode: string | null;
  effect: string;
  enabled: boolean;
  /** What the end user is told when the rule stops a request. */
  message: string;
  /** "reask": ask the model once more instead of refusing (model output only). */
  onBlock: string;
  /** Detection threshold, when the rule tests a detection; null otherwise. */
  minScore: number | null;
};

export type RuleInfo = {
  rule_id: string;
  description: string;
  effect: string;
  severity: string;
  enabled: boolean;
  packs: RulePack[];
};

/** Every installed pack with its live rules, and every rule with the packs it is in. */
export async function loadRules(): Promise<{ packs: PackInfo[]; rules: RuleInfo[] }> {
  // One request for every pack and its live rules (`?full=1`), not one per pack.
  const list = await safeApi<any>("/api/policies?full=1", { policies: [] });
  const packs: PackInfo[] = (list.policies || []).map((d: any) => {
    const compiled = d.live_compiled && d.live_compiled.rules ? d.live_compiled : d.compiled || {};
    return {
      key: d.key,
      name: d.name || d.key,
      description: d.description || "",
      mode: d.mode,
      boundVersion: d.bound_version,
      latestVersion: d.latest_version,
      liveBody: d.live_body || d.body || "",
      versions: d.version_history || [],
      rules: compiled.rules || [],
    };
  });
  const byId = new Map<string, RuleInfo>();
  for (const p of packs) {
    for (const r of p.rules) {
      const enabled = r.enabled !== false;
      const entry: RuleInfo = byId.get(r.id) || {
        rule_id: r.id,
        description: r.description || "",
        effect: r.effect,
        severity: r.severity,
        enabled,
        packs: [],
      };
      const minScore = r.when?.detection?.min_score;
      entry.packs.push({
        key: p.key,
        name: p.name,
        mode: p.mode,
        effect: r.effect,
        enabled,
        message: r.message || "",
        onBlock: r.on_block || "refuse",
        minScore: typeof minScore === "number" ? minScore : null,
      });
      byId.set(r.id, entry);
    }
  }
  // Workspace-wide packs first; an agent's own protection layer (`agent.<slug>`) after.
  const agentLayer = (key: string) => (key.startsWith("agent.") ? 1 : 0);
  for (const r of byId.values()) r.packs.sort((a, b) => agentLayer(a.key) - agentLayer(b.key));
  return { packs, rules: Array.from(byId.values()) };
}

/** Watching or enforcing, for a rule: enforcing if any pack it is on in enforces. */
export function ruleMode(r: RuleInfo): string | null {
  const on = r.packs.filter((p) => p.enabled);
  if (!on.length) return null;
  return on.some((p) => p.mode === "enforce") ? "enforce" : "observe";
}
