/** Shared between the Sources page (server) and its add-flow form (client). */

export const TIER_TONE: Record<string, string> = {
  system_of_record: "ok",
  approved: "",
  unverified: "warn",
  external: "bad",
};

export const TIER_OPTIONS: { value: string; label: string }[] = [
  { value: "system_of_record", label: "Official company data, kept up to date" },
  { value: "approved", label: "Reviewed and approved, but not the master copy" },
  { value: "unverified", label: "Reference material — may be outdated" },
  { value: "external", label: "Someone's personal notes, or an outside source" },
];

export const FRESHNESS_OPTIONS: { value: string; label: string }[] = [
  { value: "24", label: "Daily" },
  { value: "168", label: "Weekly" },
  { value: "720", label: "Monthly" },
  { value: "", label: "Rarely / no schedule" },
];

export const inputStyle = {
  width: "100%",
  padding: "6px 9px",
  borderRadius: 6,
  border: "1px solid var(--border)",
  background: "var(--panel-2)",
  color: "var(--text)",
  fontSize: 13,
  fontFamily: "inherit",
} as const;

/**
 * What kind of thing a source key actually is, which decides what you can do
 * with it.
 *
 * The row menu used to offer the same four actions on every row, and two of them
 * are impossible for some of those rows — a fact the page states in its own
 * column tooltips and then ignores:
 *
 *   "url"       The key is an http(s) address. It is fetched directly, so it can
 *               be validated as-is and needs no connection. Offering "Connect a
 *               database or API" here proposes work that changes nothing.
 *   "connected" The key is opaque (a table name, a document id) but a database or
 *               API connection is registered, so validation has something to
 *               reach it through.
 *   "opaque"    The key is neither. NOTHING can check it — the content-check
 *               column renders "not a URL — can't verify" for exactly this case.
 *               Offering "Validate now" here is a button whose only outcome is a
 *               failure the UI already predicted.
 */
export type SourceKind = "url" | "connected" | "opaque";

export function sourceKind(source: { key: string; connection_kind?: string | null }): SourceKind {
  if (source.connection_kind) return "connected";
  return /^https?:\/\//i.test(source.key) ? "url" : "opaque";
}

/** Can this source actually be fetched and its content compared? */
export function canValidate(source: { key: string; connection_kind?: string | null }): boolean {
  return sourceKind(source) !== "opaque";
}
