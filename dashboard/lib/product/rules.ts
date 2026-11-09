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
  /** This rule only watches, even though its pack enforces (a new rule in Your rules). */
  watch?: boolean;
};

export type RuleInfo = {
  rule_id: string;
  description: string;
  effect: string;
  severity: string;
  enabled: boolean;
  /** What a content rule looks for (`PII`, `INJECTION.JAILBREAK`); empty for rules about tool calls or the run. */
  finds: string;
  packs: RulePack[];
};

/** Every installed pack with its live rules, and every rule with the packs it is in. */
export async function loadRules(): Promise<{ packs: PackInfo[]; rules: RuleInfo[] }> {
  // One request for every pack and its live rules (`?full=1`), not one per pack.
  const [list, business] = await Promise.all([
    safeApi<any>("/api/policies?full=1", { policies: [] }),
    safeApi<any>("/api/business/rules", { rules: [] }),
  ]);
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
        finds: String(r.when?.detection?.entity || r.when?.detection?.entity_prefix || ""),
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
        watch: Boolean(r.watch),
      });
      byId.set(r.id, entry);
    }
  }
  // A business rule (an approval limit) is a rule like any other to a person: listed
  // as `business.<key>`, in Your rules, in its own mode.
  for (const b of business.rules || []) {
    const entry = businessRule(b);
    byId.set(entry.rule_id, entry);
  }
  // Workspace-wide packs first; an agent's own protection layer (`agent.<slug>`) after.
  const agentLayer = (key: string) => (key.startsWith("agent.") ? 1 : 0);
  for (const r of byId.values()) r.packs.sort((a, b) => agentLayer(a.key) - agentLayer(b.key));
  return { packs, rules: Array.from(byId.values()) };
}

/** The mode one pack applies this rule in: a rule that watches on its own does not enforce. */
export function packRuleMode(p: RulePack): string | null {
  return p.mode === "enforce" && p.watch ? "observe" : p.mode;
}

/** Watching or enforcing, for a rule: enforcing if any pack it is on in enforces it. */
export function ruleMode(r: RuleInfo): string | null {
  const on = r.packs.filter((p) => p.enabled);
  if (!on.length) return null;
  return on.some((p) => packRuleMode(p) === "enforce") ? "enforce" : "observe";
}

/** The library a business rule lives in, as the rule's page and Applied rules name it. */
export const BUSINESS_LIBRARY = { key: "custom", name: "Your rules" };

/** The strongest outcome among a business rule's bands: what it "does". */
const STRONGEST = ["block", "escalate", "verify", "redact", "allow"];

/** A business rule (GET /api/business/rules row) as a rule: id `business.<key>`, its own mode. */
export function businessRule(b: any): RuleInfo {
  const bands: any[] = b.definition?.bands || [];
  const outcomes = new Set(bands.map((x) => x.outcome || "allow"));
  const effect = STRONGEST.find((o) => outcomes.has(o)) || "allow";
  const said = bands.find((x) => x.outcome === effect && x.reason)?.reason || "";
  const enabled = b.enabled !== false;
  return {
    rule_id: `business.${b.key}`,
    description: b.description || said || b.name || b.key,
    effect,
    severity: "medium",
    enabled,
    finds: "",
    packs: [{ ...BUSINESS_LIBRARY, mode: b.mode, effect, enabled, message: "", onBlock: "refuse", minScore: null }],
  };
}
