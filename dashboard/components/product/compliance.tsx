import { Pill, type Tone, ago } from "@/components/kit";

/**
 * Compliance vocabulary, shown the same way on every compliance screen: a control's
 * computed status, a person's attestation of it, and a retention period.
 */

const STATUS: Record<string, { label: string; tone: Tone }> = {
  effective: { label: "Effective", tone: "ok" },
  degraded: { label: "Degraded", tone: "warn" },
  failing: { label: "Failing", tone: "bad" },
  not_implemented: { label: "Not implemented", tone: "outline" },
  not_applicable: { label: "Not applicable", tone: "outline" },
  not_computed: { label: "Not computed", tone: "outline" },
};

export function StatusPill({ value }: { value?: string | null }) {
  const s = STATUS[value || "not_computed"] || { label: value || "", tone: "outline" as Tone };
  return <Pill tone={s.tone}>{s.label}</Pill>;
}

export const OUTCOMES: Record<string, { label: string; tone: Tone }> = {
  meets: { label: "Meets", tone: "ok" },
  partially_meets: { label: "Partially meets", tone: "warn" },
  does_not_meet: { label: "Does not meet", tone: "bad" },
  not_applicable: { label: "Not applicable", tone: "neutral" },
};

export type Review = {
  id: string;
  framework: string;
  outcome: string;
  note: string;
  reviewer: string;
  reviewed_at: string;
  expires_at: string;
  state: "current" | "expired";
  audit_seq?: number | null;
  status_at_review?: string | null;
};

/** An attestation as a pill: the outcome while current, "Expired" once it lapses. */
export function ReviewPill({ review }: { review?: Review | null }) {
  if (!review) return <Pill tone="outline">Not reviewed</Pill>;
  if (review.state === "expired") {
    return (
      <Pill tone="warn" title={`Was "${OUTCOMES[review.outcome]?.label}" until ${review.expires_at.slice(0, 10)}`}>
        Review expired
      </Pill>
    );
  }
  const o = OUTCOMES[review.outcome] || { label: review.outcome, tone: "neutral" as Tone };
  return <Pill tone={o.tone}>{o.label}</Pill>;
}

/** Who reviewed and when, in one muted line. */
export function ReviewBy({ review }: { review?: Review | null }) {
  if (!review) return <span className="k-muted">—</span>;
  return (
    <span className="k-muted" title={review.reviewed_at}>
      {review.reviewer}, {ago(review.reviewed_at)}
    </span>
  );
}

export function days(n?: number | null): string {
  if (n === null || n === undefined) return "Kept indefinitely";
  if (n % 365 === 0) return `${n / 365} year${n === 365 ? "" : "s"}`;
  return `${n} day${n === 1 ? "" : "s"}`;
}
