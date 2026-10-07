import { safeApi } from "@/lib/product/api";

/**
 * Every place a bare control code (e.g. "NOM-RTG-09") used to render alone —
 * Findings, Trace detail, the framework-review page — required a trip to the
 * Compliance page or the Glossary to learn what it actually checks. No
 * comparable product (per the terminology research behind this change) ever
 * shows a control identifier without its plain-English title in the same
 * breath, so this is the one place that mapping gets built.
 */
export async function controlTitleMap(): Promise<Record<string, string>> {
  const controls = await safeApi<{ controls?: { key: string; title: string }[] }>(
    "/api/controls",
    { controls: [] },
  );
  const map: Record<string, string> = {};
  for (const c of controls.controls || []) map[c.key] = c.title;
  return map;
}
