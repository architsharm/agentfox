import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { api, safeApi, apiErrorProps } from "@/lib/api";
import { ApiDown, Empty, InfoTip, InventoryStrip, Panel, Severity, Stat, agentName } from "@/components/ui";
import { PageHeader } from "@/components/PageHeader";
import { Countdown } from "@/components/Countdown";
import { DetectorCatalogue } from "@/components/DetectorCatalogue";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata(
  "Policies",
  "Rules as versioned, reviewable code, with the guardrail tuning behind them.",
);

export const dynamic = "force-dynamic";

const TABS: { key: string; label: string }[] = [
  { key: "rules", label: "Rules" },
  { key: "guardrails", label: "Guardrail tuning" },
];

export default async function Policies({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string; review_error?: string; review_notice?: string; agent?: string }>;
}) {
  const { tab: rawTab, review_error, review_notice, agent } = await searchParams;
  const tab = TABS.some((t) => t.key === rawTab) ? rawTab! : "rules";

  return (
    <>
      <PageHeader
        title="Policies"
        sub={
          <>
            The rules each agent follows, and whether each one is watching (
            <span className="mono">observe</span>) or stopping things (
            <span className="mono">enforce</span>).
          </>
        }
      />

      {review_error && <div className="error">{review_error}</div>}
      {review_notice && <div className="note-panel">{review_notice}</div>}

      <div className="tabbar">
        {TABS.map((t) => (
          <Link
            key={t.key}
            href={t.key === "rules" ? "/app/policies" : `/app/policies?tab=${t.key}`}
            className={tab === t.key ? "active" : ""}
          >
            {t.label}
          </Link>
        ))}
      </div>

      {tab === "rules" ? <RulesTab agent={agent} /> : <GuardrailTuningTab agent={agent} />}
    </>
  );
}

async function RulesTab({ agent }: { agent?: string }) {
  const policiesPath = agent ? `/api/policies?agent=${encodeURIComponent(agent)}` : "/api/policies";
  let policies: any, detectors: any, probes: any, agents: any;
  try {
    [policies, detectors, probes, agents] = await Promise.all([
      api(policiesPath),
      safeApi("/api/detectors", { detectors: [], budget_ms: 0, detector_timeout_ms: 0 }),
      safeApi("/api/redteam/probes", { probes: [], runners: {} }),
      safeApi("/api/agents", { agents: [] }),
    ]);
  } catch (e: any) {
    return <ApiDown {...apiErrorProps(e)} />;
  }

  const proposed = policies.policies.filter((p: any) => p.proposed);

  return (
    <>
      {/* Removed: a callout at the top of every load that said what the mode
          column's own tooltip already says — "tool containment ships in enforce:
          it reads no text, so it has no false positives to tune, and it is the
          control meant to hold when a content filter has already been fooled".
          The claim is worth making; making it twice, one of them in a bordered
          box above the table on every visit, is not. The row it is about is in
          the table, and says `enforce` where the others say `observe`. */}
      {proposed.length > 0 && (
        <>
          <h2>Pending review</h2>
          <Panel
            title="Proposed by a repo scan"
            note="already in observe mode (blocks nothing) — approve to acknowledge, reject to discard"
          >
            <table>
              <thead>
                <tr>
                  <th>policy</th>
                  <th>description</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {proposed.map((p: any) => (
                  <tr key={p.id}>
                    <td>
                      <Link href={`/app/policies/${p.key}`}>{p.name}</Link>
                      <div className="small muted mono">{p.key}</div>
                    </td>
                    <td className="small wrap muted" style={{ maxWidth: 420 }}>
                      {p.description}
                    </td>
                    <td>
                      <div className="review-actions">
                        <form action={`/api/policies/${p.id}/approve`} method="POST">
                          <button type="submit" className="btn-approve">
                            Approve
                          </button>
                        </form>
                        <form action={`/api/policies/${p.id}/reject`} method="POST">
                          <button type="submit" className="btn-reject">
                            Reject
                          </button>
                        </form>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}

      <h2>All policies</h2>
      <p className="sub">
        One policy commonly governs many agents at once, matched by name pattern.
        <InfoTip text="A pattern such as 'every agent starting with support-', rather than agents picked one at a time." />
      </p>
      <form action="/app/policies" method="GET" className="chipbar" style={{ marginBottom: 4 }}>
        <label htmlFor="policies-agent-filter" className="chipbar-label">agent:</label>
        <select
          id="policies-agent-filter"
          name="agent"
          defaultValue={agent ?? ""}
          style={{ padding: "3px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 12, fontFamily: "inherit" }}
        >
          <option value="">all agents</option>
          {(agents.agents || []).map((a: any) => (
            <option key={a.slug} value={a.slug}>{a.name || a.slug}</option>
          ))}
        </select>
        <button type="submit" className="chip" style={{ cursor: "pointer" }}>filter</button>
        {agent && <Link href="/app/policies" className="chip">clear agent ×</Link>}
      </form>
      <div className="panel scroll-x">
        {/* Two different nothings. A filter that matched nothing is a dead end to
            back out of; no policies at all is a workspace nobody has connected
            yet, and the fix for that is on another page entirely. Gating only on
            `agent` sent the second case a bare column header and no sentence. */}
        {policies.policies.length === 0 ? (
          agent ? (
            <Empty>
              No policy's declared scope matches &lsquo;{agentName(agents, agent)}&rsquo;.
              Clear the filter to see all of them.
              <InfoTip text="Policies are scoped by name pattern, so an agent can be covered by a policy that never names it." />
            </Empty>
          ) : (
            <Empty>
              No policies yet. Connect a repository on{" "}
              <Link href="/app/start?tab=connect">Start here</Link>: the scan proposes a
              starting set, in observe mode, to review here.
            </Empty>
          )
        ) : (
        <table>
          <thead>
            <tr>
              <th>policy</th><th>description</th><th>version</th>
              <th>
                mode
                <InfoTip text="Observe records what a policy would have blocked without blocking it, so you can check it is not too trigger-happy before promoting it — a policy that blocks the moment it is turned on is how a real safety rule ends up disabled by an annoyed engineer. The content policies ship in observe for that reason. Tool containment ships in enforce: it reads no text, so it has no false positives to tune, and it is the control meant to hold when a content filter has already been fooled." />
              </th>
              <th className="num">rules</th>
              {/* A policy row linked only from its name, so "these are editable"
                  was something you found out by clicking a title and noticing a
                  button on the next page. Named action, every row. */}
              <th />
            </tr>
          </thead>
          <tbody>
            {policies.policies.map((p: any) => (
              <tr key={p.key}>
                <td>
                  <Link href={`/app/policies/${p.key}`}>{p.name}</Link>
                  <div className="small muted mono">{p.key}</div>
                  {p.proposed && <div><span className="tag warn">proposed</span></div>}
                </td>
                <td className="small wrap muted" style={{ maxWidth: 420 }}>{p.description}</td>
                <td className="small">v{p.latest_version}</td>
                <td>
                  <span className={`tag ${p.mode === "enforce" ? "ok" : "warn"}`}>
                    {p.mode || "unbound"}
                  </span>
                </td>
                <td className="num">{p.rules}</td>
                <td className="small" style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <Link href={`/app/policies/${p.key}`}>Review &amp; edit &rarr;</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        )}
      </div>

      <p className="page-foot">
        Simulate a change before promoting it:{" "}
        <code className="mono">agentfox policy simulate -f candidate.yaml</code> exits
        non-zero when it would newly block production traffic.
      </p>

      {/* Was a heading whose entire body was one sentence pointing at another tab
          — a section that contained no section. The three numbers in that sentence
          are the only content it had, so they are the row now, and each one is the
          link it was describing. */}
      <h2>Detectors</h2>
      <InventoryStrip
        items={[
          {
            n: detectors.detectors.filter((d: any) => d.enabled && d.available).length,
            label: "turned on here",
            href: "/app/policies?tab=guardrails",
          },
          {
            n: detectors.detectors.filter((d: any) => !d.enabled && d.available).length,
            label: "available, not turned on",
            href: "/app/policies?tab=guardrails",
          },
          {
            n: detectors.detectors.filter((d: any) => !d.available).length,
            label: "not installed",
            href: "/app/policies?tab=guardrails",
          },
        ]}
      />
      <p className="page-foot">
        Cost, precision and suppressions for each are on the{" "}
        <Link href="/app/policies?tab=guardrails">Guardrail tuning tab</Link>.
      </p>

      {/* "Not installed" was a number with nowhere to go.
       
          Most of that number is the Guardrails AI Hub, wrapped one validator per
          detector — so it is not a deficiency, it is a catalogue, and a reader
          should be able to see what is in it and take one. Each row carries the
          exact command, because "install the package" without the name is the
          same dead end the count was. */}
      <DetectorCatalogue detectors={detectors.detectors} />

      {/* Was a heading, a sentence pointing elsewhere, and a 22-row reference
          table open on every load — a catalogue you could read but not act on.
          The action is now on the heading, and the catalogue is behind it. */}
      <div className="section-head">
        <h2>
          Attack simulations
          <InfoTip text="Scripted attempts to break an agent: getting it to leak a secret, ignore its instructions, or say something it shouldn't." />
        </h2>
        <Link href="/app/evals#redteam" className="btn-primary">
          Run these against an agent &rarr;
        </Link>
      </div>
      <p className="sub">
        {probes.probes.length} probes ship with the product and run through the same
        enforcement path as live traffic.
      </p>
      <details className="rt-more">
        <summary>The full probe catalogue ({probes.probes.length})</summary>
      <div className="panel scroll-x">
        {/* This list comes from a `safeApi` fallback, so an empty array here is
            just as likely to mean the probes call failed as it is to mean there
            are none — either way, column headers over nothing said neither. */}
        {probes.probes.length === 0 ? (
          <Empty>
            None listed. Reload; if it stays empty this deployment is missing its
            probe library.
            <InfoTip text="They ship with the product, so an empty list here usually means the control plane could not be asked for them rather than that none exist." />
          </Empty>
        ) : (
        <table>
          <thead>
            <tr><th>probe</th><th>category</th><th>surface</th><th>severity</th><th>OWASP</th><th>ATLAS</th></tr>
          </thead>
          <tbody>
            {probes.probes.map((p: any) => (
              <tr key={p.key}>
                <td className="mono small">{p.key}</td>
                <td className="small muted">{p.category}</td>
                <td className="small muted">{p.surface}</td>
                <td><Severity value={p.severity} /></td>
                <td className="small mono muted">{p.owasp_id || "—"}</td>
                <td className="small mono muted">{p.atlas_id || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        )}
      </div>
      </details>
      <p className="page-foot">
        Wrapped runners:{" "}
        {Object.entries(probes.runners || {}).map(([n, ok]) => (
          <span key={n} className={`tag ${ok ? "ok" : ""}`} style={{ marginRight: 6 }}>
            {n}{ok ? "" : " (not installed)"}
          </span>
        ))}
      </p>

      <ChangeProposals />
    </>
  );
}

/**
 * The improvement loop has a full API and an `agentfox proposals` command group and
 * no screen at all, so a dashboard user has no way to learn it exists, let alone
 * that there may be proposals waiting on their decision. Until there is a page for
 * it, saying so plainly here is better than the current silence.
 */
function ChangeProposals() {
  return (
    <>
      <h2>Change proposals</h2>
      <p className="sub">
        This product proposes changes to its own configuration rather than making
        them. There is no screen for them yet — each step is a command, below.{" "}
        <Link href="/app/glossary#proposal">What a proposal carries</Link>.
      </p>
      {/* Was three paragraphs in a note-panel, and all three were already in the
          Glossary's own Proposal entry — the page restated the definition next to
          the commands rather than linking to it. Only one of the three facts
          changes what an operator does, so only that one is a callout now. */}
      <div className="note-panel" style={{ marginTop: 0 }}>
        <strong>A loosening change is never applied automatically.</strong> Direction
        is computed from the diff against live configuration, not taken from whoever
        filed it.{" "}
        <InfoTip text="A loosening at org level needs two different approvers. Undoing a tightening counts as a loosening, so only a person can do that too." />
      </div>
      <div className="panel scroll-x" style={{ marginTop: 14 }}>
        <table>
          <thead>
            <tr><th>to do this</th><th>command</th><th>over HTTP</th></tr>
          </thead>
          <tbody>
            <tr>
              <td className="small">See what is waiting</td>
              <td className="mono small">agentfox proposals list --status proposed</td>
              <td className="mono small muted">GET /api/proposals?status=</td>
            </tr>
            <tr>
              <td className="small">Read one in full</td>
              <td className="mono small">agentfox proposals show ID</td>
              <td className="mono small muted">GET /api/proposals/{"{id}"}</td>
            </tr>
            <tr>
              <td className="small">Decide on one</td>
              <td className="mono small">agentfox proposals approve ID --actor you --note &quot;...&quot;</td>
              <td className="mono small muted">POST /api/proposals/{"{id}"}/decide</td>
            </tr>
            <tr>
              <td className="small">Put it into effect</td>
              <td className="mono small">agentfox proposals apply ID</td>
              <td className="mono small muted">POST /api/proposals/{"{id}"}/apply</td>
            </tr>
            <tr>
              <td className="small">Undo it</td>
              <td className="mono small">agentfox proposals rollback ID --reason &quot;...&quot;</td>
              <td className="mono small muted">POST /api/proposals/{"{id}"}/rollback</td>
            </tr>
            <tr>
              <td className="small">
                Record whether it worked
                <InfoTip text="Approving a proposal is not evidence that it worked. A verification marked failed rolls the change back, unless rolling back would itself loosen a control." />
              </td>
              <td className="mono small">agentfox proposals verify ID --actor you</td>
              <td className="mono small muted">POST /api/proposals/{"{id}"}/verify</td>
            </tr>
          </tbody>
        </table>
      </div>
      {/* Two unrelated sentences were glued into one trailing line: who may run
          these, and where proposals come from. They answer different questions,
          so they are two lines. */}
      <p className="page-foot">
        Apply, rollback and verify need the{" "}
        <span className="mono">policy_production</span> permission.
        <InfoTip text="The actor is taken from whoever is authenticated, not from a field you fill in." />
        <br />
        False positives you label on the{" "}
        <Link href="/app/policies?tab=guardrails">Guardrail tuning tab</Link> arrive
        here as proposed rule changes.
      </p>
    </>
  );
}

/**
 * P3-12/13/14 — the tuning surface, which had an API and no page.
 *
 * The question this answers is not "is a detector configured" but "should I trust
 * it, and what is it costing me" — precision beside its sample size, latency as
 * percentiles rather than a mean, and every suppression with an expiry date.
 */
async function GuardrailTuningTab({ agent }: { agent?: string }) {
  const agentQs = agent ? `agent=${encodeURIComponent(agent)}` : "";
  let detectors: any, latency: any, precision: any, recommendations: any, suppressions: any, agents: any, feedback: any;
  try {
    [detectors, latency, precision, recommendations, suppressions, agents, feedback] = await Promise.all([
      api("/api/detectors"),
      api(`/api/guardrails/latency?${agentQs}`),
      api(`/api/guardrails/precision?${agentQs}`),
      api("/api/guardrails/recommendations"),
      api(`/api/guardrails/suppressions?${agentQs}`),
      safeApi("/api/agents", { agents: [] }),
      api("/api/guardrails/feedback?limit=50"),
    ]);
  } catch (e: any) {
    return <ApiDown {...apiErrorProps(e)} />;
  }

  const health = suppressions.health || {};
  const degraded = latency.degraded_rate || 0;

  return (
    <>
      <p className="small muted" style={{ marginTop: 4, marginBottom: 12 }}>
        Are these checks catching real problems, slowing agents down, or silenced?
      </p>

      <form action="/app/policies" method="GET" className="chipbar" style={{ marginBottom: 4 }}>
        <input type="hidden" name="tab" value="guardrails" />
        <label htmlFor="guardrails-agent-filter" className="chipbar-label">agent:</label>
        <select
          id="guardrails-agent-filter"
          name="agent"
          defaultValue={agent ?? ""}
          style={{ padding: "3px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 12, fontFamily: "inherit" }}
        >
          <option value="">all agents</option>
          {(agents.agents || []).map((a: any) => (
            <option key={a.slug} value={a.slug}>{a.name || a.slug}</option>
          ))}
        </select>
        <button type="submit" className="chip" style={{ cursor: "pointer" }}>filter</button>
        {agent && <Link href="/app/policies?tab=guardrails" className="chip">clear agent ×</Link>}
      </form>

      {/* Five tiles, three of them zero, and `tone="ok"` painted the zeros green
          — so "0 checks turned off" and "0.0% ran late" glowed as loudly as a
          real number. A tile is for something that wants a person; none of these
          do until they are non-zero, and then only two of them. */}
      {(degraded > 0.01 || (health.expiring_within_7_days?.length || 0) > 0) && (
        <div className="cards">
          {degraded > 0.01 && (
            <Stat
              n={`${(degraded * 100).toFixed(1)}%`}
              label="checks that ran late or got skipped"
              tone="warn"
              hint="A check that took too long (degraded, only partly ran) or got skipped to keep the agent responsive. High here means the safety net has holes, not that anything caught a real problem."
            />
          )}
          {(health.expiring_within_7_days?.length || 0) > 0 && (
            <Stat
              n={health.expiring_within_7_days.length}
              label="suppressions expiring this week"
              tone="warn"
              hint="Suppressions are time-boxed on purpose: these start enforcing again automatically unless someone renews them."
            />
          )}
        </div>
      )}

      <InventoryStrip
        items={[
          {
            n: detectors.detectors.filter((d: any) => d.available).length,
            label: "checks turned on",
            href: "/app/policies?tab=guardrails",
          },
          {
            n: latency.runs,
            label: `checks run, last ${latency.window_days} days`,
            href: "/app/traces",
          },
          {
            n: `${(degraded * 100).toFixed(1)}%`,
            label: "ran late or skipped",
            href: "/app/policies?tab=guardrails",
          },
          {
            n: health.active || 0,
            label: "suppressed for a specific case",
            href: "/app/policies?tab=guardrails",
          },
        ]}
      />

      {/* The tab is called "Guardrail tuning" and its first two thirds were a
          latency report and a precision report — measurement, not tuning. The two
          things you can actually change from this page, revoking a suppression
          and labelling a detection so it becomes one, were at 622 and 680 lines
          down, under both reports.

          Tuning first, then the measurements that justify it, collapsed. The
          reports are why you would tune, and they are worth reading once, not on
          every visit to revoke one exception. */}
      <h2>Suppressions</h2>
      <p className="sub">
        Every exception expires.
        <InfoTip text="A permanent silent exception is indistinguishable from a detector that stopped working." />
      </p>
      <div className="panel">
        {suppressions.suppressions?.length ? (
          <table>
            <thead>
              <tr>
                <th>detector</th>
                <th>scope</th>
                <th>reason</th>
                <th>hits</th>
                <th>expires</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {suppressions.suppressions.map((s: any) => (
                <tr key={s.id}>
                  <td className="mono">{s.detector_key}</td>
                  <td className="small">
                    {s.agent === "*" ? (
                      <span className="muted">all agents</span>
                    ) : (
                      <Link href={`/app/agents/${s.agent}`}>{s.agent}</Link>
                    )}
                    {s.entity_type && <span className="tag">{s.entity_type}</span>}
                  </td>
                  <td className="small muted">{s.reason || "—"}</td>
                  <td className="mono small">
                    {s.hits}
                    {s.hits === 0 && <span className="tag warn">never used</span>}
                  </td>
                  <td className="small">
                    {s.active ? <Countdown at={s.expires_at} /> : <span className="tag">inactive</span>}
                  </td>
                  <td className="small">
                    {s.active && (
                      <form action="/api/guardrails/suppressions/revoke" method="POST">
                        <input type="hidden" name="id" value={s.id} />
                        <button type="submit" className="chip" style={{ cursor: "pointer" }}>revoke</button>
                      </form>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No suppressions. Every detection is currently acted on.</Empty>
        )}
      </div>

      <h2>Feedback log</h2>
      <p className="sub">
        Every verdict a human has filed, most recent first. A false positive is one
        click from a scoped, expiring suppression.
      </p>
      <div className="panel scroll-x">
        {feedback.feedback?.length ? (
          <table>
            <thead>
              <tr>
                <th>detector</th>
                <th>entity</th>
                <th>label</th>
                <th>note</th>
                <th>actor</th>
                <th>status</th>
                <th>trace</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {feedback.feedback.slice(0, 20).map((f: any) => (
                <tr key={f.id}>
                  <td className="mono small">{f.detector_key || <span className="muted">—</span>}</td>
                  <td className="mono small">{f.entity_type || <span className="muted">—</span>}</td>
                  <td>
                    <span className={`tag ${f.label === "false_positive" ? "bad" : f.label === "true_positive" ? "ok" : "warn"}`}>
                      {f.label.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="small muted wrap" style={{ maxWidth: 260 }}>{f.note || "—"}</td>
                  <td className="small muted">{f.actor || "—"}</td>
                  <td className="small">
                    <span className={`tag ${f.status === "applied" ? "ok" : f.status === "rejected" ? "bad" : ""}`}>{f.status}</span>
                  </td>
                  <td className="small">
                    {f.trace_id ? <Link href={`/app/traces/${f.trace_id}`}>trace</Link> : <span className="muted">—</span>}
                  </td>
                  <td className="small">
                    {f.label === "false_positive" && f.status === "open" && f.detector_key ? (
                      <form action="/api/guardrails/suppressions" method="POST" className="row" style={{ gap: 4, alignItems: "center" }}>
                        <input type="hidden" name="feedback_id" value={f.id} />
                        <input type="hidden" name="ttl_days" value="30" />
                        <button type="submit" className="chip" style={{ cursor: "pointer" }}>suppress 30d</button>
                      </form>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No feedback filed yet.</Empty>
        )}
      </div>

      <div className="note-panel">
        <strong>A false positive can become a proposed rule change, not just a
        suppression.</strong>{" "}
        <span className="mono">agentfox proposals from-labels --days 30</span> files the
        false positives labelled above as proposed cut-off changes to the rules that
        produced them, and applies nothing. The <span className="mono">tuning.propose</span>{" "}
        job runs the same work daily.
        <InfoTip text="A person still decides each proposal, and proposals can be waiting even if you never run the command." />{" "}
        Read them with <span className="mono">agentfox proposals list</span>. What they
        are and how deciding works is on the <Link href="/app/policies">Rules tab</Link>.
      </div>

      <details className="rt-more" style={{ marginTop: 20 }}>
        <summary>How often each check is actually right</summary>
        <div className="panel">
          {Object.keys(precision.detectors || {}).length ? (
            <table>
              <thead>
                <tr>
                  <th>detector</th>
                  <th>labelled</th>
                  <th>false pos</th>
                  <th>precision</th>
                  <th>recommendation</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(precision.detectors).map(([key, stats]: [string, any]) => {
                  const rec = (recommendations.recommendations || []).find(
                    (r: any) => r.detector_key === key
                  );
                  return (
                    <tr key={key}>
                      <td className="mono">{key}</td>
                      <td className="mono small">
                        {stats.labelled}
                        {!stats.sufficient_sample && (
                          <span className="tag warn">too few</span>
                        )}
                      </td>
                      <td className="mono small">{stats.false_positive}</td>
                      <td className="mono small">
                        {stats.precision === null ? "—" : `${Math.round(stats.precision * 100)}%`}
                      </td>
                      <td className="small">
                        {rec ? (
                          <>
                            <span
                              className={`tag ${
                                rec.action === "raise_threshold"
                                  ? "ok"
                                  : rec.action === "no_clean_separation"
                                  ? "bad"
                                  : ""
                              }`}
                            >
                              {rec.action.replace(/_/g, " ")}
                            </span>
                            <div className="muted">{rec.rationale}</div>
                          </>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <Empty>
              No feedback yet. File it from a detection on a{" "}
              <Link href="/app/traces">trace</Link>.
              <InfoTip text="The alternative is that somebody turns the detector off instead, and nobody finds out." />
            </Empty>
          )}
        </div>
      </details>

      <details className="rt-more" style={{ marginTop: 20 }}>
        <summary>How much each check slows things down</summary>
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>check</th>
                <th>version</th>
                <th>runs</th>
                <th>typical (p50)</th>
                <th>slow (p95)</th>
                <th>worst case</th>
              </tr>
            </thead>
            <tbody>
              {detectors.detectors.map((d: any) => {
                const stats = latency.per_detector?.[d.key] || {};
                const slow = (stats.p95_ms || 0) > detectors.detector_timeout_ms;
                return (
                  <tr key={d.key}>
                    <td>
                      <span className="mono">{d.key}</span>
                      {!d.available && (
                        <span className="tag warn">
                          unavailable
                          {d.unavailable_reason && <InfoTip text={d.unavailable_reason} />}
                        </span>
                      )}
                      {!d.enabled && <span className="tag">off</span>}
                    </td>
                    <td className="small muted">{d.version}</td>
                    <td className="mono small">{stats.runs ?? 0}</td>
                    <td className="mono small">{stats.p50_ms ?? "—"}</td>
                    <td className={`mono small ${slow ? "bad" : ""}`}>{stats.p95_ms ?? "—"}</td>
                    <td className="mono small">{stats.max_ms ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="body small muted">
            Budget {detectors.budget_ms} ms per call, {detectors.detector_timeout_ms} ms per
            detector.
          </div>
        </div>
      </details>

    </>
  );
}
