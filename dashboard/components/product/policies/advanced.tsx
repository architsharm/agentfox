/**
 * Policies → Advanced: the installed packs, detector tuning, and which AI judges may
 * decide and what data may leave. Each section opens with one line on what it is for
 * and the controls that change something; reports and reference material sit in
 * collapsed details below.
 */
import Link from "next/link";
import type { ReactNode } from "react";
import { api, apiErrorProps, safeApi } from "@/lib/product/api";
import { ApiDown, InfoTip, Severity } from "@/components/ui";
import { Card, Empty, Grid, Kpi, ModePill, Pill, href } from "@/components/kit";
import { Countdown } from "@/components/product/Countdown";
import { DetectorCatalogue } from "@/components/product/DetectorCatalogue";

export type AdvancedSection = "packs" | "tuning" | "judges";

export const ADVANCED_SECTIONS: { key: AdvancedSection; label: string; purpose: string }[] = [
  { key: "packs", label: "Packs", purpose: "Every installed pack and its mode, with the checks and probes behind them." },
  { key: "tuning", label: "Detector tuning", purpose: "Is each check right, fast enough, and not silenced?" },
  { key: "judges", label: "AI judges & egress", purpose: "Which AI judges may decide, and what data may leave this deployment." },
];

const sectionHref = (key: AdvancedSection, agent?: string) =>
  href("/app/policies", { tab: "advanced", sec: key === "packs" ? undefined : key, agent });

/** Section switcher and its one-line purpose. */
export function AdvancedNav({ section, agent }: { section: AdvancedSection; agent?: string }) {
  const current = ADVANCED_SECTIONS.find((s) => s.key === section)!;
  return (
    <div className="adv-nav">
      <div className="k-seg" role="tablist" aria-label="Advanced">
        {ADVANCED_SECTIONS.map((s) => (
          <Link key={s.key} href={sectionHref(s.key, agent)} role="tab" aria-selected={s.key === section} className={s.key === section ? "active" : ""}>
            {s.label}
          </Link>
        ))}
      </div>
      <p className="k-muted adv-purpose">{current.purpose}</p>
    </div>
  );
}

/** A GET form that narrows a section to one agent. */
function AgentFilter({ agents, agent, sec }: { agents: any[]; agent?: string; sec?: string }) {
  return (
    <form action="/app/policies" method="GET" className="adv-filter">
      <input type="hidden" name="tab" value="advanced" />
      {sec && <input type="hidden" name="sec" value={sec} />}
      <select className="k-select" name="agent" defaultValue={agent ?? ""} aria-label="Agent">
        <option value="">All agents</option>
        {agents.map((a: any) => (
          <option key={a.slug} value={a.slug}>
            {a.name || a.slug}
          </option>
        ))}
      </select>
      <button type="submit" className="k-btn">
        Apply
      </button>
    </form>
  );
}

function More({ summary, children }: { summary: ReactNode; children: ReactNode }) {
  return (
    <details className="adv-more">
      <summary>{summary}</summary>
      <div className="adv-more-body">{children}</div>
    </details>
  );
}

// --- Packs ---------------------------------------------------------------------------

export async function AdvancedPacks({ agent }: { agent?: string }) {
  let policies: any, detectors: any, probes: any, agents: any;
  try {
    [policies, detectors, probes, agents] = await Promise.all([
      api(agent ? `/api/policies?agent=${encodeURIComponent(agent)}` : "/api/policies"),
      safeApi("/api/detectors", { detectors: [], budget_ms: 0, detector_timeout_ms: 0 }),
      safeApi("/api/redteam/probes", { probes: [], runners: {} }),
      safeApi("/api/agents", { agents: [] }),
    ]);
  } catch (e: any) {
    return <ApiDown {...apiErrorProps(e)} />;
  }
  const all: any[] = policies.policies || [];
  const proposed = all.filter((p) => p.proposed);
  const dets: any[] = detectors.detectors || [];
  const on = dets.filter((d) => d.enabled && d.available).length;
  const idle = dets.filter((d) => !d.enabled && d.available).length;
  const missing = dets.filter((d) => !d.available).length;
  const tuning = sectionHref("tuning");

  return (
    <div className="adv-stack">
      {proposed.length > 0 && (
        <Card title="Waiting for review" hint="Proposed by a repo scan. They already watch and block nothing; approve to keep, reject to discard." flush>
          <table>
            <tbody>
              {proposed.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link href={`/app/policies/${p.key}`} className="k-name">
                      {p.name}
                    </Link>
                    <div className="k-muted k-mono adv-key">{p.key}</div>
                  </td>
                  <td className="adv-actions">
                    <form action={`/api/policies/${p.id}/approve`} method="POST">
                      <button type="submit" className="k-btn-primary">
                        Approve
                      </button>
                    </form>
                    <form action={`/api/policies/${p.id}/reject`} method="POST">
                      <button type="submit" className="k-btn">
                        Reject
                      </button>
                    </form>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Card
        title="Packs"
        hint="A pack governs every agent its scope pattern matches. Watching records what it would block; enforcing blocks."
        action={<AgentFilter agents={agents.agents || []} agent={agent} />}
        flush
      >
        {all.length === 0 ? (
          <Empty action={agent ? <Link href={sectionHref("packs")} className="k-btn">Show all</Link> : <Link href="/app/policies?tab=library" className="k-btn">Open the library</Link>}>
            {agent ? "No pack's scope matches this agent." : "No packs installed yet."}
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Pack</th>
                <th>Mode</th>
                <th className="num">Rules</th>
                <th className="num">Version</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {all.map((p) => (
                <tr key={p.key}>
                  <td>
                    <Link href={`/app/policies/${p.key}`} className="k-name" title={p.description || undefined}>
                      {p.name}
                    </Link>
                    <div className="k-muted k-mono adv-key">{p.key}</div>
                  </td>
                  <td>
                    <span className="k-pills">
                      <ModePill mode={p.mode} />
                      {p.proposed && <Pill tone="warn">Proposed</Pill>}
                    </span>
                  </td>
                  <td className="num">{p.rules}</td>
                  <td className="num k-muted">v{p.latest_version}</td>
                  <td className="num">
                    <Link href={`/app/policies/${p.key}`}>Open</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Grid cols={3}>
        <Kpi label="Checks on" value={on} href={tuning} />
        <Kpi label="Installed, off" value={idle} href="/app/policies?tab=checks" />
        <Kpi label="Not installed" value={missing} hint="Most are wrapped from other projects and one install command away. See the catalogue below." />
      </Grid>

      <More summary={`Check catalogue (${dets.length})${dets.filter((d) => !d.available && d.install).length ? `, ${dets.filter((d) => !d.available && d.install).length} one install away` : ""}`}>
        <DetectorCatalogue detectors={dets} />
      </More>

      <More summary={`Attack probes (${probes.probes.length})`}>
        <div className="adv-row">
          <span className="k-muted">Runners</span>
          {Object.entries(probes.runners || {}).map(([n, ok]) => (
            <Pill key={n} tone={ok ? "ok" : "outline"}>
              {n}
              {ok ? "" : ", not installed"}
            </Pill>
          ))}
          <Link href="/app/test" className="k-btn adv-push">
            Run against an agent
          </Link>
        </div>
        {probes.probes.length === 0 ? (
          <Empty>No probes listed. Reload; if it stays empty this deployment is missing its probe library.</Empty>
        ) : (
          <Card flush>
            <table>
              <thead>
                <tr>
                  <th>Probe</th>
                  <th>Category</th>
                  <th>Surface</th>
                  <th>Severity</th>
                  <th>OWASP</th>
                  <th>ATLAS</th>
                </tr>
              </thead>
              <tbody>
                {probes.probes.map((p: any) => (
                  <tr key={p.key}>
                    <td className="k-mono">{p.key}</td>
                    <td className="k-muted">{p.category}</td>
                    <td className="k-muted">{p.surface}</td>
                    <td>
                      <Severity value={p.severity} />
                    </td>
                    <td className="k-mono k-muted">{p.owasp_id || "-"}</td>
                    <td className="k-mono k-muted">{p.atlas_id || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </More>

      <More summary="Change proposals and the command line">
        <p className="adv-note">
          <strong>A loosening is never applied automatically.</strong> Its direction comes from the diff against live config.{" "}
          <Link href="/app/glossary#proposal">What a proposal carries</Link>
        </p>
        <Card flush>
          <table>
            <thead>
              <tr>
                <th>To</th>
                <th>Command</th>
                <th>HTTP</th>
              </tr>
            </thead>
            <tbody>
              {PROPOSAL_COMMANDS.map(([what, cmd, http]) => (
                <tr key={what}>
                  <td>{what}</td>
                  <td className="k-mono">{cmd}</td>
                  <td className="k-mono k-muted">{http}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <p className="k-muted adv-foot">
          Apply, rollback and verify need the <span className="k-mono">policy_production</span> permission. Simulate a candidate first with{" "}
          <span className="k-mono">agentfox policy simulate -f candidate.yaml</span>; it exits non-zero when it would newly block traffic.
        </p>
      </More>
    </div>
  );
}

const PROPOSAL_COMMANDS: [string, string, string][] = [
  ["See what is waiting", "agentfox policy proposals list --status proposed", "GET /api/proposals?status="],
  ["Read one", "agentfox policy proposals show ID", "GET /api/proposals/{id}"],
  ["Decide", 'agentfox policy proposals approve ID --note "..."', "POST /api/proposals/{id}/decide"],
  ["Apply", "agentfox policy proposals apply ID", "POST /api/proposals/{id}/apply"],
  ["Undo", 'agentfox policy proposals rollback ID --reason "..."', "POST /api/proposals/{id}/rollback"],
  ["Record if it worked", "agentfox policy proposals verify ID", "POST /api/proposals/{id}/verify"],
];

// --- Tuning ----------------------------------------------------------------------------

export async function AdvancedTuning({ agent }: { agent?: string }) {
  const qs = agent ? `agent=${encodeURIComponent(agent)}` : "";
  let detectors: any, latency: any, precision: any, recommendations: any, suppressions: any, agents: any, feedback: any;
  try {
    [detectors, latency, precision, recommendations, suppressions, agents, feedback] = await Promise.all([
      api("/api/detectors"),
      api(`/api/guardrails/latency?${qs}`),
      api(`/api/guardrails/precision?${qs}`),
      api("/api/guardrails/recommendations"),
      api(`/api/guardrails/suppressions?${qs}`),
      safeApi("/api/agents", { agents: [] }),
      api("/api/guardrails/feedback?limit=50"),
    ]);
  } catch (e: any) {
    return <ApiDown {...apiErrorProps(e)} />;
  }
  const health = suppressions.health || {};
  const degraded = latency.degraded_rate || 0;
  const expiring = health.expiring_within_7_days?.length || 0;
  const sups: any[] = suppressions.suppressions || [];
  const fb: any[] = (feedback.feedback || []).slice(0, 20);
  const prec = Object.entries(precision.detectors || {}) as [string, any][];

  return (
    <div className="adv-stack">
      <div className="adv-row">
        <AgentFilter agents={agents.agents || []} agent={agent} sec="tuning" />
      </div>
      <Grid cols={4}>
        <Kpi label="Checks on" value={(detectors.detectors || []).filter((d: any) => d.enabled && d.available).length} href="/app/policies?tab=checks" />
        <Kpi label={`Runs, last ${latency.window_days} days`} value={latency.runs} href="/app/observe" />
        <Kpi label="Ran late or skipped" value={`${(degraded * 100).toFixed(1)}%`} tone={degraded > 0.01 ? "warn" : undefined} hint="A check that timed out or was skipped to keep the agent responsive. High means gaps in the safety net." />
        <Kpi label="Suppressions" value={health.active || 0} tone={expiring ? "warn" : undefined} hint={expiring ? `${expiring} expire this week and start enforcing again.` : "Every exception expires."} />
      </Grid>

      <Card title="Suppressions" hint="Every exception expires: a permanent one cannot be told apart from a check that stopped working." flush>
        {sups.length ? (
          <table>
            <thead>
              <tr>
                <th>Check</th>
                <th>Scope</th>
                <th>Reason</th>
                <th className="num">Hits</th>
                <th>Expires</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {sups.map((s) => (
                <tr key={s.id}>
                  <td className="k-mono">{s.detector_key}</td>
                  <td>
                    {s.agent === "*" ? <span className="k-muted">All agents</span> : <Link href={`/app/agents/${s.agent}`}>{s.agent}</Link>}
                    {s.entity_type && <Pill tone="outline">{s.entity_type}</Pill>}
                  </td>
                  <td className="k-muted">{s.reason || "-"}</td>
                  <td className="num">
                    {s.hits}
                    {s.hits === 0 && <Pill tone="warn">Never used</Pill>}
                  </td>
                  <td>{s.active ? <Countdown at={s.expires_at} /> : <Pill tone="outline">Inactive</Pill>}</td>
                  <td className="num">
                    {s.active && (
                      <form action="/api/guardrails/suppressions/revoke" method="POST">
                        <input type="hidden" name="id" value={s.id} />
                        <button type="submit" className="k-btn">
                          Revoke
                        </button>
                      </form>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>None. Every detection is acted on.</Empty>
        )}
      </Card>

      <Card title="Feedback" hint="Verdicts people filed on detections, newest first. A false positive can become a 30-day suppression here." flush>
        {fb.length ? (
          <table>
            <thead>
              <tr>
                <th>Check</th>
                <th>Label</th>
                <th>Note</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {fb.map((f) => (
                <tr key={f.id}>
                  <td>
                    <span className="k-mono">{f.detector_key || "-"}</span>
                    {f.entity_type && <div className="k-muted k-mono adv-key">{f.entity_type}</div>}
                  </td>
                  <td>
                    <Pill tone={f.label === "false_positive" ? "bad" : f.label === "true_positive" ? "ok" : "warn"}>{String(f.label).replace(/_/g, " ")}</Pill>
                  </td>
                  <td className="k-muted adv-clamp" title={f.note || undefined}>
                    {f.note || "-"}
                    {f.actor && <div className="adv-key">{f.actor}</div>}
                  </td>
                  <td>
                    <Pill tone={f.status === "applied" ? "ok" : f.status === "rejected" ? "bad" : "outline"}>{f.status}</Pill>
                  </td>
                  <td className="num adv-actions">
                    {f.trace_id && <Link href={`/app/traces/${f.trace_id}`}>Trace</Link>}
                    {f.label === "false_positive" && f.status === "open" && f.detector_key && (
                      <form action="/api/guardrails/suppressions" method="POST">
                        <input type="hidden" name="feedback_id" value={f.id} />
                        <input type="hidden" name="ttl_days" value="30" />
                        <button type="submit" className="k-btn">
                          Suppress 30 days
                        </button>
                      </form>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No feedback yet. File it from a detection on a trace.</Empty>
        )}
      </Card>

      <More summary="How often each check is right">
        {prec.length ? (
          <Card flush>
            <table>
              <thead>
                <tr>
                  <th>Check</th>
                  <th className="num">Labelled</th>
                  <th className="num">False positives</th>
                  <th className="num">Precision</th>
                  <th>Suggestion</th>
                </tr>
              </thead>
              <tbody>
                {prec.map(([key, st]) => {
                  const rec = (recommendations.recommendations || []).find((r: any) => r.detector_key === key);
                  return (
                    <tr key={key}>
                      <td className="k-mono">{key}</td>
                      <td className="num">
                        {st.labelled}
                        {!st.sufficient_sample && <Pill tone="warn">Too few</Pill>}
                      </td>
                      <td className="num">{st.false_positive}</td>
                      <td className="num">{st.precision === null ? "-" : `${Math.round(st.precision * 100)}%`}</td>
                      <td>
                        {rec ? (
                          <span title={rec.rationale}>
                            <Pill tone={rec.action === "raise_threshold" ? "ok" : rec.action === "no_clean_separation" ? "bad" : "outline"}>{rec.action.replace(/_/g, " ")}</Pill>
                          </span>
                        ) : (
                          <span className="k-muted">-</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
        ) : (
          <Empty>No labelled detections yet.</Empty>
        )}
      </More>

      <More summary="How much each check costs in time">
        <Card flush>
          <table>
            <thead>
              <tr>
                <th>Check</th>
                <th className="num">Runs</th>
                <th className="num">p50 ms</th>
                <th className="num">p95 ms</th>
                <th className="num">Max ms</th>
              </tr>
            </thead>
            <tbody>
              {(detectors.detectors || []).map((d: any) => {
                const st = latency.per_detector?.[d.key] || {};
                const slow = (st.p95_ms || 0) > detectors.detector_timeout_ms;
                return (
                  <tr key={d.key}>
                    <td>
                      <span className="k-mono">{d.key}</span>{" "}
                      {!d.available && (
                        <Pill tone="warn" title={d.unavailable_reason || undefined}>
                          Unavailable
                        </Pill>
                      )}
                      {d.available && !d.enabled && <Pill tone="outline">Off</Pill>}
                    </td>
                    <td className="num">{st.runs ?? 0}</td>
                    <td className="num">{st.p50_ms ?? "-"}</td>
                    <td className={`num${slow ? " adv-bad" : ""}`}>{st.p95_ms ?? "-"}</td>
                    <td className="num">{st.max_ms ?? "-"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
        <p className="k-muted adv-foot">
          Budget {detectors.budget_ms} ms per call, {detectors.detector_timeout_ms} ms per check.
        </p>
      </More>

      <More summary="Turn false positives into rule proposals">
        <p className="adv-note">
          <span className="k-mono">agentfox policy proposals from-labels --days 30</span> files labelled false positives as proposed threshold changes and applies nothing. The{" "}
          <span className="k-mono">tuning.propose</span> job does the same daily.
          <InfoTip text="A person still decides each proposal. Read them with agentfox policy proposals list." />
        </p>
      </More>
    </div>
  );
}

// --- AI judges & egress --------------------------------------------------------------

type Kind = { combine: string; deciders: string[]; refused: Record<string, string> };

export type PostureDetail = {
  posture: { tiers: string[]; pii_egress: string; fail_closed: boolean; backend: string; version: number };
  ceiling: { allow_egress: boolean; pii_egress: string; fail_closed_required: boolean; explains: string };
  tiers: { tier: string; enabled: boolean; sends_data: boolean; selectable: boolean; blocked_reason: string }[];
  pii_egress_options: { value: string; label: string; detail: string; selectable: boolean }[];
  backends: { value: string; selectable: boolean }[];
  sends_anything: boolean;
  kinds: Record<string, Kind>;
};

const KIND_LABEL: Record<string, string> = {
  structural_parsed: "Parsed structure (SQL blast radius)",
  structural_grant: "Grant lookup (entitlement)",
  pattern_open: "Open-ended patterns (injection, personal data)",
  semantic: "Meaning (is this question contested)",
  performative: "What an utterance does (binding commitments)",
};

const TIER_LABEL: Record<string, [string, string]> = {
  deterministic: ["Deterministic", "Code, parsers and rules. Always on."],
  local_model: ["Local model", "Classifier weights on this host."],
  local_llm: ["Local LLM", "A model served on loopback."],
  jev: ["Jev", "TypeSafe System One, hosted."],
  llm: ["LLM as judge", "A hosted model."],
};

/**
 * The judgment posture form. It posts the whole document, because the risky changes
 * are combinations. The deployment's ceiling (egress, the personal-data floor,
 * failing closed) is shown disabled with its reason rather than hidden, and widening
 * egress needs an explicit confirmation; narrowing does not.
 */
export async function AdvancedJudges() {
  let detail: PostureDetail, me: any;
  try {
    [detail, me] = await Promise.all([api<PostureDetail>("/api/judgment/posture"), safeApi("/api/me", null)]);
  } catch (e) {
    return <ApiDown {...apiErrorProps(e)} />;
  }
  const canEdit = ["owner", "admin", "security"].includes(me?.role ?? "");
  const { posture, ceiling } = detail;
  const blocked = detail.tiers.filter((t) => !t.selectable && t.tier !== "deterministic").length;

  return (
    <div className="adv-stack">
      <div className={`adv-banner${detail.sends_anything ? " adv-banner-warn" : ""}`}>
        <Pill tone={detail.sends_anything ? "warn" : "ok"}>{detail.sends_anything ? "Data leaves" : "Nothing leaves"}</Pill>
        <span>
          {detail.sends_anything ? "This workspace sends payloads to a third party." : "Nothing leaves this deployment."}{" "}
          {!ceiling.allow_egress && <span className="k-muted">Egress is off for the deployment.</span>}
          <InfoTip
            text={
              ceiling.allow_egress
                ? "The deployment allows egress (allow_egress), so tiers that send data can be turned on here."
                : `AGENTFOX_ALLOW_EGRESS is off. ${ceiling.explains}`
            }
          />
        </span>
        <span className="k-muted adv-push">Version {posture.version}</span>
      </div>

      <form method="post" action="/api/judgment/posture">
        <input type="hidden" name="return_to" value="/app/policies?tab=advanced&sec=judges" />
        <fieldset disabled={!canEdit} className="adv-fieldset">
          <Grid cols={2}>
            <Card title="Judges" hint="Each judge is barred from the decision kinds it measured worse on, so turning one on cannot weaken an existing control.">
              <ul className="adv-choices">
                {detail.tiers.map((t) => {
                  const [name, what] = TIER_LABEL[t.tier] || [t.tier, ""];
                  return (
                    <li key={t.tier}>
                      <label className="adv-choice">
                        <input type="checkbox" name="tiers" value={t.tier} defaultChecked={t.enabled} disabled={!t.selectable} />
                        <span>
                          <strong>{name}</strong> <span className="k-muted">{what}</span>
                          {t.sends_data && (
                            <>
                              {" "}
                              <Pill tone="warn">Sends data out</Pill>
                            </>
                          )}
                          {t.blocked_reason && t.tier !== "deterministic" && <span className="adv-why">{t.blocked_reason}</span>}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
              {blocked > 0 && <p className="k-muted adv-foot">{blocked} can only be enabled by whoever runs the process.</p>}
            </Card>

            <Card title="Personal data on the way out">
              <ul className="adv-choices">
                {detail.pii_egress_options.map((o) => (
                  <li key={o.value}>
                    <label className="adv-choice">
                      <input type="radio" name="pii_egress" value={o.value} defaultChecked={posture.pii_egress === o.value} disabled={!o.selectable} />
                      <span>
                        <strong>{o.label}</strong>
                        <span className="adv-why">
                          {o.detail}
                          {!o.selectable && ` Not available: the deployment floor is ${ceiling.pii_egress}.`}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </Card>
          </Grid>

          <Card title="Save">
            <div className="k-form">
              <div className="k-field">
                <label htmlFor="adv-backend">Backend</label>
                <select id="adv-backend" className="k-select" name="backend" defaultValue={posture.backend}>
                  {detail.backends.map((b) => (
                    <option key={b.value} value={b.value} disabled={!b.selectable}>
                      {b.value}
                      {b.selectable ? "" : " (egress off)"}
                    </option>
                  ))}
                </select>
              </div>
              <div className="k-field">
                <label>On a judge outage</label>
                <span>
                  {/* A disabled checkbox is not submitted, so the required value goes in a hidden field. */}
                  {ceiling.fail_closed_required && <input type="hidden" name="fail_closed" value="on" />}
                  <label className="k-check">
                    <input
                      type="checkbox"
                      name={ceiling.fail_closed_required ? "fail_closed_display" : "fail_closed"}
                      defaultChecked={posture.fail_closed || ceiling.fail_closed_required}
                      disabled={ceiling.fail_closed_required}
                    />
                    Deny the request {ceiling.fail_closed_required && <span className="k-muted">(required here)</span>}
                  </label>
                </span>
              </div>
              <div className="k-field">
                <label htmlFor="adv-reason">Why</label>
                <input id="adv-reason" className="k-input" type="text" name="reason" required placeholder="Recorded in the audit log" />
              </div>
              <div className="k-field">
                <span />
                <label className="k-check">
                  <input type="checkbox" name="confirm_egress" />
                  I am sending more data out (needed only to widen egress)
                </label>
              </div>
              <div className="k-field">
                <span />
                <span>
                  <button type="submit" className="k-btn-primary">
                    Save
                  </button>
                </span>
              </div>
            </div>
          </Card>
        </fieldset>
      </form>
      {!canEdit && <p className="k-muted adv-foot">Read only for your role. Owners, admins and security can change this.</p>}

      <More summary="What each decision kind uses">
        <Card flush>
          <table>
            <thead>
              <tr>
                <th>Decision</th>
                <th>Decided by</th>
                <th>Not permitted</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(detail.kinds).map(([kind, k]) => (
                <tr key={kind}>
                  <td>{KIND_LABEL[kind] ?? kind}</td>
                  <td className="k-mono">{k.deciders.join(" → ")}</td>
                  <td className="k-muted">
                    {Object.keys(k.refused).length === 0
                      ? "-"
                      : Object.entries(k.refused).map(([tier, why]) => (
                          <div key={tier}>
                            <span className="k-mono">{tier}</span>: {why}
                          </div>
                        ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <p className="k-muted adv-foot">
          A self-hosted model on loopback counts as <span className="k-mono">local_llm</span> and does not egress. <Link href="/docs/benchmarks">Measurements</Link>
        </p>
      </More>
    </div>
  );
}
