import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { api, apiErrorProps } from "@/lib/product/api";
import { Card, Empty, Header, Pill } from "@/components/kit";
import { ApiDown, DraftCaveat, NotFound } from "@/components/ui";
import { ReviewBy, ReviewPill, StatusPill } from "@/components/product/compliance";

export const metadata: Metadata = appPageMetadata("Framework");

export const dynamic = "force-dynamic";

/**
 * One regulation or standard, as requirements. Each requirement (an article or
 * clause the catalog cites) lists the controls mapped to it, each with its status
 * computed from telemetry and its current attestation. A control row opens the
 * control: the rules that implement it, the runs they acted on, the evidence, and
 * the review form.
 */
export default async function FrameworkPage({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;

  let f: any;
  try {
    f = await api(`/api/frameworks/${encodeURIComponent(key)}`);
  } catch (e: any) {
    if (e?.status === 404) {
      return <NotFound what="framework" back={{ href: "/app/compliance?tab=regulations", label: "Regulations" }} />;
    }
    return <ApiDown {...apiErrorProps(e)} />;
  }

  const requirements: any[] = f.requirements_detail || [];
  const counts = f.status_counts || {};
  const att = f.attestations || {};
  const obligations: any[] = f.obligations_detail || [];

  return (
    <>
      <Header
        back={{ href: "/app/compliance?tab=regulations", label: "Regulations" }}
        title={f.title}
        meta={<span className="k-muted">{f.description}</span>}
      />

      <div className="k-grid k-grid-4">
        <div className="k-kpi">
          <div className="k-kpi-label">Requirements</div>
          <div className="k-kpi-value">{requirements.length}</div>
          <div className="k-kpi-foot k-muted">{f.controls_mapped} controls mapped</div>
        </div>
        <div className="k-kpi">
          <div className="k-kpi-label">Controls effective</div>
          <div className="k-kpi-value">{counts.effective || 0}</div>
          <div className="k-kpi-foot k-muted">
            {counts.failing || 0} failing, {counts.degraded || 0} degraded
          </div>
        </div>
        <div className="k-kpi">
          <div className="k-kpi-label">Attested</div>
          <div className="k-kpi-value">{att.current || 0}</div>
          <div className="k-kpi-foot k-muted">
            {att.expired || 0} expired, {att.none || 0} never
          </div>
        </div>
        <div className="k-kpi">
          <div className="k-kpi-label">Next deadline</div>
          <div className="k-kpi-value" style={{ fontSize: 18 }}>
            {f.next_deadline ? f.next_deadline.effective_date.slice(0, 10) : "None"}
          </div>
          <div className="k-kpi-foot k-muted">{f.next_deadline?.reference || ""}</div>
        </div>
      </div>

      <Card title="Requirements" flush>
        {requirements.length === 0 ? (
          <Empty>No control is mapped to this framework.</Empty>
        ) : (
          <table className="k-table">
            <thead>
              <tr>
                <th>Requirement</th>
                <th className="tight">Status</th>
                <th>Control</th>
                <th className="tight">Control status</th>
                <th className="tight">Review</th>
                <th>By</th>
              </tr>
            </thead>
            <tbody>
              {requirements.flatMap((r) =>
                r.controls.map((c: any, i: number) => (
                  <tr key={`${r.clause}:${c.key}`} id={i === 0 ? `req-${encodeURIComponent(r.clause)}` : undefined}>
                    {i === 0 && (
                      <>
                        <td rowSpan={r.controls.length} style={{ verticalAlign: "top" }}>
                          <strong>{r.reference}</strong>
                        </td>
                        <td rowSpan={r.controls.length} className="tight" style={{ verticalAlign: "top" }}>
                          <StatusPill value={r.status} />
                        </td>
                      </>
                    )}
                    <td>
                      <Link className="k-name" href={`/app/compliance/controls/${c.key}?framework=${key}`}>
                        {c.title}
                      </Link>
                      <span className="sub k-mono">{c.key}</span>
                    </td>
                    <td className="tight"><StatusPill value={c.status} /></td>
                    <td className="tight">
                      <Link href={`/app/compliance/controls/${c.key}?framework=${key}#fw-${key}`}>
                        <ReviewPill review={c.review} />
                      </Link>
                    </td>
                    <td><ReviewBy review={c.review} /></td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        )}
      </Card>

      {obligations.length > 0 && (
        <Card title="Deadlines" flush>
          <table className="k-table">
            <thead>
              <tr>
                <th className="tight">Date</th>
                <th>Obligation</th>
                <th className="tight">Status</th>
                <th>Agents in scope</th>
              </tr>
            </thead>
            <tbody>
              {obligations.map((o) => (
                <tr key={o.reference} id={`obligation-${encodeURIComponent(o.reference)}`}>
                  <td className="tight k-mono">{(o.effective_date || "").slice(0, 10)}</td>
                  <td>
                    {requirements.some((r) => r.clause === o.reference) ? (
                      <a className="k-name" href={`#req-${encodeURIComponent(o.reference)}`}>{o.title}</a>
                    ) : (
                      <span className="k-name">{o.title}</span>
                    )}
                    <span className="sub">{o.reference}</span>
                  </td>
                  <td className="tight">
                    <Pill tone={o.status === "live" ? "bad" : "warn"}>
                      {o.status === "live" ? "In force" : `In ${o.days_until} days`}
                    </Pill>
                  </td>
                  <td>
                    {o.agents_in_scope.length === 0 ? (
                      <span className="k-muted">None</span>
                    ) : (
                      o.agents_in_scope.slice(0, 6).map((slug: string, i: number) => (
                        <span key={slug}>
                          {i > 0 && ", "}
                          <Link href={`/app/agents/${encodeURIComponent(slug)}`}>{slug}</Link>
                        </span>
                      ))
                    )}
                    {o.agents_in_scope.length > 6 && <span className="k-muted"> +{o.agents_in_scope.length - 6}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {f.declared_gaps?.length > 0 && (
        <Card title="Not covered" hint="Parts of this framework no control here addresses. Plan for them elsewhere.">
          <ul className="k-plain">
            {f.declared_gaps.map((g: string) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        </Card>
      )}

      <DraftCaveat />
    </>
  );
}
