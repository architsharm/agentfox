import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { redirect } from "next/navigation";
import { api, apiErrorProps } from "@/lib/product/api";
import { ApiDown, ControlStatus, DraftCaveat, InfoTip, StatusBar, pct, ts } from "@/components/ui";
import { REPORTS_TABS } from "@/components/product/AreaTabs";
import { Card, Empty, Header, Pill, Tabs, ago } from "@/components/kit";
import { days } from "@/components/product/compliance";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata(
  "Compliance",
  "Framework and control status computed from this workspace's telemetry.",
);

export const dynamic = "force-dynamic";

const inputStyle = {
  width: "100%",
  padding: "6px 9px",
  borderRadius: 6,
  border: "1px solid var(--border)",
  background: "var(--panel-2)",
  color: "var(--text)",
  fontSize: 13,
  fontFamily: "inherit",
  marginTop: 4,
} as const;

const TABS: { key: string; label: string }[] = [
  { key: "controls", label: "Controls" },
  { key: "regulations", label: "Regulations" },
  { key: "risk", label: "Risk register" },
  { key: "retention", label: "Retention & legal hold" },
];

/** Older links to the two tabs Regulations replaced. */
const TAB_ALIASES: Record<string, string> = { frameworks: "regulations", obligations: "regulations" };

export default async function Compliance({
  searchParams,
}: {
  searchParams: Promise<{ review_error?: string; review_notice?: string; tab?: string }>;
}) {
  const { review_error, review_notice, tab: rawTab } = await searchParams;
  // Evidence and the board summary moved to their own Reports tabs.
  if (rawTab === "evidence") redirect("/app/reports?tab=evidence");
  if (rawTab === "board") redirect("/app/reports");
  const wanted = TAB_ALIASES[rawTab || ""] || rawTab;
  // Controls is the default because /findings and /policies deep-link to
  // /compliance#<control-key> — a control anchor that lands on the wrong tab
  // never scrolls into view, so the tab that owns those anchors has to be first.
  const tab = TABS.some((t) => t.key === wanted) ? wanted! : "controls";

  let controls: any, frameworks: any, register: any, retention: any;
  try {
    [controls, frameworks, register, retention] = await Promise.all([
      api("/api/controls"),
      api("/api/frameworks"),
      api("/api/risk/register"),
      api("/api/retention"),
    ]);
  } catch (e: any) {
    return (
      <>
        <Header title="Reports" />
        <Tabs items={REPORTS_TABS} active="compliance" />
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }

  const counts = controls.posture.counts || {};
  const catalogLoaded = controls.controls.length > 0;
  const assessed = (counts.effective || 0) + (counts.degraded || 0) + (counts.failing || 0);

  return (
    <>
      <Header title="Reports" />
      <Tabs items={REPORTS_TABS} active="compliance" />

      {review_error && <div className="error">{review_error}</div>}
      {review_notice && <div className="note-panel">{review_notice}</div>}

      {!catalogLoaded && (
        <div className="hero empty" style={{ marginBottom: 20 }}>
          <div className="hero-title">Control catalog not loaded</div>
          <p>
            This deployment has never loaded the reference control catalog, so every
            count below reads zero.
            <InfoTip text="The catalog is the fixed set of controls and their mappings to EU AI Act, NIST AI RMF, ISO/IEC 42001 and the rest. Loading it is idempotent, so it is safe to run again later when the catalog version changes." />
          </p>
          <form action="/api/compliance/sync" method="POST">
            <button type="submit" className="btn-primary">
              Load control catalog
            </button>
          </form>
        </div>
      )}

      <DraftCaveat />

      <StatusBar
        segments={[
          { n: counts.effective || 0, label: "effective", tone: "ok" },
          { n: counts.degraded || 0, label: "degraded", tone: "warn" },
          { n: counts.failing || 0, label: "failing", tone: "bad" },
          { n: counts.not_implemented || 0, label: "not implemented", tone: "idle" },
          { n: counts.not_computed || 0, label: "not computed", tone: "idle" },
        ]}
        total={pct(controls.posture.effectiveness)}
        unit={`effective of the ${assessed} control(s) with telemetry to assess; the ${counts.not_implemented || 0} not yet implemented are left out of the ratio, not counted as failing`}
      />

      {/* Sections of Compliance, under the Reports tab bar — chips rather than a
          second underlined tab row, so the two levels never look alike. */}
      <div className="chipbar">
        {TABS.map((t) => {
          const n: Record<string, number> = {
            controls: controls.controls.length,
            regulations: frameworks.frameworks.length,
            risk: register.register.length,
            retention: retention.legal_holds.filter((h: any) => !h.released_at).length,
          };
          return (
            <Link
              key={t.key}
              href={t.key === "controls" ? "/app/compliance" : `/app/compliance?tab=${t.key}`}
              className={tab === t.key ? "chip active" : "chip"}
            >
              {t.label}
              {n[t.key] ? <span className="chip-n">{n[t.key]}</span> : null}
            </Link>
          );
        })}
      </div>

      {tab === "controls" && (
        <>
          <h2 style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span>Controls</span>
            {catalogLoaded && (
              <div className="row" style={{ gap: 10 }}>
                {counts.not_computed > 0 && (
                  <span className="small muted">
                    {counts.not_computed} never computed. They need real traffic.{" "}
                    <Link href="/app/start">Connect an agent</Link>
                  </span>
                )}
                <form action="/api/compliance/compute" method="POST">
                  <button type="submit" className="btn-scan" style={{ fontWeight: 400 }}>
                    Recompute status from telemetry
                  </button>
                </form>
              </div>
            )}
          </h2>
          <p className="sub">
            Every control this product can check, and whether your own telemetry says it
            is holding. Open one for its rules, runs, evidence and reviews.
            <InfoTip text="The rationale says what the telemetry actually found, which is usually enough to tell whether the fix is a configuration change or more traffic. Grey is not a bad score: it means no assessment has been made yet." />
          </p>

          <NeedsWork controls={controls.controls} />

          {/* The catalogue is the reference behind the worklist above, not the
              thing you came for. Closed, with its size on the control, so the
              page ends on what needs doing. */}
          <details className="rt-more" style={{ marginTop: 20 }}>
            <summary>All {controls.controls.length} controls</summary>
            <div className="panel scroll-x">
              <table>
                <thead>
                  <tr>
                    <th>control</th>
                    <th>what it checks</th>
                    <th>
                      status
                      <InfoTip text="Effective (green): telemetry confirms it works. Degraded (amber): partially confirmed. Failing (red): telemetry contradicts it. Grey: not implemented, not applicable, or not computed yet, meaning catalogued but never assessed, which is different from failing." />
                    </th>
                    <th>evidence / rationale</th>
                  </tr>
                </thead>
                <tbody>
                  {controls.controls.map((c: any) => (
                    <tr key={c.key} id={c.key}>
                      <td className="small wrap" style={{ maxWidth: 240 }}>
                        <Link href={`/app/compliance/controls/${c.key}`}>{c.title}</Link>
                        <div className="mono small muted">{c.key}</div>
                      </td>
                      <td className="small wrap muted" style={{ maxWidth: 330 }}>{c.objective}</td>
                      <td><ControlStatus value={c.status} /></td>
                      <td className="small wrap muted" style={{ maxWidth: 380 }}>{c.rationale || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}

      {tab === "regulations" && <Regulations frameworks={frameworks.frameworks} />}

      {tab === "risk" && (
        <>
          <h2>Risk register</h2>
          <p className="small muted" style={{ marginTop: -6, marginBottom: 14 }}>
            An unassessed agent needs someone to record a class and a residual risk.
            Expand a row to do that.
          </p>
          <div className="panel scroll-x">
            <table>
              <thead>
                <tr><th>agent</th><th>risk tier</th><th>EU class</th><th>residual</th><th>assessor</th><th>next review</th><th></th></tr>
              </thead>
              <tbody>
                {register.register.map((r: any) => (
                  <tr key={r.agent}>
                    <td className="mono small"><Link href={`/app/agents/${r.agent}`}>{r.agent}</Link></td>
                    <td><span className={`tag ${r.risk_tier === "high" ? "bad" : ""}`}>{r.risk_tier}</span></td>
                    <td className="small">
                      {r.eu_ai_act_class || <span className="tag warn">not assessed</span>}
                    </td>
                    <td className="small muted">{r.residual_risk || "—"}</td>
                    <td className="small muted">{r.assessor || "—"}</td>
                    <td className="small muted">
                      {r.review_overdue ? (
                        <span className="tag bad">overdue</span>
                      ) : (r.next_review_at || "—").slice(0, 10)}
                    </td>
                    <td>
                      <details>
                        <summary className="small">{r.eu_ai_act_class ? "Reassess" : "Assess"}</summary>
                        <form
                          action={`/api/risk/assessments/${r.agent}`}
                          method="POST"
                          className="stack"
                          style={{ marginTop: 8, minWidth: 220 }}
                        >
                          <label className="small muted" style={{ display: "block" }}>
                            EU AI Act class
                            <select name="eu_ai_act_class" defaultValue="" style={inputStyle}>
                              <option value="">Let the platform propose one</option>
                              <option value="minimal">Minimal</option>
                              <option value="limited">Limited</option>
                              <option value="high">High</option>
                              <option value="prohibited">Prohibited</option>
                            </select>
                          </label>
                          <label className="small muted" style={{ display: "block" }}>
                            Residual risk
                            <select name="residual_risk" defaultValue="low" style={inputStyle}>
                              <option value="low">Low</option>
                              <option value="medium">Medium</option>
                              <option value="high">High</option>
                            </select>
                          </label>
                          <label className="small muted" style={{ display: "block" }}>
                            Signed off by
                            <input
                              type="email"
                              name="signed_off_by"
                              placeholder="you@yourcompany.com"
                              style={inputStyle}
                            />
                          </label>
                          <button type="submit" className="btn-primary" style={{ fontSize: 12 }}>
                            Record assessment
                          </button>
                        </form>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === "retention" && <Retention retention={retention} />}
    </>
  );
}

/**
 * Each framework that applies, as a row you can open: how many of its requirements
 * the controls cover, how those controls are doing, how many carry a current
 * attestation, and the next dated obligation. The framework page goes on down:
 * requirement, mapped controls, rules, runs and evidence.
 */
function Regulations({ frameworks }: { frameworks: any[] }) {
  return (
    <>
      <h2>Regulations</h2>
      <p className="sub">
        The frameworks you may be asked about. Open one for its requirements and the
        controls that answer each.
      </p>
      <Card flush>
        <table className="k-table">
          <thead>
            <tr>
              <th>Framework</th>
              <th className="tight num">Requirements</th>
              <th className="tight">Controls</th>
              <th className="tight">Attested</th>
              <th className="tight">Next deadline</th>
            </tr>
          </thead>
          <tbody>
            {frameworks.map((f) => {
              const s = f.status_counts || {};
              const a = f.attestations || {};
              const mapped = f.controls_mapped || 0;
              return (
                <tr key={f.framework}>
                  <td>
                    <Link className="k-name" href={`/app/compliance/frameworks/${f.framework}`}>
                      {f.title}
                    </Link>
                    <span className="sub">{f.description}</span>
                  </td>
                  <td className="tight num">{f.requirements}</td>
                  <td className="tight">
                    <span className="k-pills">
                      {!(s.effective || s.failing || s.degraded) && (
                        <Pill tone="outline">{s.not_computed ? "Not computed" : "None assessed"}</Pill>
                      )}
                      {s.effective > 0 && <Pill tone="ok">{s.effective} effective</Pill>}
                      {s.failing > 0 && <Pill tone="bad">{s.failing} failing</Pill>}
                      {s.degraded > 0 && <Pill tone="warn">{s.degraded} degraded</Pill>}
                    </span>
                  </td>
                  <td className="tight">
                    {a.current || 0} of {mapped}
                    {a.expired > 0 && (
                      <>
                        {" "}
                        <Pill tone="warn">{a.expired} expired</Pill>
                      </>
                    )}
                  </td>
                  <td className="tight muted">
                    {f.next_deadline ? (
                      <Link
                        href={`/app/compliance/frameworks/${f.framework}#obligation-${encodeURIComponent(f.next_deadline.reference)}`}
                        title={f.next_deadline.title}
                      >
                        {f.next_deadline.effective_date.slice(0, 10)}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </>
  );
}

const ACTION_LABEL: Record<string, string> = {
  delete: "Deleted",
  redact: "Content redacted",
  locked: "Never purged",
  unenforced: "Not enforced",
};

function purgeSummary(result: any): string {
  if (!result) return "—";
  if (result.skipped) {
    return result.skipped === "no policy" ? "Kept" : result.skipped === "legal hold" ? "Held" : "—";
  }
  let deleted = 0;
  let redacted = 0;
  for (const [k, v] of Object.entries(result)) {
    if (typeof v !== "number") continue;
    if (k.endsWith("_deleted")) deleted += v;
    if (k.endsWith("_redacted")) redacted += v;
  }
  if (!deleted && !redacted) return "Nothing due";
  return [deleted ? `${deleted} deleted` : "", redacted ? `${redacted} redacted` : ""].filter(Boolean).join(", ");
}

/**
 * How long each class of recorded data is kept, changed here and enforced by a
 * daily purge. The audit log is shown, locked: it is never purged.
 */
function Retention({ retention }: { retention: any }) {
  const last = retention.last_run;
  const activeHolds = retention.legal_holds.filter((h: any) => !h.released_at);
  return (
    <>
      <h2>Retention</h2>
      <p className="sub">
        How long each kind of data is kept. A daily purge deletes or redacts what is
        older. Active legal holds stop it.
      </p>

      <Card
        flush
        title="Data classes"
        action={
          <form action="/api/retention/purge" method="POST" className="row" style={{ gap: 10 }}>
            <span className="small muted">
              Last purge {last ? `${ago(last.started_at)} by ${last.requested_by || "schedule"}` : "never"}
              {" · "}
              Next {retention.next_run ? (retention.next_run === "due" ? "on the next cron run" : ts(retention.next_run)) : "not scheduled"}
            </span>
            <button type="submit" className="k-btn">Run purge now</button>
          </form>
        }
      >
        <table className="k-table">
          <thead>
            <tr>
              <th>Data</th>
              <th className="tight">Kept for</th>
              <th className="tight">After that</th>
              <th className="tight">Last purge</th>
              <th className="tight"></th>
            </tr>
          </thead>
          <tbody>
            {retention.classes.map((c: any) => (
              <tr key={c.data_class}>
                <td>
                  <span className="k-name">{c.label}</span>
                  <span className="sub">{c.covers}</span>
                </td>
                <td className="tight">
                  {c.action === "locked" ? "Life of the workspace" : days(c.retain_days)}
                </td>
                <td className="tight">
                  <Pill tone={c.action === "locked" ? "ok" : c.retain_days ? "info" : "outline"}>
                    {c.action === "locked" || c.retain_days ? ACTION_LABEL[c.action] : "Nothing"}
                  </Pill>
                </td>
                <td className="tight muted">{purgeSummary(c.last_result)}</td>
                <td className="tight">
                  {c.action === "delete" || c.action === "redact" ? (
                    <details>
                      <summary className="small">Change</summary>
                      <form
                        action={`/api/retention/${encodeURIComponent(c.data_class)}`}
                        method="POST"
                        className="k-limits-form"
                        style={{ marginTop: 8 }}
                      >
                        <div className="k-limits-row">
                          <input
                            className="k-input"
                            type="number"
                            name="retain_days"
                            min={1}
                            max={3650}
                            required
                            defaultValue={c.retain_days ?? c.default_days ?? 365}
                            aria-label="Days to keep"
                          />
                          <span className="small muted">days</span>
                        </div>
                        <input
                          className="k-input"
                          name="reason"
                          required
                          placeholder="Reason, kept on the audit log"
                          aria-label="Reason"
                        />
                        <button type="submit" className="k-btn-primary">Save</button>
                      </form>
                    </details>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <h2>Legal holds</h2>
      <p className="sub">
        A hold preserves data the purge would otherwise remove. A hold with no agents
        stops the purge entirely.
      </p>

      <Card title="Place a hold">
        <form action="/api/legal-holds" method="POST" className="k-form">
          <div className="k-field">
            <label htmlFor="lh-agents">Agents</label>
            <input id="lh-agents" className="k-input" type="text" name="agents" placeholder="All agents, or: support-triage, refund-bot" />
          </div>
          <div className="k-field">
            <label htmlFor="lh-reason">Reason</label>
            <input id="lh-reason" className="k-input" type="text" name="reason" required placeholder="Litigation hold, case 4471" />
          </div>
          <div className="k-field">
            <span />
            <div><button type="submit" className="k-btn-primary">Place hold</button></div>
          </div>
        </form>
      </Card>

      <Card flush title={`Holds${activeHolds.length ? ` (${activeHolds.length} active)` : ""}`}>
        {retention.legal_holds.length === 0 ? (
          <Empty>No legal holds placed.</Empty>
        ) : (
          <table className="k-table">
            <thead>
              <tr><th className="tight">Placed</th><th>By</th><th>Agents</th><th>Reason</th><th className="tight">Status</th></tr>
            </thead>
            <tbody>
              {retention.legal_holds.map((h: any) => (
                <tr key={h.id}>
                  <td className="tight muted">{ts(h.placed_at)}</td>
                  <td className="muted">{h.placed_by}</td>
                  <td className="muted">{(h.scope?.agents || ["All"]).join(", ")}</td>
                  <td>{h.reason}</td>
                  <td className="tight">
                    <Pill tone={h.released_at ? "outline" : "warn"}>
                      {h.released_at ? `Released ${ts(h.released_at)}` : "Active"}
                    </Pill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}

/**
 * The controls whose telemetry says something is wrong, lifted out of the
 * catalogue and put where the instruction to work them is.
 *
 * Failing before degraded, and within each, catalogue order — a stable sort, so
 * a row does not move between refreshes for any reason except its own status
 * changing. Each row opens the control.
 *
 * Renders nothing when everything holds.
 */
function NeedsWork({ controls }: { controls: any[] }) {
  const rank: Record<string, number> = { failing: 0, degraded: 1 };
  const rows = controls
    .map((c, i) => ({ c, i }))
    .filter(({ c }) => c.status in rank)
    .sort((a, b) => rank[a.c.status] - rank[b.c.status] || a.i - b.i)
    .map(({ c }) => c);

  if (rows.length === 0) return null;

  const failing = rows.filter((c) => c.status === "failing").length;

  return (
    <section className="needs-work">
      <h3>
        <span className="nw-n">{rows.length}</span>
        control{rows.length === 1 ? "" : "s"} your telemetry contradicts
        <span className="nw-split">
          {failing > 0 && `${failing} failing`}
          {failing > 0 && rows.length - failing > 0 && " · "}
          {rows.length - failing > 0 && `${rows.length - failing} degraded`}
        </span>
      </h3>
      <ol className="nw-list">
        {rows.map((c) => (
          <li key={c.key} className={`nw-row nw-${c.status}`}>
            <div className="nw-head">
              <ControlStatus value={c.status} />
              <Link href={`/app/compliance/controls/${c.key}`} className="nw-title">
                {c.title}
              </Link>
              <span className="mono nw-key">{c.key}</span>
            </div>
            <p className="nw-why">{c.rationale || "No rationale recorded."}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
