/**
 * Words for the policy screens where the API hands back something written for
 * engineers: a version's notes (`injection.direct: {'min_score': 0.5}`), a library
 * rule's docstring (markdown, control IDs), a business rule named by its slug.
 * Kept apart from the screens so each translation is tested.
 */

import { ACTIONS, SENSITIVITY, sensitivityOf } from "@/lib/product/vocab";

// --- inline markdown ---------------------------------------------------------------

export type Inline = { kind: "text" | "em" | "strong" | "code"; text: string };

/**
 * `*higher*`, `**must**` and `` `code` `` in a rule's description, as pieces to render.
 * Only the inline marks rule docstrings use; anything else stays as written.
 */
export function inlineMarkdown(src: string): Inline[] {
  const out: Inline[] = [];
  const re = /\*\*([^*]+)\*\*|\*([^*\s][^*]*?)\*|`([^`]+)`/g;
  let last = 0;
  for (let m = re.exec(src); m; m = re.exec(src)) {
    if (m.index > last) out.push({ kind: "text", text: src.slice(last, m.index) });
    if (m[1] !== undefined) out.push({ kind: "strong", text: m[1] });
    else if (m[2] !== undefined) out.push({ kind: "em", text: m[2] });
    else out.push({ kind: "code", text: m[3] });
    last = m.index + m[0].length;
  }
  if (last < src.length) out.push({ kind: "text", text: src.slice(last) });
  return out;
}

/** Control IDs a rule maps to (`NOM-RTG-13`, `EU-AIA-ART14`): for a details row, not the sentence. */
const CONTROL = /\b[A-Z]{2,6}(?:-[A-Z0-9]{2,8}){1,3}\b/g;

/**
 * A rule's description without the control IDs written into it, and those IDs.
 * "… predate this policy (NOM-RTG-13, NOM-IAM-08)." → "… predate this policy." + both IDs.
 */
export function splitControls(text: string): { text: string; controls: string[] } {
  const controls = Array.from(new Set(text.match(CONTROL) || [])).filter((c) => /\d/.test(c));
  if (!controls.length) return { text: text.trim(), controls };
  let rest = text;
  for (const c of controls) rest = rest.split(c).join("");
  rest = rest
    .replace(/\(\s*(?:[,;/]\s*)*\)/g, "") // the parentheses that held only IDs
    .replace(/\s+([.,;:])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
  return { text: rest, controls };
}

// --- version notes -------------------------------------------------------------------

/**
 * A Python dict literal of scalars, as the gateway writes a rule change into a
 * version's notes: `{'min_score': 0.5, 'enabled': False, 'message': "Can't"}`.
 * Null when it is anything else.
 */
export function parsePyDict(src: string): Record<string, unknown> | null {
  const s = src.trim();
  if (!s.startsWith("{") || !s.endsWith("}")) return null;
  const out: Record<string, unknown> = {};
  let i = 1;
  const ws = () => {
    while (i < s.length && /\s/.test(s[i])) i++;
  };
  const str = (): string | null => {
    const q = s[i];
    if (q !== "'" && q !== '"') return null;
    let v = "";
    i++;
    while (i < s.length && s[i] !== q) {
      if (s[i] === "\\" && i + 1 < s.length) {
        v += s[i + 1];
        i += 2;
      } else v += s[i++];
    }
    if (s[i] !== q) return null;
    i++;
    return v;
  };
  const scalar = (): { ok: boolean; v?: unknown } => {
    ws();
    const quoted = str();
    if (quoted !== null) return { ok: true, v: quoted };
    const m = /^(True|False|None|-?\d+(?:\.\d+)?(?:e-?\d+)?)/.exec(s.slice(i));
    if (!m) return { ok: false };
    i += m[0].length;
    const t = m[0];
    return { ok: true, v: t === "True" ? true : t === "False" ? false : t === "None" ? null : Number(t) };
  };
  for (;;) {
    ws();
    if (s[i] === "}") return i === s.length - 1 ? out : null;
    const key = str();
    if (key === null) return null;
    ws();
    if (s[i++] !== ":") return null;
    const v = scalar();
    if (!v.ok) return null;
    out[key] = v.v;
    ws();
    if (s[i] === ",") i++;
  }
}

const sensitivityWord = (v: unknown) => {
  if (typeof v !== "number") return null;
  const key = sensitivityOf(v);
  return SENSITIVITY.find((x) => x.key === key)?.label ?? null;
};

/** One field of a rule change, in words; `before` when the notes say what it was. */
function changeWords(field: string, after: unknown, before: unknown): string {
  const from = (w: string | null) => (w ? ` from ${w}` : "");
  switch (field) {
    case "min_score": {
      const a = sensitivityWord(after);
      const b = sensitivityWord(before);
      if (a && b && a !== b) return `Sensitivity changed from ${b} to ${a}`;
      return a ? `Sensitivity set to ${a}` : "Sensitivity changed";
    }
    case "effect": {
      const a = ACTIONS[String(after)] || String(after);
      const b = before === undefined ? null : ACTIONS[String(before)] || String(before);
      return `Action changed${from(b)} to ${a}`;
    }
    case "enabled":
      return after ? "Turned on" : "Turned off";
    case "message":
      return after ? `Message to the user changed to “${after}”` : "Message to the user cleared";
    case "on_block":
      return after === "reask" ? "On a blocked answer: ask the model to fix it" : "On a blocked answer: refuse";
    case "overridable":
      return after ? "Agents may now loosen this rule" : "Agents may no longer loosen this rule";
    default:
      return `${field.replace(/_/g, " ")} changed`;
  }
}

/**
 * A version's notes as a person reads them. The gateway writes a one-rule change as
 * `<rule id>: {'min_score': 0.5}` and, from 0.5.2, `… (was {'min_score': 0.7})`;
 * those become "Sensitivity changed from Medium to High". Notes a person wrote, or
 * any other shape, come back as they are.
 */
export function versionNote(notes: string | null | undefined, ruleTitle?: (id: string) => string): { text: string; rule?: string } {
  const raw = (notes || "").trim();
  const m = /^([a-z0-9_.-]+): (\{.*?\})(?: \(was (\{.*\})\))?$/i.exec(raw);
  if (!m) return { text: raw.charAt(0).toUpperCase() + raw.slice(1) };
  const after = parsePyDict(m[2]);
  if (!after || !Object.keys(after).length) return { text: raw };
  const before = (m[3] && parsePyDict(m[3])) || {};
  const text = Object.entries(after)
    .map(([k, v]) => changeWords(k, v, before[k]))
    .join(" · ");
  return { text, rule: ruleTitle ? ruleTitle(m[1]) : m[1] };
}

// --- business rule names ------------------------------------------------------------------

/** `custom-payments-transfer`: a key, not a name a person gave it. */
function slugLike(name: string): boolean {
  return /^[a-z0-9]+(?:[-_.][a-z0-9]+)+$/.test(name);
}

/**
 * A business rule's name: the one the person typed, or one said from what it does
 * ("Approval limit on payments.transfer") when the rule only has its key.
 */
export function businessRuleName(r: { key?: string; name?: string | null; tool?: string | null; kind?: string | null }): string {
  const name = (r.name || "").trim();
  if (name && name !== r.key && !slugLike(name)) return name;
  const tool = r.tool && r.tool !== "*" ? r.tool : null;
  if (!r.kind || r.kind === "threshold_ladder") return tool ? `Approval limit on ${tool}` : "Approval limit";
  const words = r.kind.replace(/_/g, " ");
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}${tool ? ` on ${tool}` : ""}`;
}

/**
 * The name a compiled approval limit is saved under when the person gives none:
 * "Approval above $100 on payments.transfer".
 */
export function suggestedLadderName(def: { tool?: string | null; unit?: string | null; bands?: { upto?: number | null; outcome: string }[] }): string {
  const bands = def.bands || [];
  const firstHeld = bands.findIndex((b) => b.outcome !== "allow");
  const limit = firstHeld > 0 ? bands[firstHeld - 1]?.upto : null;
  const amount = limit == null ? null : def.unit === "USD" ? `$${limit.toLocaleString("en-US")}` : `${limit.toLocaleString("en-US")}${def.unit ? ` ${def.unit}` : ""}`;
  const tool = def.tool && def.tool !== "*" ? ` on ${def.tool}` : "";
  return amount ? `Approval above ${amount}${tool}` : `Approval limit${tool}`;
}

/**
 * The sentences of what was written that compiled to nothing. A sentence that became
 * the allow band ("Transfers up to $100 run automatically") is used, so it is not
 * listed even when the compiler reports it as ignored.
 */
export function unusedSentences(ignored: string[], rules: { definition?: { bands?: { upto?: number | null; outcome: string }[] } }[]): string[] {
  const allowUpTo = new Set<number>();
  for (const r of rules) for (const b of r.definition?.bands || []) if (b.outcome === "allow" && typeof b.upto === "number") allowUpTo.add(b.upto);
  if (!allowUpTo.size) return ignored;
  return ignored.filter((s) => {
    const says = /\b(automatic|automatically|allowed|no approval|without approval|freely|can run|may run)\b/i.test(s);
    const amounts = (s.match(/\d[\d,]*(?:\.\d+)?/g) || []).map((x) => Number(x.replace(/,/g, "")));
    return !(says && amounts.some((a) => allowUpTo.has(a)));
  });
}

// --- scope of a new rule ------------------------------------------------------------------

/**
 * The agent a new rule starts scoped to: the one the page was opened for, else the
 * project's only agent, else "" (every agent).
 */
export function defaultRuleScope(agent: string | undefined, agents: { slug: string }[]): string {
  if (agent) return agent;
  return agents.length === 1 ? agents[0].slug : "";
}
