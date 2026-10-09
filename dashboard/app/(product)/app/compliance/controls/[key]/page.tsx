import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { api, apiErrorProps } from "@/lib/product/api";
import { Card, Empty, Header, Meta, ModePill, Pill, SeverityPill, ago } from "@/components/kit";
import { ApiDown, NotFound } from "@/components/ui";
import { OUTCOMES, ReviewBy, ReviewPill, StatusPill, type Review } from "@/components/product/compliance";
import { ruleTitle } from "@/lib/product/vocab";

export const metadata: Metadata = appPageMetadata("Control");

export const dynamic = "force-dynamic";

/**
 * One control, end to end: what the platform computed for it (status, the rules
 * that implement it, when they last fired, the runs they fired in, open findings,
 * evidence packages), where it is mapped, and the attestations people have made
 * against it. Recording a review freezes the evidence shown here onto the review.
 */
export default async function ControlPage({
  params,
  searchParams,
}: {
  params: Promise<{ key: string }>;
  searchParams: Promise<{ framework?: string; review_error?: string; review_notice?: string }>;
}) {
  const { key } = await params;
  const { framework: preselect, review_error, review_notice } = await searchParams;

  let c: any;
  try {
    c = await api(`/api/controls/${encodeURIComponent(key)}`);
  } catch (e: any) {
    if (e?.status === 404) return <NotFound what="control" back={{ href: "/app/compliance", label: "Compliance" }} />;
    return <ApiDown {...apiErrorProps(e)} />;
  }

  const ev = c.evidence;
  const frameworks: any[] = c.frameworks || [];
  const history: Review[] = c.history || [];

  return (
    <>
      <Header
        back={{ href: preselect ? `/app/compliance/frameworks/${preselect}` : "/app/compliance", label: preselect ? "Framework" : "Compliance" }}
        title={c.title}
        meta={
          <>
            <span className="k-mono k-muted">{c.key}</span> <StatusPill value={ev.status} />
          </>
        }
      />

      {review_error && <div className="error">{review_error}</div>}
      {review_notice && <div className="note-panel">{review_notice}</div>}

      <p className="sub">{c.objective}</p>

      <Card title="Computed from telemetry" hint="Recomputed daily from this workspace's own traffic, not attested.">
        <Meta
          items={[
            ["Status", <StatusPill key="s" value={ev.status} />],
            ["Computed", ev.computed_at ? ago(ev.computed_at) : "Never"],
            ["Rules fired", `${ev.fires} decision${ev.fires === 1 ? "" : "s"} in ${ev.fired_window_days} days`],
            ["Last fired", ev.last_fired ? ago(ev.last_fired) : "—"],
          ]}
        />
        <p className="small muted" style={{ marginTop: 10 }}>{ev.rationale || "No status computed yet."}</p>
      </Card>

      <Card title="Rules that implement it" flush>
        {ev.rules.length === 0 ? (
          <Empty>No bound rule names this control. Its status comes from telemetry alone.</Empty>
        ) : (
          <table className="k-table">
            <thead>
              <tr>
                <th>Rule</th>
                <th>Policy</th>
                <th className="tight">Mode</th>
                <th className="tight num">Fires</th>
                <th className="tight">Last fired</th>
              </tr>
            </thead>
            <tbody>
              {ev.rules.map((r: any) => (
                <tr key={`${r.policy}:${r.rule_id}`}>
                  <td>
                    <Link className="k-name" href={`/app/policies/rules/${encodeURIComponent(r.rule_id)}`}>
                      {ruleTitle(r.rule_id, r.description)}
                    </Link>
                    <span className="sub k-mono">{r.rule_id}</span>
                  </td>
                  <td>
                    <Link href={`/app/policies/${encodeURIComponent(r.policy)}`}>{r.policy_name}</Link>
                  </td>
                  <td className="tight">{r.enabled ? <ModePill mode={r.mode} /> : <Pill tone="outline">Off</Pill>}</td>
                  <td className="tight num">{r.fires}</td>
                  <td className="tight muted">{r.last_fired ? ago(r.last_fired) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="Runs it acted on" flush>
        {ev.runs.length === 0 ? (
          <Empty>No run in the last {ev.fired_window_days} days fired a rule for this control.</Empty>
        ) : (
          <table className="k-table">
            <thead>
              <tr>
                <th className="tight">When</th>
                <th>Run</th>
                <th>Rule</th>
                <th className="tight">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {ev.runs.map((r: any) => (
                <tr key={r.trace_id}>
                  <td className="tight muted">{ago(r.at)}</td>
                  <td>
                    <Link className="k-mono" href={`/app/traces/${r.trace_id}`}>{r.trace_id}</Link>
                  </td>
                  <td className="muted">{ruleTitle(r.rule_id)}</td>
                  <td className="tight">
                    <Pill tone={r.verdict === "block" ? "bad" : r.verdict === "escalate" ? "held" : "neutral"}>
                      {r.verdict}
                      {r.mode === "observe" ? " (watching)" : ""}
                    </Pill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {(ev.open_findings.length > 0 || ev.evidence_packages.length > 0) && (
        <div className="k-grid k-grid-2">
          <Card title="Open findings" flush>
            {ev.open_findings.length === 0 ? (
              <Empty>None open.</Empty>
            ) : (
              <ul className="k-list">
                {ev.open_findings.map((f: any) => (
                  <li key={f.id}>
                    <div className="k-list-main">
                      <Link href={`/app/findings/${f.id}`}>{f.title}</Link>
                      <span className="muted">{ago(f.created_at)}</span>
                    </div>
                    <div className="k-list-end"><SeverityPill value={f.severity} /></div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Evidence packages" flush>
            {ev.evidence_packages.length === 0 ? (
              <Empty action={<Link href="/app/reports?tab=evidence">Build one</Link>}>None built.</Empty>
            ) : (
              <ul className="k-list">
                {ev.evidence_packages.map((p: any) => (
                  <li key={p.id}>
                    <div className="k-list-main">
                      <span>{ago(p.built_at)}</span>
                      <span className="muted">{p.requested_by}</span>
                    </div>
                    <div className="k-list-end">
                      <Pill tone={p.chain_valid ? "ok" : "bad"}>{p.chain_valid ? "Chain verified" : "Chain broken"}</Pill>
                      <a href={`/api/evidence/${p.id}/download`}>Download</a>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}

      <Card
        title="Attestations"
        hint={`A named reviewer records whether this control meets each framework's requirement, on the evidence above. A review lasts ${c.valid_days} days and is recorded on the audit chain.`}
        flush
      >
        <table className="k-table">
          <thead>
            <tr>
              <th>Framework</th>
              <th>Requirement</th>
              <th className="tight">Review</th>
              <th>By</th>
              <th className="tight">Expires</th>
            </tr>
          </thead>
          <tbody>
            {frameworks.map((f) => (
              <tr key={f.framework} id={`fw-${f.framework}`}>
                <td>
                  <Link className="k-name" href={`/app/compliance/frameworks/${f.framework}`}>{f.title}</Link>
                </td>
                <td className="muted">{f.references.join(", ")}</td>
                <td className="tight"><ReviewPill review={f.review} /></td>
                <td><ReviewBy review={f.review} /></td>
                <td className="tight muted">{f.review ? f.review.expires_at.slice(0, 10) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {frameworks.length > 0 && (
        <Card title="Record a review">
          <form action={`/api/controls/${encodeURIComponent(c.key)}/reviews`} method="POST" className="k-form">
            <div className="k-field">
              <label htmlFor="rv-fw">Framework</label>
              <select id="rv-fw" name="framework" className="k-select" defaultValue={preselect || frameworks[0].framework}>
                {frameworks.map((f) => (
                  <option key={f.framework} value={f.framework}>{f.title}</option>
                ))}
              </select>
            </div>
            <div className="k-field">
              <label htmlFor="rv-outcome">Outcome</label>
              <select id="rv-outcome" name="outcome" className="k-select" defaultValue="meets">
                {(c.outcomes as string[]).map((o) => (
                  <option key={o} value={o}>{OUTCOMES[o]?.label || o}</option>
                ))}
              </select>
            </div>
            <div className="k-field">
              <label htmlFor="rv-note">Note</label>
              <textarea
                id="rv-note"
                name="note"
                className="k-input"
                rows={3}
                placeholder="Required unless it meets. What you checked, and what is missing."
              />
            </div>
            <div className="k-field">
              <span />
              <div>
                <button type="submit" className="k-btn-primary">Record review</button>{" "}
                <span className="small muted">You are recorded as the reviewer.</span>
              </div>
            </div>
          </form>
        </Card>
      )}

      {history.length > 0 && (
        <Card title="Review history" flush>
          <table className="k-table">
            <thead>
              <tr>
                <th className="tight">When</th>
                <th>Framework</th>
                <th className="tight">Outcome</th>
                <th>Reviewer</th>
                <th>Note</th>
                <th className="tight">Status then</th>
                <th className="tight num">Audit entry</th>
              </tr>
            </thead>
            <tbody>
              {history.map((r) => (
                <tr key={r.id}>
                  <td className="tight muted" title={r.reviewed_at}>{r.reviewed_at.slice(0, 10)}</td>
                  <td>{frameworks.find((f) => f.framework === r.framework)?.title || r.framework}</td>
                  <td className="tight"><ReviewPill review={r} /></td>
                  <td>{r.reviewer}</td>
                  <td className="muted">{r.note || "—"}</td>
                  <td className="tight"><StatusPill value={r.status_at_review} /></td>
                  <td className="tight num k-mono">
                    {r.audit_seq ? <Link href="/app/reports?tab=audit">#{r.audit_seq}</Link> : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
