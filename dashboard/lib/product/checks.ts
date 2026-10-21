import { detectorName } from "@/lib/product/vocab";

/** A check, as the Checks catalogue describes it. */
export type CheckInfo = { key: string; label: string; source: string; surfaces: string[]; available: boolean; finds?: string };

/** What kind of check each source is, in a word. */
export const CHECK_KIND: Record<string, string> = { builtin: "Regex", open_source: "ML", yours: "Custom", llm_judge: "LLM" };

const NAMES: Record<string, string> = {
  "custom.validators": "Your validator rules",
  "injection.judgment": "Prompt injection (judge)",
  "validator.prompt_injection_llm": "Prompt injection (validator judge)",
};
export const checkName = (d: { key: string; label: string }) => NAMES[d.key] || d.label || detectorName(d.key);

/** The checks that can fire a rule: they report the kind of finding it looks for. */
export function checksFor(finds: string, catalog: CheckInfo[]): CheckInfo[] {
  const kind = finds.split(".")[0];
  return kind ? catalog.filter((d) => d.finds === kind) : [];
}
