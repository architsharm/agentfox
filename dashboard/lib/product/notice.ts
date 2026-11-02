/**
 * The one-line result a form post leaves on the page it redirects back to.
 *
 * Routes put it in the query string (`review_notice` on success, `review_error` on
 * failure; see proxy.ts). Shown raw it read "Done: agent quarantined." in a grey bar
 * that never went away and came back on every reload. These helpers say it in plain
 * words and take it out of the URL once it has been shown.
 */

export const NOTICE_PARAMS = ["review_notice", "review_error"] as const;

/** Notices the routes send in their own shorthand, in the words a person would use. */
const PLAIN: Record<string, string> = {
  "agent quarantined": "Agent paused",
  "agent killed": "Agent stopped",
  "agent resumed": "Agent resumed",
  approved: "Request approved",
  denied: "Request denied",
  acknowledged: "Hand-off acknowledged",
};

/** Prefixes pages used to wrap a notice in; the plain text never needs them. */
const PREFIX = /^(done|saved|request)\s*:?\s+/i;

/**
 * A notice as a sentence: known shorthand mapped to plain words, anything else
 * capitalised and ended with a full stop. Empty in, empty out.
 */
export function noticeText(raw?: string | null): string {
  let text = String(raw || "").trim();
  if (!text) return "";
  const known = PLAIN[text.toLowerCase().replace(/[.!]+$/, "")];
  if (known) return `${known}.`;
  const unwrapped = text.replace(PREFIX, "");
  const again = PLAIN[unwrapped.toLowerCase().replace(/[.!]+$/, "")];
  if (again) return `${again}.`;
  text = text.charAt(0).toUpperCase() + text.slice(1);
  return /[.!?)]$/.test(text) ? text : `${text}.`;
}

/**
 * The URL with the notice params removed, as a path + query + hash for
 * `router.replace`; null when there was nothing to remove.
 */
export function withoutNoticeParams(href: string): string | null {
  const url = new URL(href, "http://x");
  if (!NOTICE_PARAMS.some((p) => url.searchParams.has(p))) return null;
  for (const p of NOTICE_PARAMS) url.searchParams.delete(p);
  const qs = url.searchParams.toString();
  return `${url.pathname}${qs ? `?${qs}` : ""}${url.hash}`;
}

/** How long a success notice stays up. Errors stay until dismissed. */
export const NOTICE_MS = 5000;
