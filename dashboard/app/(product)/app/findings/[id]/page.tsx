import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import { ApiError, api, safeApi, apiErrorProps } from "@/lib/product/api";
import { AgentLink, ApiDown, ControlChip, NotFound, Severity, findingTypeInfo, ts } from "@/components/ui";
import { Breadcrumbs } from "@/components/product/Breadcrumbs";
import { FindingEvidence } from "@/components/product/FindingEvidence";
import { controlTitleMap } from "@/lib/product/controls";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata("Finding");

export const dynamic = "force-dynamic";

/** True when the evidence attached to this finding still shows the underlying
 * problem — used to warn before letting someone mark it resolved without the
 * numbers actually having changed. */
function stillLooksUnresolved(finding: any): boolean {
  const ev = finding.evidence || {};
  if (typeof ev.posture_score === "number" && ev.posture_score < 1) return true;
  if (typeof ev.attacks_succeeded === "number" && ev.attacks_succeeded > 0) return true;
  return false;
}

export default async function FindingDetail({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ review_error?: string }>;
}) {
  const { id } = await params;
  const { review_error } = await searchParams;
  let finding: any, agents: any, controlTitles: Record<string, string>;
  try {
    [finding, agents, controlTitles] = await Promise.all([
      api(`/api/findings/${id}`),
      safeApi("/api/agents", { agents: [] }),
      controlTitleMap(),
    ]);
  } catch (e: any) {
    return (
      <>
        <h1>Finding</h1>
        {e instanceof ApiError && e.status === 404 ? (
          <NotFound what="finding" detail={id} back={{ href: "/app/findings", label: "Findings" }} />
        ) : (
          <ApiDown {...apiErrorProps(e)} />
        )}
      </>
    );
  }

  return (
    <>
      <Breadcrumbs crumbs={[{ label: "Findings", href: "/app/findings" }]} />
      <h1 className="wrap">{finding.title}</h1>
      <p className="sub">
        <Severity value={finding.severity} />{" "}
        <span className="small muted">{findingTypeInfo(finding.type).label}</span>{" "}
        <span className="small muted">raised {ts(finding.created_at)}</span>
      </p>
      {findingTypeInfo(finding.type).blurb && (
        <p className="small muted" style={{ marginTop: -16, marginBottom: 18 }}>
          {findingTypeInfo(finding.type).blurb}
        </p>
      )}

      {review_error && <div className="error">{review_error}</div>}

      <div className="row small" style={{ marginBottom: 14, gap: 16 }}>
        <span>
          <span className="muted">status </span>
          <span className={`tag ${finding.status === "open" ? "warn" : finding.status === "resolved" ? "ok" : ""}`}>
            {finding.status}
          </span>
        </span>
        <span>
          <span className="muted">agent </span>
          {finding.agent_slug ? (
            <AgentLink slug={finding.agent_slug} agents={agents.agents || []} />
          ) : (
            <span className="mono">{finding.subject_id || "—"}</span>
          )}
        </span>
        {finding.controls?.length > 0 && (
          <span>
            <span className="muted">controls </span>
            {finding.controls.map((c: string) => (
              <ControlChip key={c} code={c} titles={controlTitles} />
            ))}
          </span>
        )}
      </div>

      {finding.status === "open" && (
        <>
          {stillLooksUnresolved(finding) && (
            <div className="caveat" style={{ marginBottom: 14 }}>
              <strong>The evidence below still shows the problem.</strong>
              This finding's own numbers (blocked/succeeded, posture) haven't changed
              since it was raised. If you haven't actually fixed the underlying issue,
              use <em>Suppress</em> instead — marking this resolved will make it
              disappear from dashboards as if it were fixed.
            </div>
          )}
          {/* Two opposed actions, each with its own required free-text field, were
              laid out as one horizontal row: input, button, input, button. Which
              input belonged to which button was left to the reader, and the two
              outcomes are not interchangeable — one says the problem is gone, the
              other says it is still here and we accept it. Stacked, each with its
              own explanation attached rather than one shared sentence underneath
              both. */}
          <div className="decide">
            <form action={`/api/findings/${id}`} method="POST" className="decide-opt">
              <input type="hidden" name="status" value="resolved" />
              <div className="decide-what">
                <strong>Mark resolved</strong>
                <span>The underlying problem is actually fixed.</span>
              </div>
              <div className="decide-do">
                <input
                  type="text"
                  name="note"
                  placeholder="What did you do to fix it?"
                  required
                  aria-label="What did you do to fix it?"
                />
                <button type="submit" className="btn-approve">Mark resolved</button>
              </div>
            </form>

            <form action={`/api/findings/${id}`} method="POST" className="decide-opt">
              <input type="hidden" name="status" value="suppressed" />
              <div className="decide-what">
                <strong>Suppress</strong>
                <span>
                  Not acting on it right now. It stays flagged as a known, accepted
                  issue rather than looking fixed.
                </span>
              </div>
              <div className="decide-do">
                <input
                  type="text"
                  name="suppression_reason"
                  placeholder="Why are you accepting it?"
                  required
                  aria-label="Why are you accepting it?"
                />
                <button type="submit" className="btn-reject">Suppress</button>
              </div>
            </form>
          </div>
        </>
      )}
      {finding.status === "suppressed" && (
        <div className="note-panel" style={{ marginBottom: 20 }}>
          <strong>Suppressed (not fixed) by {finding.suppressed_by}</strong>
          {finding.suppression_reason}
        </div>
      )}
      {finding.status === "resolved" && (
        <div className="note-panel" style={{ marginBottom: 20 }}>
          <strong>Resolved by {finding.resolved_by}</strong>
          {finding.resolution_note}
        </div>
      )}

      <h2>What we found</h2>
      <FindingEvidence finding={finding} />
    </>
  );
}
