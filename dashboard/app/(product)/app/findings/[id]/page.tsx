import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { ApiError, api, apiErrorProps } from "@/lib/product/api";
import { ApiDown, NotFound, findingTypeInfo } from "@/components/ui";
import { Card, Header, Meta, Pill, SeverityPill, ago, num } from "@/components/kit";
import { FindingEvidence } from "@/components/product/FindingEvidence";

export const metadata: Metadata = appPageMetadata("Issue");
export const dynamic = "force-dynamic";

/** The evidence still shows the problem, so "resolved" would be a claim, not a fact. */
function stillLooksUnresolved(finding: any): boolean {
  const ev = finding.evidence || {};
  if (typeof ev.posture_score === "number" && ev.posture_score < 1) return true;
  if (typeof ev.attacks_succeeded === "number" && ev.attacks_succeeded > 0) return true;
  return false;
}

const STATUS: Record<string, { label: string; tone: "warn" | "ok" | "outline" }> = {
  open: { label: "Open", tone: "warn" },
  resolved: { label: "Resolved", tone: "ok" },
  suppressed: { label: "Accepted", tone: "outline" },
};

export default async function IssueDetail({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ review_error?: string }>;
}) {
  const { id } = await params;
  const { review_error } = await searchParams;
  let f: any;
  try {
    f = await api(`/api/findings/${id}`);
  } catch (e: any) {
    return (
      <>
        <Header title="Issue" back={{ href: "/app/findings", label: "Issues" }} />
        {e instanceof ApiError && e.status === 404 ? (
          <NotFound what="issue" detail={id} back={{ href: "/app/findings", label: "Issues" }} />
        ) : (
          <ApiDown {...apiErrorProps(e)} />
        )}
      </>
    );
  }
  const type = findingTypeInfo(f.type);
  const st = STATUS[f.status] || { label: f.status, tone: "outline" as const };

  return (
    <>
      <Header
        back={{ href: "/app/findings", label: "Issues" }}
        title={f.title}
        hint={type.blurb}
        meta={
          <>
            <SeverityPill value={f.severity} />
            <Pill tone={st.tone}>{st.label}</Pill>
          </>
        }
      />
      <Meta
        items={[
          ["Agent", f.agent_slug ? <Link href={`/app/agents/${encodeURIComponent(f.agent_slug)}`}>{f.agent_slug}</Link> : f.subject_id || "—"],
          ["Kind", type.label],
          ["Times", num(f.occurrences || 1)],
          ["First", ago(f.created_at)],
          ["Last", ago(f.last_seen_at || f.created_at)],
        ]}
      />
      <div style={{ height: 14 }} />
      {review_error && <div className="error">{review_error}</div>}

      {f.status === "open" && (
        <Card title="Close this issue">
          {stillLooksUnresolved(f) && (
            <div className="k-muted" style={{ marginBottom: 10 }}>
              The evidence still shows the problem. Accept it instead of marking it fixed.
            </div>
          )}
          <div className="k-form">
            <form action={`/api/findings/${id}`} method="POST" className="k-field">
              <input type="hidden" name="status" value="resolved" />
              <label htmlFor="fix-note">Fixed</label>
              <span className="k-pills" style={{ gap: 8 }}>
                <input id="fix-note" className="k-input" name="note" required placeholder="What fixed it?" style={{ width: 360 }} />
                <button type="submit" className="k-btn-primary">Mark fixed</button>
              </span>
            </form>
            <form action={`/api/findings/${id}`} method="POST" className="k-field">
              <input type="hidden" name="status" value="suppressed" />
              <label htmlFor="accept-note">Not fixing now</label>
              <span className="k-pills" style={{ gap: 8 }}>
                <input id="accept-note" className="k-input" name="suppression_reason" required placeholder="Why is it acceptable?" style={{ width: 360 }} />
                <button type="submit" className="k-btn">Accept</button>
              </span>
            </form>
          </div>
        </Card>
      )}
      {f.status === "suppressed" && (
        <Card>
          <span className="k-muted">Accepted by {f.suppressed_by}: </span>
          {f.suppression_reason}
        </Card>
      )}
      {f.status === "resolved" && (
        <Card>
          <span className="k-muted">Fixed by {f.resolved_by}: </span>
          {f.resolution_note}
        </Card>
      )}

      <Card title="Evidence">
        <FindingEvidence finding={f} />
      </Card>
    </>
  );
}
