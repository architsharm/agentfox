import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { ApiError, api, apiErrorProps, safeApi } from "@/lib/product/api";
import { ApiDown, NotFound } from "@/components/ui";
import { Card, Header, Meta, Pill, when } from "@/components/kit";
import { Countdown } from "@/components/product/Countdown";
import {
  STATUS_TONE,
  actionArguments,
  actionLabel,
  decidedBy,
  endedLabel,
  isMessage,
  readableReason,
  type Approval,
} from "@/lib/product/approvals";

export const metadata: Metadata = appPageMetadata("Approval");
export const dynamic = "force-dynamic";

const BACK = { href: "/app/approvals?tab=history", label: "Approvals" };

/** One approval: what was asked, why it was held, and how it ended. */
export default async function ApprovalDetail({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const { id } = await params;
  const sp = await searchParams;

  let a: Approval;
  try {
    a = await api<Approval>(`/api/approvals/${encodeURIComponent(id)}`);
  } catch (e: any) {
    return (
      <>
        <Header title="Approval" back={BACK} />
        {e instanceof ApiError && e.status === 404 ? (
          <NotFound what="approval" detail={id} back={BACK} />
        ) : (
          <ApiDown {...apiErrorProps(e)} />
        )}
      </>
    );
  }

  const agents = await safeApi<any>("/api/agents", { agents: [] });
  const agent = (agents.agents || []).find((x: any) => x.id === a.agent_id);
  const args = actionArguments(a);
  const self = `/app/approvals/${encodeURIComponent(a.id)}`;
  const pending = a.status === "pending";

  return (
    <>
      <Header
        title={actionLabel(a)}
        back={BACK}
        meta={<Pill tone={pending ? "held" : STATUS_TONE[a.status] || "neutral"}>{a.status}</Pill>}
        actions={
          pending ? (
            <>
              <form action={`/api/approvals/${a.id}/deny`} method="POST">
                <input type="hidden" name="return_to" value={self} />
                <button type="submit" className="k-btn-danger">Deny</button>
              </form>
              <form action={`/api/approvals/${a.id}/approve`} method="POST">
                <input type="hidden" name="return_to" value={self} />
                <button type="submit" className="k-btn-primary">Approve</button>
              </form>
            </>
          ) : undefined
        }
      />
      {sp.review_error && <div className="error">{sp.review_error}</div>}
      {sp.review_notice && <div className="note-panel">Request {sp.review_notice}.</div>}

      <Card>
        <Meta
          items={[
            ["Agent", agent ? <Link href={`/app/agents/${agent.slug}`}>{agent.name || agent.slug}</Link> : "—"],
            ["Requested", when(a.requested_at)],
            pending
              ? ["Expires", <Countdown key="exp" at={a.expires_at} />]
              : [endedLabel(a.status), when(a.resolved_at)],
            ["Decided by", decidedBy(a) || "—"],
            ["Run", a.trace_id ? <Link href={`/app/traces/${a.trace_id}`}>Open</Link> : "—"],
            ["Id", <span key="id" className="k-mono">{a.id}</span>],
          ]}
        />
      </Card>

      <Card title={isMessage(a) ? "Message" : "Arguments"}>
        {isMessage(a) ? (
          <blockquote className="k-quote">{args[0]?.[1] || "—"}</blockquote>
        ) : args.length ? (
          <table className="k-table">
            <tbody>
              {args.map(([k, v]) => (
                <tr key={k}>
                  <td className="tight muted">{k}</td>
                  <td className="k-mono">{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <span className="k-muted">No arguments.</span>
        )}
      </Card>

      <Card title="Why it was held">
        <p style={{ margin: 0 }}>{readableReason(a.reason) || "—"}</p>
        {a.rationale && (
          <p className="k-muted" style={{ marginBottom: 0 }}>
            Note from {a.resolver || "the approver"}: {a.rationale}
          </p>
        )}
      </Card>
    </>
  );
}
