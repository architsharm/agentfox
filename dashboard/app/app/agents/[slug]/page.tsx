import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { api, safeApi, apiErrorProps } from "@/lib/api";
import { ApiDown, InfoTip, InventoryStrip, Panel, Severity, ts } from "@/components/ui";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { AgentMap } from "@/components/AgentMap";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata("Agent");

export const dynamic = "force-dynamic";

/** Split by the question being asked, not by where the data comes from. */
const TABS: { key: string; label: string }[] = [
  { key: "activity", label: "Activity" },
  { key: "permissions", label: "What it may do" },
  { key: "registration", label: "Registration" },
];

/**
 * The four tiers a tool can be declared at (`agentfox tools declare --impact`).
 * high_impact was missing here, so a tool at that tier rendered as an untoned
 * tag — visually identical to a read-only one, which is the opposite of what it
 * means. Every containment rule reasons over this axis, so it has to be complete.
 */
const IMPACT_TONE: Record<string, string> = {
  read: "",
  write: "warn",
  high_impact: "warn",
  irreversible: "bad",
};

const IMPACT_MEANS: Record<string, string> = {
  read: "Returns information and changes nothing.",
  write: "Changes something, and the change can be undone.",
  high_impact: "Significant effect, but still reversible — untrusted arguments send it for approval.",
  irreversible: "Cannot be undone. Untrusted arguments always require a human.",
};

export default async function AgentDetail({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ tab?: string; review_error?: string; review_notice?: string }>;
}) {
  const { slug } = await params;
  const { tab: rawTab, review_error, review_notice } = await searchParams;
  const tab = TABS.some((t) => t.key === rawTab) ? rawTab! : "activity";
  let posture: any, lineage: any, traces: any, classification: any, boundaries: any, controls: any, effective: any, tools: any, mcpServers: any;
  try {
    [posture, lineage, traces, classification, boundaries, controls, effective, tools, mcpServers] = await Promise.all([
      api(`/api/agents/${slug}/posture`),
      safeApi(`/api/agents/${slug}/lineage?depth=2`, { nodes: [], links: [], blast_radius: 0 }),
      safeApi(`/api/traces?agent=${slug}&limit=15`, { traces: [] }),
      safeApi(`/api/risk/classify/${slug}`, null),
      safeApi(`/api/answerability/boundaries`, { boundaries: [], question_types: [] }),
      safeApi(`/api/agent-controls`, { controls: [] }),
      safeApi(`/api/policies/effective?agent=${slug}`, null),
      safeApi(`/api/tools`, { tools: [] }),
      safeApi(`/api/mcp-servers`, { servers: [] }),
    ]);
  } catch (e: any) {
    return (
      <>
        <h1>{slug}</h1>
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }

  const a = posture.agent;
  const lineageNodeType: Record<string, string> = {};
  for (const n of lineage.nodes || []) lineageNodeType[n.id] = n.type;
  const boundary = boundaries.boundaries.find((b: any) => b.agent === a.slug) || null;
  const control = (controls.controls || []).find((c: any) => c.agent === a.slug) || null;
  const state = control?.state || "active";
  const toolByKey: Record<string, any> = {};
  for (const t of tools.tools || []) toolByKey[t.key] = t;
  const mcpById: Record<string, any> = {};
  for (const s of mcpServers.servers || []) mcpById[s.id] = s;
  const questionTypes: string[] = boundaries.question_types?.length
    ? boundaries.question_types
    : ["fact", "aggregate", "prediction", "opinion", "procedure"];

  return (
    <>
      <Breadcrumbs crumbs={[{ label: "Agents", href: "/app/agents" }]} />
      <h1>
        {a.name || a.slug}
        {a.is_seed && (
          <span
            className="tag"
            style={{ marginLeft: 10, verticalAlign: "middle" }}
            title="Created by `agentfox seed` for demo purposes — not a real registration."
          >
            sample data
          </span>
        )}
      </h1>
      {a.name && <p className="mono small muted" style={{ marginTop: -8 }}>{a.slug}</p>}

      <p className="sub">
        What this agent is, what it has actually been doing, and what it is allowed
        to do. Come here to decide whether it is safe to leave running as it is.
      </p>

      {review_error && <div className="error">{review_error}</div>}
      {review_notice && <div className="note-panel">{review_notice}</div>}

      {state !== "active" && (
        <div className="note-panel" style={{ borderLeftColor: "var(--bad)" }}>
          <strong>This agent is {state}</strong>
          {control?.reason && <> — {control.reason}</>}
          {control?.actor && <span className="small muted"> ({control.actor}, {ts(control.changed_at)})</span>}
          . Every governed call is currently refused until it's resumed.
        </div>
      )}


      {/* Six tiles, and on a quiet agent all six read 0 — three of them wearing a
          green border to celebrate it. Same rule as everywhere else in here: a
          number takes colour only when it is a problem, and a row of counts is a
          strip, not six cards. */}
      <InventoryStrip
        items={[
          { n: posture.traces, label: "traces", href: `/app/traces?agent=${a.slug}` },
          { n: posture.decisions, label: "decisions", href: `/app/traces?agent=${a.slug}` },
          {
            n: posture.blocked,
            label: "blocked",
            href: `/app/traces?agent=${a.slug}&verdict=block`,
            ...(posture.blocked ? { tone: "bad" as const } : {}),
          },
          {
            n: posture.escalated,
            label: "escalated",
            href: `/app/traces?agent=${a.slug}&verdict=escalate`,
            ...(posture.escalated ? { tone: "warn" as const } : {}),
          },
          {
            n: posture.handoffs,
            label: "hand-offs",
            href: `/app/approvals?tab=escalation&agent=${a.slug}`,
            ...(posture.handoffs ? { tone: "warn" as const } : {}),
          },
          { n: lineage.blast_radius, label: "blast radius", href: `/app/agents/${a.slug}?tab=registration` },
        ]}
      />

      {/* Ten sections in one scroll — 1,072 words over 5,173px — is a page you
          navigate by scrollbar. Three tabs, split by the question being asked:
          what has it been doing, what is it allowed to do, and what is it
          declared as. The summary and the state banner stay above them, because
          "this agent is quarantined" must not be one tab-click away. */}
      <div className="tabbar">
        {TABS.map((t) => (
          <Link
            key={t.key}
            href={t.key === "activity" ? `/app/agents/${a.slug}` : `/app/agents/${a.slug}?tab=${t.key}`}
            className={tab === t.key ? "active" : ""}
          >
            {t.label}
          </Link>
        ))}
      </div>

      {tab === "activity" && (
        <>
        {posture.open_findings?.length > 0 && (
          <>
            <h2>Open findings</h2>
            <div className="panel">
              <table>
                <thead><tr><th>severity</th><th>type</th><th>finding</th></tr></thead>
                <tbody>
                  {posture.open_findings.map((f: any) => (
                    <tr key={f.id}>
                      <td><Severity value={f.severity} /></td>
                      <td className="mono small">{f.type}</td>
                      <td className="small wrap">
                        <Link href={`/app/findings/${f.id}`}>{f.title}</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}


        <h2>Recent traces</h2>
        <div className="panel">
          {traces.traces.length === 0 ? (
            <div className="body muted small">
              No traces recorded yet.
              {posture.handoffs > 0 && (
                <>
                  {" "}This agent does have {posture.handoffs} hand-off{posture.handoffs === 1 ? "" : "s"} on
                  record — hand-offs are logged independently of traced calls, see{" "}
                  <Link href={`/app/approvals?tab=escalation&agent=${a.slug}`}>Escalation</Link>.
                </>
              )}
            </div>
          ) : (
            <table>
              <thead><tr><th>trace</th><th>verdict</th><th>model</th><th>intent</th><th>when</th></tr></thead>
              <tbody>
                {traces.traces.map((t: any) => (
                  <tr key={t.id}>
                    <td><Link href={`/app/traces/${t.id}`} className="mono small">{t.id}</Link></td>
                    <td><span className={`tag ${t.verdict === "block" ? "bad" : t.verdict === "allow" ? "ok" : "warn"}`}>{t.verdict}</span></td>
                    <td className="small muted">{t.model || "—"}</td>
                    <td className="small wrap muted" style={{ maxWidth: 280 }}>{t.intent || "—"}</td>
                    <td className="small muted">{ts(t.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {posture.slos?.length > 0 && (
          <>
            <h2>Reliability objectives</h2>
            <div className="panel">
              <table>
                <thead>
                  <tr><th>scorer</th><th>objective</th><th className="num">target</th><th className="num">attainment</th><th className="num">error budget</th><th>status</th></tr>
                </thead>
                <tbody>
                  {posture.slos.map((s: any) => (
                    <tr key={s.slo_id}>
                      <td className="mono small">{s.scorer}</td>
                      <td className="small wrap" style={{ maxWidth: 260 }}>{s.objective || "—"}</td>
                      <td className="num small">{s.target ?? "—"}</td>
                      <td className="num small">{s.attainment ?? "—"}</td>
                      <td className="num small">{s.error_budget_remaining ?? "—"}</td>
                      <td><span className={`tag ${s.status === "healthy" ? "ok" : s.status === "burned" ? "bad" : ""}`}>{s.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        </>
      )}

      {tab === "permissions" && (
        <>
        {effective && (
          <>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
              <h2 style={{ marginBottom: 0 }}>
                Effective policy
                {effective.rules?.some((r: any) => r.source && !r.source.startsWith("org:")) && (
                  <span className="tag warn" title="At least one rule below comes from a team/agent/user-level policy, not the org default.">
                    customized
                  </span>
                )}
                <InfoTip text="What actually applies to this agent right now, composed from every level that reaches it (org, team, agent) — with per-rule provenance so 'why did this block?' has a real answer. A rule from a narrower level can loosen or override a broader one; 'loosened' flags exactly that." />
              </h2>
              <Link
                href={`/app/policies/${a.slug}-overrides?level=agent&scope_id=${encodeURIComponent(a.slug)}&name=${encodeURIComponent(`${a.name || a.slug} overrides`)}`}
                className="btn-scan"
              >
                + Customize for this agent
              </Link>
            </div>
            <div className="panel">
              <div className="body small muted">
                mode <span className="tag">{effective.mode}</span> · default effect{" "}
                <span className="tag">{effective.default_effect}</span> · layers:{" "}
                {effective.layers?.length ? effective.layers.join(", ") : "none apply"}
              </div>
              {effective.rules?.length > 0 && (
                <table>
                  <thead>
                    <tr><th>what it checks</th><th>effect</th><th>source</th><th>mode</th><th></th></tr>
                  </thead>
                  <tbody>
                    {effective.rules.map((r: any) => (
                      <tr key={r.rule_id}>
                        <td className="small wrap" style={{ maxWidth: 340 }}>
                          {r.description || r.rule_id}
                          <div className="mono small muted">{r.rule_id}</div>
                        </td>
                        <td><span className={`tag ${r.effect === "block" ? "bad" : ""}`}>{r.effect}</span></td>
                        <td className="small muted">
                          {r.source}
                          {r.source && !r.source.startsWith("org:") && (
                            <span className="tag warn" title="Applies at a narrower scope than the org default.">custom</span>
                          )}
                        </td>
                        <td className="small muted">{r.mode}</td>
                        <td>{r.loosened && <span className="tag warn">loosened</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {effective.rejected?.length > 0 && (
                <div className="body small">
                  <strong>{effective.rejected.length} rule(s) rejected during composition:</strong>
                  <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                    {effective.rejected.map((r: any, i: number) => (
                      <li key={i} className="muted">{r.rule_id ? `${r.rule_id}: ` : ""}{r.message || r.code}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </>
        )}


        <h2>Knowledge boundary</h2>
        <Panel
          title={boundary ? "Declared" : "Not declared"}
          note="without one, nothing stops the agent inventing an answer it has no data for (P7)"
        >
          <form action={`/api/agents/${a.slug}/boundary`} method="POST" className="body stack">
            <div>
              <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
                Systems of record it may answer from (comma-separated)
              </label>
              <input
                type="text"
                name="systems_of_record"
                defaultValue={boundary?.systems_of_record?.join(", ") || ""}
                placeholder="e.g. price-book, ticket-history"
                style={{ width: "100%", maxWidth: 480, padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
              />
            </div>
            <div className="row">
              <div>
                <label className="small muted" style={{ display: "block", marginBottom: 4 }}>Coverage (months of history)</label>
                <input type="number" name="coverage_months" min={0} defaultValue={boundary?.coverage_months ?? ""} style={{ width: 100, padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }} />
              </div>
              <div>
                <label className="small muted" style={{ display: "block", marginBottom: 4 }}>Freshness (hours)</label>
                <input type="number" name="freshness_hours" min={0} defaultValue={boundary?.freshness_hours ?? ""} style={{ width: 100, padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }} />
              </div>
            </div>
            <div>
              <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
                Entity types it knows about (comma-separated)
              </label>
              <input
                type="text"
                name="entity_types"
                defaultValue={boundary?.entity_types?.join(", ") || ""}
                placeholder="e.g. customer, order, invoice"
                style={{ width: "100%", maxWidth: 480, padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
              />
            </div>
            <div>
              <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
                Topics it must refuse even if it has data (comma-separated)
              </label>
              <input
                type="text"
                name="out_of_scope_topics"
                defaultValue={boundary?.out_of_scope_topics?.join(", ") || ""}
                placeholder="e.g. legal advice, medical diagnosis"
                style={{ width: "100%", maxWidth: 480, padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
              />
            </div>
            <div>
              <label className="small muted" style={{ display: "block", marginBottom: 4 }}>Question types it may answer</label>
              <div className="row" style={{ gap: 14 }}>
                {questionTypes.map((qt) => (
                  <label key={qt} className="small" style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    <input
                      type="checkbox"
                      name="answerable_types"
                      value={qt}
                      defaultChecked={boundary ? boundary.answerable_types?.includes(qt) : true}
                    />
                    {qt}
                  </label>
                ))}
              </div>
            </div>
            <div>
              <button type="submit" className="btn-primary">
                {boundary ? "Update boundary" : "Declare boundary"}
              </button>
            </div>
          </form>
        </Panel>
        </>
      )}

      {tab === "registration" && (
        <>
        <form
          action={`/api/agents/${a.slug}/owner`}
          method="POST"
          className="row"
          style={{ gap: 6, marginBottom: 20, marginTop: 10, alignItems: "center" }}
        >
          <label className="small muted" htmlFor="purpose-input">Purpose</label>
          {!a.purpose && <span className="tag warn">not set</span>}
          <input
            id="purpose-input"
            type="text"
            name="purpose"
            placeholder="e.g. answers customer support questions from our help center"
            defaultValue={a.purpose || ""}
            style={{ flex: 1, minWidth: 260, maxWidth: 480, padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
          />
          <button type="submit" className="btn-scan">Save</button>
        </form>

        {/* The reach, drawn, before the reach listed. The table below is the same
          data and stays — it is what you read when you need the exact counts —
          but "how far does this thing go" is a shape, not four columns. */}
      {lineage.links?.length > 0 && (
        <AgentMap
          root={lineage.root || a.slug}
          nodes={lineage.nodes || []}
          links={lineage.links}
          blastRadius={lineage.blast_radius ?? 0}
        />
      )}

      <div className="grid2" style={{ marginTop: 22 }}>
          <Panel title="Registration">
            <table>
              <tbody>
                <tr><td className="muted">owner</td><td>{a.owner_email || <span className="tag warn">unowned</span>}</td></tr>
                <tr><td className="muted"></td><td className="small">
                  <form action={`/api/agents/${a.slug}/owner`} method="POST" className="row" style={{ gap: 6 }}>
                    <input
                      type="email"
                      name="owner_email"
                      placeholder="owner@company.com"
                      defaultValue={a.owner_email || ""}
                      required
                      style={{ padding: "3px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 12, fontFamily: "inherit" }}
                    />
                    <input
                      type="text"
                      name="owner_team"
                      placeholder="team (optional)"
                      defaultValue={a.owner_team || ""}
                      style={{ padding: "3px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 12, fontFamily: "inherit", width: 130 }}
                    />
                    <button type="submit" className="btn-primary">{a.owner_email ? "Update" : "Assign owner"}</button>
                  </form>
                </td></tr>
                <tr><td className="muted">team</td><td>{a.owner_team || "—"}</td></tr>
                <tr><td className="muted">environment</td><td>{a.environment}</td></tr>
                <tr><td className="muted">risk tier</td><td><span className="tag">{a.risk_tier}</span></td></tr>
                <tr><td className="muted">framework</td><td>{a.framework || "—"}</td></tr>
                <tr><td className="muted">registered</td><td>{a.registered ? <span className="tag ok">yes</span> : <span className="tag bad">unregistered</span>}</td></tr>
                <tr><td className="muted">declared models</td><td className="small mono">{a.declared_models?.join(", ") || "—"}</td></tr>
                <tr><td className="muted">declared tools</td><td className="small mono wrap">{a.declared_tools?.join(", ") || "—"}</td></tr>
                <tr><td className="muted">data classes</td><td className="small">{a.data_classes?.join(", ") || "—"}</td></tr>
                <tr><td className="muted">last seen</td><td className="small muted">{ts(a.last_seen_at)}</td></tr>
              </tbody>
            </table>
          </Panel>

          <Panel
            title="Observed lineage"
            note={
              <>
                derived from traces, not config{" "}
                <InfoTip text="'Observed' means seen actually happening in traced traffic. Contrast with the 'declared models'/'declared tools' rows in Registration, which are just what someone typed in — a mismatch between the two is itself a signal worth noticing. When a target is a registered tool, its impact tier (read, write, high_impact or irreversible) and — if it came through an MCP server — that server's trust level are shown alongside it." />
              </>
            }
          >
            {lineage.links.length === 0 ? (
              <div className="body muted small">No relationships observed yet.</div>
            ) : (
              <table>
                <thead>
                  <tr><th>from</th><th>relation</th><th>to</th><th className="num">seen</th></tr>
                </thead>
                <tbody>
                  {lineage.links.map((l: any, i: number) => (
                    <tr key={i}>
                      <td className="mono small">
                        {lineageNodeType[l.source] === "agent" ? (
                          <Link href={`/app/agents/${l.source}`}>{l.source}</Link>
                        ) : (
                          l.source
                        )}
                      </td>
                      <td className="small muted">{l.relation}</td>
                      <td className="mono small">
                        {lineageNodeType[l.target] === "agent" ? (
                          <Link href={`/app/agents/${l.target}`}>{l.target}</Link>
                        ) : (
                          l.target
                        )}
                        {toolByKey[l.target] && (
                          <>
                            {" "}
                            <span
                              className={`tag ${IMPACT_TONE[toolByKey[l.target].impact] ?? ""}`}
                              title={IMPACT_MEANS[toolByKey[l.target].impact]}
                            >
                              {toolByKey[l.target].impact}
                            </span>
                            {toolByKey[l.target].mcp_server_id && mcpById[toolByKey[l.target].mcp_server_id] && (
                              <span className="tag" title="MCP server trust level">
                                {mcpById[toolByKey[l.target].mcp_server_id].trust_level}
                              </span>
                            )}
                          </>
                        )}
                      </td>
                      <td className="num small">{l.observed_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>

        {classification && (
          <>
            <h2>
              Proposed risk classification
              <InfoTip text="EU AI Act terms: 'Annex III' lists the domains (employment, credit, law enforcement, etc.) that count as high-risk by default; 'Art. 14' requires a human-oversight gate before a high-impact action; 'Art. 50' requires disclosing that the user is talking to an AI. This is an advisory signal from purpose text and observed behavior, not a legal determination." />
            </h2>
            <Panel
              title={`EU AI Act — proposed: ${classification.proposed_class}`}
              note={`currently recorded as ${classification.current_class}`}
            >
              <div className="body">
                {classification.signals.length ? (
                  <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
                    {classification.signals.map((s: string) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                ) : (
                  <div className="muted small">No elevating signals observed.</div>
                )}
                <div className="caveat" style={{ marginBottom: 0 }}>
                  <strong>Requires human confirmation</strong>
                  {classification.caveat}
                </div>
                {classification.proposed_class !== classification.current_class && (
                  <form action={`/api/agents/${a.slug}/owner`} method="POST" style={{ marginTop: 10 }}>
                    <input type="hidden" name="risk_tier" value={classification.proposed_class} />
                    <button type="submit" className="btn-approve">
                      Accept — set risk tier to {classification.proposed_class}
                    </button>{" "}
                    <span className="small muted">
                      or leave as recorded ({classification.current_class}) to reject.
                    </span>
                  </form>
                )}
              </div>
            </Panel>
          </>
        )}

        <h2>
          Kill switch
          <InfoTip text="Quarantine: reversible, 'stop while I investigate.' Kill: the stronger incident action, requires the identity role rather than the registry role. Both refuse every governed call from this agent immediately and are logged to the audit chain." />
        </h2>
        <div className="panel body stack">
          <div className="row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <span className={`tag ${state === "active" ? "ok" : "bad"}`}>{state}</span>
            <form action={`/api/agents/${a.slug}/control`} method="POST" className="row" style={{ gap: 8, alignItems: "center", flex: 1, minWidth: 260 }}>
              <input type="hidden" name="action" value={state === "active" ? "quarantine" : "resume"} />
              <input
                type="text"
                name="reason"
                placeholder={state === "active" ? "reason for quarantining (optional)" : "reason for resuming (optional)"}
                style={{ flex: 1, minWidth: 200, padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
              />
              {state === "active" ? (
                <button type="submit" className="btn-reject">Quarantine</button>
              ) : (
                <button type="submit" className="btn-approve">Resume</button>
              )}
            </form>
          </div>
          {state !== "killed" && (
            <div className="row" style={{ gap: 10, alignItems: "center", paddingTop: 12, borderTop: "1px solid var(--hairline)" }}>
              <span className="small muted">Stronger incident action, different role:</span>
              <form action={`/api/agents/${a.slug}/control`} method="POST">
                <input type="hidden" name="action" value="kill" />
                <button type="submit" className="btn-reject">Kill</button>
              </form>
            </div>
          )}
        </div>
        </>
      )}
    </>
  );
}
