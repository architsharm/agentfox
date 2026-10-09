import { safeApi } from "@/lib/product/api";
import type { RangeKey } from "@/lib/product/vocab";

type SP = Record<string, string | undefined>;

/**
 * The range a view opens on when the URL names none: the smallest window that holds
 * the latest traffic (a week at least), so a quiet workspace opens on its data
 * rather than on an empty week. Asked of the gateway (`/api/metrics/activity`).
 */
export async function activeRange(agent?: string): Promise<{ range: RangeKey; last: string | null }> {
  const q = agent ? `?agent=${encodeURIComponent(agent)}` : "";
  const a = await safeApi<any>(`/api/metrics/activity${q}`, { range: "7d", last_request_at: null });
  return { range: (a.range || "7d") as RangeKey, last: a.last_request_at };
}

/**
 * For a page whose numbers depend on the range: with no range in the URL, fill in
 * the one that has data, in place, so every component reading ``sp.range`` agrees.
 * Wrap the page in `RangeProvider` with the result so the filter bar shows it. (This
 * redirected to the URL with the range before; that cost a full extra round trip.)
 */
export async function ensureRange(_path: string, sp: SP, agent?: string): Promise<void> {
  if (sp.range) return;
  sp.range = (await activeRange(agent ?? sp.agent)).range;
}
