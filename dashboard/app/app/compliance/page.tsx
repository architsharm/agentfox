import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { api, apiErrorProps } from "@/lib/api";
import { ApiDown, ControlStatus, DraftCaveat, Gaps, InfoTip, InventoryStrip, Panel, Stat, StatLink, StatusBar, pct, ts } from "@/components/ui";
import { PageHeader } from "@/components/PageHeader";
import { PrintButton } from "@/components/PrintButton";

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
  { key: "frameworks", label: "Frameworks" },
  { key: "obligations", label: "Obligations" },
  { key: "risk", label: "Risk register" },
  { key: "evidence", label: "Evidence & reports" },
  { key: "retention", label: "Retention & legal hold" },
  { key: "board", label: "Board snapshot" },
];

export default async function Compliance({
  searchParams,
}: {
  searchParams: Promise<{ review_error?: string; review_notice?: string; tab?: string }>;
}) {
  const { review_error, review_notice, tab: rawTab } = await searchParams;
  // Controls is the default because /findings and /policies deep-link to
  // /compliance#<control-key> — a control anchor that lands on the wrong tab
  // never scrolls into view, so the tab that owns those anchors has to be first.
  const tab = TABS.some((t) => t.key === rawTab) ? rawTab! : "controls";

  let controls: any, frameworks: any, obligations: any, register: any, evidencePackages: any, retention: any;
  try {
    [controls, frameworks, obligations, register, evidencePackages, retention] = await Promise.all([
      api("/api/controls"),
      api("/api/frameworks"),
      api("/api/obligations"),
      api("/api/risk/register"),
      api("/api/evidence"),
      api("/api/retention"),
    ]);
  } catch (e: any) {
    return (
      <>
        <h1>Compliance</h1>
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }

  const counts = controls.posture.counts || {};
  const catalogLoaded = controls.controls.length > 0;
  const assessed = (counts.effective || 0) + (counts.degraded || 0) + (counts.failing || 0);

  return (
    <>
      <PageHeader
        title="Compliance"
        sub={
          <>
            One control set, seven frameworks. Status is{" "}
            <strong>computed from telemetry</strong>, not attested on a form.
          </>
        }
      />

      {review_error && <div className="error">{review_error}</div>}
      {review_notice && <div className="note-panel">{review_notice}</div>}

      {!catalogLoaded && (
        <div className="hero empty" style={{ marginBottom: 20 }}>
          <div className="hero-title">Control catalog not loaded</div>
          <p>
            This deployment has never loaded the reference control catalog, so every
            count below reads zero.
            <InfoTip text="The catalog is the fixed set of ~40 controls and their mappings to EU AI Act, NIST AI RMF, ISO/IEC 42001 and the rest. Loading it is idempotent, so it is safe to run again later when the catalog version changes." />
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
          unit={`effective of the ${assessed} control(s) with telemetry to assess — the ${counts.not_implemented || 0} not-yet-implemented are excluded from the ratio, not counted as failing`}
        />

      <div className="tabbar">
        {TABS.map((t) => (
          <Link
            key={t.key}
            href={t.key === "controls" ? "/app/compliance" : `/app/compliance?tab=${t.key}`}
            className={tab === t.key ? "active" : ""}
          >
            {t.label}
            <span className="tab-count">
              {t.key === "controls" && controls.controls.length}
              {t.key === "frameworks" && frameworks.frameworks.length}
              {t.key === "obligations" && obligations.obligations.length}
              {t.key === "risk" && register.register.length}
              {t.key === "evidence" && evidencePackages.packages.length}
              {t.key === "retention" && retention.legal_holds.length}
            </span>
          </Link>
        ))}
      </div>

      {tab === "controls" && (
        <>
          <h2 style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span>Controls</span>
            {catalogLoaded && (
              <div className="row" style={{ gap: 10 }}>
                {counts.not_computed > 0 && (
                  <span className="small muted">
                    {counts.not_computed} never computed — needs real traffic, not a click.{" "}
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
            is holding.
            <InfoTip text="The rationale column says what the telemetry actually found, which is usually enough to tell whether the fix is a configuration change or more traffic. Grey is not a bad score, it means no assessment has been made yet." />
          </p>

          {/* The instruction here used to be "Work the red and amber rows", above a
              43-row catalogue sorted by control id, with the five rows in question
              scattered through it at positions 8, 16, 24, 31 and 38. Telling someone
              to work a subset and then making them find it is not a flow.

              So the subset is the block, and the catalogue underneath is what it has
              always been: the reference. Each row links to its own anchor in that
              table, which already carried `id={c.key}`. The objective column is
              dropped here on purpose — deciding what to do about a control that is
              failing needs what the telemetry FOUND, not a restatement of what the
              control is for. */}
          <NeedsWork controls={controls.controls} />

          {/* The catalogue is 43 rows of three prose columns — the reference
              behind the worklist above, not the thing you came for. Closed, with
              its size on the control, so the page ends on what needs doing. */}
          <details className="rt-more" style={{ marginTop: 20 }}>
          <summary>
            The full control catalogue ({controls.controls.length}) — everything this
            product can check
          </summary>
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
                      {c.title}
                      <div className="mono small muted" title="Internal code, cross-referenced on the Glossary page">
                        {c.key}
                      </div>
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

      {tab === "frameworks" && (
        <>
          <h2>Frameworks</h2>
          <p className="small muted" style={{ marginTop: -6, marginBottom: 14, maxWidth: "var(--measure)" }}>
            The same control set through each framework you may be asked about, and how
            much of it each covers. Open one to review its mappings.
            <InfoTip text="A mapping is a claim that a control satisfies a particular clause, and it stays marked draft until a named person confirms it. Reviewing them here is what turns a computed guess into something an auditor can use." />
          </p>
          <div className="panel scroll-x">
            <table>
              <thead>
                <tr>
                  <th>framework</th><th className="num">controls mapped</th>
                  <th className="num">mappings</th><th className="num">reviewed</th><th>status</th><th></th>
                </tr>
              </thead>
              <tbody>
                {frameworks.frameworks.map((f: any) => (
                  <tr key={f.framework}>
                    <td>
                      <div>{f.title}</div>
                      <div className="small muted wrap" style={{ maxWidth: 460 }}>{f.description}</div>
                    </td>
                    <td className="num">{f.controls_mapped}/{f.controls_total}</td>
                    <td className="num">{f.mappings_total}</td>
                    <td className="num">{f.mappings_reviewed}</td>
                    <td>
                      <span className={`tag ${f.review_status === "reviewed" ? "ok" : "warn"}`}>
                        {f.review_status}
                      </span>
                    </td>
                    <td>
                      <Link href={`/app/compliance/frameworks/${f.framework}`} className="small">
                        Review mappings →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Was a run of bare <h3>s and bullet lists stacked under the table,
              which a reader had to scroll through to get past. One control per
              framework instead — still one click from the coverage it qualifies. */}
          {frameworks.frameworks.map((f: any) => (
            <Gaps key={f.framework} gaps={f.declared_gaps} title={f.title} />
          ))}
        </>
      )}

      {tab === "obligations" && (
        <>
          <h2>Regulatory obligations</h2>
          <p className="small muted" style={{ marginTop: -6, marginBottom: 14, maxWidth: "var(--measure)" }}>
            Dated duties that regulations put on you, each matched against the agents it
            would apply to.
            <InfoTip text="So a date arriving is not the first you hear of it, and you can see how much of your inventory it touches. A row is a calendar entry, not a record that the duty was met, and none of it is legal advice." />
          </p>
          <div className="panel scroll-x">
            <table>
              <thead>
                <tr>
                  <th>date</th><th>framework</th><th>obligation</th><th>status</th>
                  <th className="num">agents in scope</th><th>build by</th>
                </tr>
              </thead>
              <tbody>
                {obligations.obligations.map((o: any, i: number) => (
                  <tr key={i} id={o.reference ? `obligation-${encodeURIComponent(o.reference)}` : undefined}>
                    <td className="small mono">{(o.effective_date || "").slice(0, 10)}</td>
                    <td className="small muted">{o.framework}</td>
                    <td>
                      <div className="small">{o.title}</div>
                      <div className="small muted wrap" style={{ maxWidth: 400 }}>{o.description}</div>
                    </td>
                    <td>
                      <span className={`tag ${o.status === "live" ? "ok" : "warn"}`}>{o.status}</span>
                    </td>
                    <td className="num">{o.agents_in_scope_count}</td>
                    <td className="small muted">{(o.target_readiness || "—").slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

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

      {tab === "evidence" && (
        <>
          <h2>Evidence & reports</h2>
          <p className="small muted" style={{ marginTop: -6, marginBottom: 14 }}>
            An auditor-ready zip: what was in scope, what the agent did, which policy
            version was in force, and a standalone script that re-derives the
            audit-chain hash. Draft
            (unreviewed) framework mappings are included too, each tagged{" "}
            <strong>DRAFT — UNVERIFIED / NOT LEGAL ADVICE</strong>, and reviewed on the{" "}
            <a href="/app/compliance?tab=frameworks">Frameworks tab</a>.
            <InfoTip text="Building a package is logged to the audit chain after its contents are computed, so a package never includes a record of its own creation and its audit-entry count is always one behind an integrity check run right after. That is expected, not a discrepancy." />
          </p>

          <form action="/api/audit/verify" method="POST" style={{ marginBottom: 20 }}>
            <button type="submit" className="btn-scan">Verify audit chain integrity now</button>{" "}
            <span className="small muted">
              Independently re-derives the hash chain over every audit entry, without
              building a package first.
              <InfoTip text="It is the same check a package runs at build time." />
            </span>
          </form>

          <div className="panel" style={{ marginBottom: 20 }}>
            <div className="head"><span>Build a package</span></div>
            <form action="/api/evidence" method="POST" className="body stack">
              <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 200 }}>
                  <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
                    Agents (comma-separated slugs, blank = all)
                  </label>
                  <input type="text" name="agents" placeholder="support-triage, refund-bot" style={inputStyle} />
                </div>
                <div style={{ flex: 1, minWidth: 200 }}>
                  <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
                    Controls (comma-separated keys, blank = all)
                  </label>
                  <input type="text" name="controls" placeholder="NOM-RTG-01" style={inputStyle} />
                </div>
              </div>
              <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 160 }}>
                  <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
                    Period from (blank = unbounded)
                  </label>
                  <input type="date" name="period_from" style={inputStyle} />
                </div>
                <div style={{ flex: 1, minWidth: 160 }}>
                  <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
                    Period to (blank = now)
                  </label>
                  <input type="date" name="period_to" style={inputStyle} />
                </div>
              </div>
              <button type="submit" className="btn-primary">Build evidence package</button>
            </form>
          </div>

          <p className="small muted" style={{ maxWidth: "var(--measure)", marginTop: -8, marginBottom: 20 }}>
            <strong>What a package does and does not settle.</strong> It shows what this
            deployment recorded over the period you chose; the bundled script lets the
            recipient confirm nothing has been altered since.
            <InfoTip text="The script does not trust this platform or call its API, so the recipient does not have to take this product's word for it. A package does not show anything that was never recorded, it does not establish that the controls in scope were the right controls, and a draft framework mapping inside it is a starting point for a reviewer, not a legal conclusion." />{" "}
            The same package can be built without the dashboard:{" "}
            <code className="mono">agentfox evidence export --since-days 30</code>, or{" "}
            <span className="mono">POST /api/evidence</span>.
          </p>

          {evidencePackages.packages.length === 0 ? (
            <div className="hero empty">
              <div className="hero-title">No evidence packages built yet</div>
              <p>
                Build one above. It gathers what this deployment already recorded for
                the period you pick.
                <InfoTip text="On a fresh instance with no traffic yet the package comes out empty and is labelled as such. Nothing is deleted by building another." />
              </p>
            </div>
          ) : (
            <div className="panel scroll-x">
              <table>
                <thead>
                  <tr>
                    <th>built</th><th>requested by</th><th>scope</th>
                    <th>chain</th><th>counts</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {evidencePackages.packages.map((p: any) => {
                    const counts = p.counts || {};
                    const substantive = ["traces", "decisions", "control_statuses", "eval_runs", "findings"];
                    const isEmpty = substantive.every((k) => !counts[k]);
                    return (
                      <tr key={p.id}>
                        <td className="small muted">{ts(p.built_at)}</td>
                        <td className="small muted">{p.requested_by}</td>
                        <td className="small muted">
                          {(p.scope?.agents || ["*"]).join(", ")} / {(p.scope?.controls || ["*"]).join(", ")}
                        </td>
                        <td>
                          <span className={`tag ${p.chain_valid ? "ok" : "bad"}`}>
                            {p.chain_valid ? "verified" : "broken"}
                          </span>
                        </td>
                        <td className="small muted">
                          {isEmpty && (
                            <div className="tag warn" style={{ marginBottom: 4 }}>
                              empty — nothing to show an auditor yet
                            </div>
                          )}
                          {Object.entries(counts).map(([k, v]) => `${k}: ${v}`).join(", ") || "—"}
                        </td>
                        <td>
                          <a href={`/api/evidence/${p.id}/download`} className="small">Download →</a>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {tab === "retention" && (
        <>
          <h2>Retention & legal hold</h2>
          <p className="small muted" style={{ marginTop: -6, marginBottom: 14 }}>
            How long each data class is kept before it's purged or redacted, and any
            active legal hold overriding that schedule.
            <InfoTip text="Placing a hold is a record that the data it covers must be preserved regardless of its normal retention policy, for example for litigation or a regulatory inquiry." />
          </p>

          <div className="panel" style={{ marginBottom: 20 }}>
            <div className="head"><span>Retention policies</span></div>
            {retention.policies.length === 0 ? (
              <div className="body small muted">
                No retention policies configured, so nothing is being purged or redacted
                on a schedule. There is no way to add one from the dashboard; ask
                whoever operates it to put a schedule in place.
                <InfoTip text="This table is read-only. A legal hold, below, works regardless of whether a schedule exists." />
              </div>
            ) : (
              <table>
                <thead>
                  <tr><th>data class</th><th>retain for</th><th>redacted fields</th></tr>
                </thead>
                <tbody>
                  {retention.policies.map((p: any) => (
                    <tr key={p.data_class}>
                      <td className="mono small">{p.data_class}</td>
                      <td className="small">{p.retain_days} days</td>
                      <td className="small muted">{(p.redact_fields || []).join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="panel" style={{ marginBottom: 20 }}>
            <div className="head"><span>Place a legal hold</span></div>
            <form action="/api/legal-holds" method="POST" className="body stack">
              <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 200 }}>
                  <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
                    Agents (comma-separated slugs, blank = all)
                  </label>
                  <input type="text" name="agents" placeholder="support-triage, refund-bot" style={inputStyle} />
                </div>
                <div style={{ flex: 2, minWidth: 240 }}>
                  <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
                    Reason
                  </label>
                  <input type="text" name="reason" required placeholder="Litigation hold — case #4471" style={inputStyle} />
                </div>
              </div>
              <button type="submit" className="btn-primary">Place hold</button>
            </form>
          </div>

          {retention.legal_holds.length === 0 ? (
            <div className="hero empty">
              <div className="hero-title">No legal holds placed</div>
              <p>Place one above to preserve data that would otherwise be purged on schedule.</p>
            </div>
          ) : (
            <div className="panel scroll-x">
              <table>
                <thead>
                  <tr><th>placed</th><th>placed by</th><th>scope</th><th>reason</th><th>status</th></tr>
                </thead>
                <tbody>
                  {retention.legal_holds.map((h: any) => (
                    <tr key={h.id}>
                      <td className="small muted">{ts(h.placed_at)}</td>
                      <td className="small muted">{h.placed_by}</td>
                      <td className="small muted">{(h.scope?.agents || ["*"]).join(", ")}</td>
                      <td className="small">{h.reason}</td>
                      <td>
                        <span className={`tag ${h.released_at ? "" : "warn"}`}>
                          {h.released_at ? `released ${ts(h.released_at)}` : "active"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {tab === "board" && <BoardTab />}
    </>
  );
}

/**
 * The printable snapshot — one page for someone outside the team: agent
 * population by risk class, control effectiveness, open findings, and the
 * regulatory calendar, frozen at the moment it's generated. Used to live at
 * its own /board URL; now a tab here since it's the same data this page
 * already computes, just summarized for print instead of browsed by table.
 */
async function BoardTab() {
  let v: any;
  try {
    v = await api("/api/board");
  } catch (e: any) {
    return <ApiDown {...apiErrorProps(e)} />;
  }

  const inv = v.inventory;
  const f = v.open_findings;

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", marginTop: 16 }}>
        <p className="small muted" style={{ maxWidth: "var(--measure)" }}>
          For day-to-day monitoring use <Link href="/app">Overview</Link>: this snapshot
          does not update itself. Generated {v.generated_at?.slice(0, 19)}.
          {v.seed_agents > 0 && (
            <>
              {" "}<span className="tag" style={{ marginLeft: 4 }}>
                {v.seed_agents} of {inv.agents} agent(s) below {v.seed_agents === 1 ? "is" : "are"} sample data from `agentfox seed`
              </span>
            </>
          )}
        </p>
        <PrintButton />
      </div>

      {/* Was six tiles here on top of the six above the tab bar — twelve on one
          screen, with 88% control effectiveness appearing in both rows. A board
          snapshot is read by someone who wants the shape of the estate in ten
          seconds, so: the things that want attention as tiles, the rest as a
          strip, and the effectiveness figure stated once. */}
      {(v.high_risk_agents.length > 0 || inv.shadow > 0 || v.unassessed_agents.length > 0 || f.total > 0) && (
        <div className="cards">
          {v.high_risk_agents.length > 0 && (
            <StatLink
              n={v.high_risk_agents.length}
              label="high-risk agents"
              tone="warn"
              href="/app/agents"
            />
          )}
          {inv.shadow > 0 && (
            <StatLink
              n={inv.shadow}
              label="unregistered"
              tone="bad"
              href="/app/agents"
              hint="Traffic observed from an agent that was never registered."
            />
          )}
          {v.unassessed_agents.length > 0 && (
            <StatLink
              n={v.unassessed_agents.length}
              label="unassessed"
              tone="warn"
              href="/app/compliance?tab=risk"
              hint="Agents with no EU AI Act risk classification on file."
            />
          )}
          {f.total > 0 && (
            <StatLink
              n={f.total}
              label="open findings"
              tone={f.by_severity?.critical ? "bad" : "warn"}
              href="/app/findings"
            />
          )}
        </div>
      )}

      <InventoryStrip
        items={[
          { n: inv.agents, label: "agents under management", href: "/app/agents" },
          { n: pct(v.overall_posture.effectiveness), label: "control effectiveness", href: "/app/compliance" },
        ]}
      />

      <div className="grid2" style={{ marginTop: 22 }}>
        <Panel title="Agents by risk class">
          <table>
            <tbody>
              {Object.entries(v.agents_by_risk_class).map(([k, n]: any) => (
                <tr key={k}>
                  <td>
                    <span className={`tag ${k === "high" || k === "prohibited" ? "bad" : ""}`}>{k}</span>
                  </td>
                  <td className="num">{n}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {v.high_risk_agents.length > 0 && (
            <div className="body small muted">
              high-risk:{" "}
              {v.high_risk_agents.map((slug: string, i: number) => (
                <span key={slug} className="mono">
                  {i > 0 && ", "}
                  <Link href={`/app/agents/${slug}`}>{slug}</Link>
                </span>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Open findings by severity">
          <table>
            <tbody>
              {Object.entries(f.by_severity || {}).map(([k, n]: any) => (
                <tr key={k}>
                  <td>
                    <Link href={`/app/findings?severity=${k}`}>
                      <span className={`tag ${k === "critical" || k === "high" ? "bad" : k === "medium" ? "warn" : ""}`}>{k}</span>
                    </Link>
                  </td>
                  <td className="num">{n}</td>
                </tr>
              ))}
              {Object.keys(f.by_severity || {}).length === 0 && (
                <tr><td className="muted small">none open</td></tr>
              )}
            </tbody>
          </table>
        </Panel>
      </div>

      <h2>Control effectiveness by framework</h2>
      <div className="panel scroll-x">
        <table>
          <thead>
            <tr>
              <th>framework</th><th className="num">controls</th><th className="num">effective</th>
              <th className="num">degraded</th><th className="num">failing</th>
              <th className="num">not implemented</th><th className="num">not computed</th>
              <th className="num">effectiveness</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(v.control_posture).map(([fw, p]: any) => (
              <tr key={fw}>
                <td className="mono small">
                  <Link href={`/app/compliance/frameworks/${fw}`}>{fw}</Link>
                </td>
                <td className="num">{p.controls}</td>
                <td className="num"><span className="tag ok">{p.counts.effective}</span></td>
                <td className="num"><span className="tag warn">{p.counts.degraded}</span></td>
                <td className="num">
                  {p.counts.failing ? <span className="tag bad">{p.counts.failing}</span> : "0"}
                </td>
                <td className="num muted">{p.counts.not_implemented}</td>
                <td className="num muted">{p.counts.not_computed}</td>
                <td className="num">{pct(p.effectiveness)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Regulatory clock</h2>
      <div className="panel scroll-x">
        <table>
          <thead>
            <tr><th>date</th><th>obligation</th><th>status</th><th className="num">days</th><th className="num">agents in scope</th></tr>
          </thead>
          <tbody>
            {[...v.live_obligations, ...v.upcoming_obligations].map((o: any, i: number) => (
              <tr key={i}>
                <td className="small mono">{(o.effective_date || "").slice(0, 10)}</td>
                <td className="small">
                  <Link href={`/app/compliance?tab=obligations#obligation-${encodeURIComponent(o.reference || "")}`}>
                    {o.title}
                  </Link>{" "}
                  <span className="muted mono">{o.reference}</span>
                </td>
                <td><span className={`tag ${o.status === "live" ? "ok" : "warn"}`}>{o.status}</span></td>
                <td className="num small muted">{o.days_until > 0 ? o.days_until : "—"}</td>
                <td className="num">{o.agents_in_scope_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <DraftCaveat text={v.caveat} />
    </>
  );
}

/**
 * The controls whose telemetry says something is wrong, lifted out of the
 * catalogue and put where the instruction to work them is.
 *
 * Failing before degraded, and within each, catalogue order — a stable sort, so
 * a row does not move between refreshes for any reason except its own status
 * changing. Nothing here is new data: every row is in the table below, and this
 * block links to it rather than restating it.
 *
 * Renders nothing when everything holds. An empty "Needs work" panel saying
 * "nothing needs work" is a panel earning its border by being congratulated —
 * the status bar above already says 88% and the catalogue is right there.
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
              <a href={`#${c.key}`} className="nw-title">
                {c.title}
              </a>
              <span className="mono nw-key">{c.key}</span>
            </div>
            <p className="nw-why">{c.rationale || "No rationale recorded."}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
