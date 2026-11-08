import { detectorName } from "@/lib/product/vocab";

/** A check, as the Checks catalogue describes it. */
export type CheckInfo = {
  key: string;
  label: string;
  source: string;
  surfaces: string[];
  available: boolean;
  finds?: string;
  /** Switched on for the workspace (`GET /api/detectors`); absent: not known. */
  enabled?: boolean;
  /** Why it cannot run here, when it cannot (`unavailable_reason`). */
  unavailable?: string | null;
};

/** What kind of check each source is, in a word. */
export const CHECK_KIND: Record<string, string> = { builtin: "Regex", open_source: "ML", yours: "Custom", llm_judge: "LLM" };

/**
 * Names the catalogue leaves blank, or gives twice: `validator.prompt_injection_llm`
 * is labelled "Prompt injection (judge)" upstream, the same as our own
 * `injection.judgment`, so it is named by where it comes from.
 */
const NAMES: Record<string, string> = {
  "custom.validators": "Your validator rules",
  "injection.judgment": "Prompt injection (judge)",
  "validator.prompt_injection_llm": "Prompt injection (Guardrails AI judge)",
};

/** `custom.validators` → "Custom validators": never a raw key on screen. */
function humanize(key: string): string {
  const words = key.replace(/^validator\./, "").replace(/[._-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const checkName = (d: { key: string; label?: string | null }) => {
  if (NAMES[d.key]) return NAMES[d.key];
  const known = detectorName(d.key);
  if (known !== d.key) return known;
  return d.label || humanize(d.key);
};

/**
 * Why a check that could feed a rule is not protecting anything, in a few words:
 * "off", "model not downloaded", "no judge on", "not installed". Null when it runs.
 */
export function checkIdle(d: Pick<CheckInfo, "available" | "enabled" | "source" | "unavailable">): string | null {
  if (!d.available) {
    if (d.source === "llm_judge") return "no judge on";
    if (/not downloaded|pull/i.test(d.unavailable || "") || d.source === "open_source") return "model not downloaded";
    return "not installed";
  }
  if (d.enabled === false) return "off";
  return null;
}

/** The checks that can fire a rule: they report the kind of finding it looks for. */
export function checksFor(finds: string, catalog: CheckInfo[]): CheckInfo[] {
  const kind = finds.split(".")[0];
  return kind ? catalog.filter((d) => d.finds === kind) : [];
}
