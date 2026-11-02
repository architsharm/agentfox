/**
 * How an approval reads on the Approvals pages.
 *
 * A held tool call carries the tool and its arguments. A held message is filed as
 * `message:<surface>` with `{surface, content, content_sha256}` (see
 * `runtime/enforcement/approvals.py`); shown raw, the approver read a digest and the
 * word "message:input" instead of the message.
 */

export type Approval = {
  id: string;
  agent_id?: string | null;
  tool?: string | null;
  arguments?: Record<string, unknown> | null;
  reason?: string | null;
  status: string;
  requested_at?: string | null;
  expires_at?: string | null;
  resolved_at?: string | null;
  resolver?: string | null;
  rationale?: string | null;
  trace_id?: string | null;
  /** `deny` (the default) or `allow`: what an unanswered request turns into. */
  timeout_action?: string | null;
};

export const STATUS_TONE: Record<string, "ok" | "bad" | "warn" | "neutral"> = {
  approved: "ok",
  used: "ok",
  denied: "bad",
  expired: "warn",
};

const SURFACE: Record<string, string> = {
  input: "Message in",
  output: "Reply",
  agent_message: "Agent message",
};

export function isMessage(a: Pick<Approval, "tool">): boolean {
  return String(a.tool || "").startsWith("message:");
}

/** The action, in a few words: the tool key, or what kind of message was held. */
export function actionLabel(a: Pick<Approval, "tool">): string {
  const tool = String(a.tool || "");
  if (!isMessage(a)) return tool || "Unknown action";
  const surface = tool.slice("message:".length);
  return SURFACE[surface] || `Message (${surface.replace(/_/g, " ")})`;
}

function show(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v);
}

/** The arguments a person decides on. A held message is its content, not its digest. */
export function actionArguments(a: Pick<Approval, "tool" | "arguments">): [string, string][] {
  const args = a.arguments || {};
  if (isMessage(a)) return args.content != null ? [["content", show(args.content)]] : [];
  return Object.entries(args).map(([k, v]) => [k, show(v)]);
}

/** One line for a table cell. */
export function actionSummary(a: Pick<Approval, "tool" | "arguments">): string {
  if (isMessage(a)) return actionArguments(a)[0]?.[1] || "";
  return actionArguments(a)
    .map(([k, v]) => `${k}: ${v}`)
    .join(" · ");
}

/** A span of minutes in words: "45 min", "2 h", "1 h 5 min", "3 days". */
export function minutesLabel(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return `${m} min`;
  if (m < 48 * 60) {
    const h = Math.floor(m / 60);
    const rest = m % 60;
    return rest ? `${h} h ${rest} min` : `${h} h`;
  }
  return `${Math.round(m / (24 * 60))} days`;
}

/** Minutes between filing and expiry: how long a request waits for a person. */
export function waitMinutes(a: Pick<Approval, "requested_at" | "expires_at">): number | null {
  const from = Date.parse(String(a.requested_at || ""));
  const to = Date.parse(String(a.expires_at || ""));
  if (Number.isNaN(from) || Number.isNaN(to) || to < from) return null;
  return Math.round((to - from) / 60000);
}

/** Who ended it: the person who decided, or nobody when it ran out unanswered, and after how long. */
export function decidedBy(a: Pick<Approval, "status" | "resolver" | "requested_at" | "expires_at">): string | null {
  if (a.status === "pending") return null;
  if (a.resolver) return a.resolver;
  if (a.status !== "expired") return null;
  // An expired request kept its expiry; it waited from filing to then.
  const waited = waitMinutes(a);
  return waited === null ? "Nobody answered" : `Nobody answered in ${minutesLabel(waited)}`;
}

/** What happens to a held call nobody answers, from its `timeout_action`. Fails closed by default. */
export function onExpiry(timeoutAction?: string | null): string {
  return timeoutAction === "allow" ? "it is approved and may run once" : "it is denied and the call does not run";
}

/** How long requests wait before they expire: what the waiting ones carry, else the gateway default. */
export const DEFAULT_WAIT_MINUTES = 30;

/** The reason as prose. Several rules' reasons arrive joined with "; ", after each one's
 *  own full stop, which read as "action.; Irreversible". */
export function readableReason(reason?: string | null): string {
  // Two rules can give the same reason; say it once.
  const parts = String(reason || "")
    .split(/;\s+/)
    .map((p) => p.trim())
    .filter(Boolean);
  return Array.from(new Set(parts))
    .map((p, i, all) => (i < all.length - 1 && !/[.!?]$/.test(p) ? `${p};` : p))
    .join(" ");
}

/** When the approval reached its status, under the right word. */
export function endedLabel(status: string): string {
  return status === "used" ? "Used" : status === "expired" ? "Expired" : status === "lapsed" ? "Lapsed" : "Decided";
}

/** The reason's first sentence, for a card line. Not cut at "Art." in "EU AI Act Art. 14". */
export function firstSentence(reason?: string | null): string {
  const text = readableReason(reason);
  const m = text.match(/^(.{25,}?[.!?])\s+(?=[A-Z])/);
  return m ? m[1] : text;
}
