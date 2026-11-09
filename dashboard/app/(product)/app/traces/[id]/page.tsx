import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { ApiError, api, apiErrorProps, safeApi } from "@/lib/product/api";
import { ApiDown, NotFound, removedByRetention } from "@/components/ui";
import {
  ActionPill,
  Card,
  Empty,
  Header,
  Meta,
  ModePill,
  OutcomePill,
  Pill,
  Tabs,
  href,
  money,
  when,
} from "@/components/kit";
import { SURFACES, TRUST, WOULD, detectorName, outcomeOf, ruleTitle, sentence } from "@/lib/product/vocab";
import type { ReactNode } from "react";
import { NoticeToast } from "@/components/product/NoticeToast";
import { approvalOutcome } from "@/lib/product/approvals";
import { agentNames, withAgentNames } from "@/lib/product/names";
import { handoffTarget, runTitle } from "@/lib/product/runWhat";

export const metadata: Metadata = appPageMetadata("Run");
export const dynamic = "force-dynamic";

const TABS = [
  { key: "summary", label: "Summary" },
  { key: "steps", label: "Steps" },
  { key: "checks", label: "Checks" },
  { key: "origin", label: "Data origin" },
  { key: "raw", label: "Raw" },
];

function firstSentence(text?: string | null): string {
  if (!text) return "";
  // A sentence ends at ". " followed by a capital, after at least 25 characters —
  // so "EU AI Act Art. 14" is not cut at "Art.".
  const m = text.match(/^(.{25,}?[.!?])\s+(?=[A-Z])/);
  return (m ? m[1] : text).slice(0, 220);
}

/** Why a rule fired, in words — from the decision's own facts where possible. */
function plainReason(rule: any, decision: any): string {
  const taint = decision?.taint || {};
  const args = taint.arguments || {};
  const untrusted = Object.entries(args).filter(([, src]) => src && src !== "user" && src !== "none");
  const cap = taint.capability || {};
  if (rule.rule_id === "capability.denied") return "This agent has no permission for this tool.";
  if (rule.rule_id === "capability.constraint_violated" && cap.constraint_reason) return firstSentence(cap.constraint_reason);
  if ((rule.rule_id.startsWith("taint.") || rule.rule_id === "capability.approval_required") && untrusted.length) {
    return untrusted.map(([a, src]) => `"${a}" came from ${trustLabel(String(src)).toLowerCase()}`).join(", ") + ".";
  }
  if (rule.rule_id === "capability.approval_required") return "This action needs a person's sign-off.";
  return firstSentence(rule.reason);
}

function trustLabel(source?: string | null): string {
  return TRUST.find((t) => t.key === source)?.label.replace(/^\+ /, "") || source || "—";
}

export default async function RunDetail({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string; review_error?: string; review_notice?: string }>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const tab = TABS.some((t) => t.key === sp.tab) ? sp.tab! : "summary";

  let d: any;
  try {
    d = await api(`/api/traces/${id}`);
  } catch (e: any) {
    return (
      <>
        <Header title="Run" back={{ href: "/app/traces", label: "Activity" }} />
        {e instanceof ApiError && e.status === 404 ? (
          <NotFound
            what="run"
            detail={id}
            back={{ href: "/app/traces", label: "Activity" }}
            removedOn={removedByRetention(e.message)}
          />
        ) : (
          <ApiDown {...apiErrorProps(e)} />
        )}
      </>
    );
  }

  const t = d.trace;
  // Issue titles carry the agent's slug; on screen it has its display name.
  const decisions: any[] = d.decisions || [];
  // ...and so does an agent a hand-off names, in the title when nothing was asked.
  const handsOff = !t.asked && decisions.some((x) => handoffTarget(x.tool));
  const names = (d.findings || []).length || handsOff ? agentNames((await safeApi<any>("/api/agents", { agents: [] })).agents) : new Map<string, string>();
  const outcome = outcomeOf(t.verdict);
  const title = runTitle(t, decisions, SURFACES, names);
  const fired = decisions.flatMap((x) => (x.rules_fired || []).map((r: any) => ({ ...r, decision: x })));
  const watchedEffect = fired.find((r) => r.mode === "observe" && ["block", "escalate"].includes(r.effect))?.effect;
  const denied = fired.find((r) => r.rule_id === "capability.denied");
  const primaryRule = fired.find((r) => r.mode !== "observe") || fired[0];
  // A held call's answer: the run reads Held only while nobody has decided.
  const heldApproval = decisions.find((x) => x.verdict === "escalate" && x.approval)?.approval;
  const answered = approvalOutcome(heldApproval);
  const duration = (d.spans || []).reduce((n: number, s: any) => n + (s.duration_ms || 0), 0);
  const tabHref = (k: string) => href(`/app/traces/${id}`, { tab: k === "summary" ? undefined : k });

  return (
    <>
      <Header
        back={{ href: "/app/traces", label: "Activity" }}
        title={title}
        meta={
          <>
            {decisions.length ? <OutcomePill outcome={outcome} /> : <Pill tone="outline">Nothing checked</Pill>}
            {outcome === "held" && answered && (
              <Link href={`/app/approvals/${heldApproval.id}`}>
                <Pill tone={answered.tone}>{answered.label}</Pill>
              </Link>
            )}
            {outcome === "allowed" && watchedEffect && <Pill tone="outline">{WOULD[watchedEffect]}</Pill>}
            {t.status === "error" && <Pill tone="bad">Error</Pill>}
          </>
        }
        actions={
          <>
            {(outcome === "blocked" || outcome === "held") && denied && t.agent && (
              <Link className="k-btn" href={href(`/app/projects/${encodeURIComponent(t.agent)}`, { view: "access", grant: denied.decision.tool })}>
                Allow this tool
              </Link>
            )}
            {(outcome === "blocked" || outcome === "held") && !denied && primaryRule && (
              <Link className="k-btn" href={href(`/app/policies/rules/${encodeURIComponent(primaryRule.rule_id)}`, { tab: "tune" })}>
                Adjust rule
              </Link>
            )}
            <Link className="k-btn-primary" href={href("/app/policies/new", { from: "run", run: id })}>
              Prevent this
            </Link>
          </>
        }
      />
      <Meta
        items={[
          ["Agent", t.agent ? <Link href={`/app/projects/${encodeURIComponent(t.agent)}`}>{t.agent_name || t.agent}</Link> : "—"],
          ["When", when(t.started_at)],
          ["Environment", t.environment],
          ["Checks", `${Math.round(duration)} ms`],
          ...(t.model ? ([["Model", t.model]] as [string, string][]) : []),
          ...(t.cost_usd ? ([["Cost", money(t.cost_usd)]] as [string, string][]) : []),
          // The issue(s) this run raised, linked: the run page used to stop at the verdict.
          ...((d.findings || []).length
            ? ([
                [
                  (d.findings || []).length === 1 ? "Issue" : "Issues",
                  <span key="issues">
                    {(d.findings || []).map((f: any, i: number) => (
                      <span key={f.id}>
                        {i > 0 && ", "}
                        <Link href={`/app/findings/${encodeURIComponent(f.id)}`}>{sentence(withAgentNames(f.title, names))}</Link>
                      </span>
                    ))}
                  </span>,
                ],
              ] as [string, ReactNode][])
            : []),
        ]}
      />
      <div style={{ height: 14 }} />
      <NoticeToast notice={sp.review_notice} error={sp.review_error} />
      <Tabs items={TABS.map((x) => ({ ...x, href: tabHref(x.key) }))} active={tab} />

      {tab === "summary" && <Summary decisions={decisions} />}
      {tab === "steps" && <Steps spans={d.spans || []} />}
      {tab === "checks" && <Checks runs={d.detector_runs || []} runId={id} />}
      {tab === "origin" && <Origin decisions={decisions} taint={d.taint || []} />}
      {tab === "raw" && (
        <Card>
          <pre className="k-mono" style={{ margin: 0, overflowX: "auto", whiteSpace: "pre-wrap" }}>
            {JSON.stringify({ trace: t, decisions }, null, 2)}
          </pre>
        </Card>
      )}
    </>
  );
}

function Summary({ decisions }: { decisions: any[] }) {
  if (!decisions.length) return <Card><Empty>No checks ran on this request.</Empty></Card>;
  return (
    <>
      {decisions.map((x) => {
        const rules: any[] = x.rules_fired || [];
        return (
          <Card
            key={x.id}
            title={
              <>
                {SURFACES[x.surface] || x.surface}
                {x.tool && <span className="k-mono k-muted">{x.tool}</span>}
              </>
            }
            action={
              <>
                <OutcomePill outcome={outcomeOf(x.verdict)} />
                {x.approval_id && <ApprovalLink id={x.approval_id} approval={x.approval} />}
              </>
            }
            flush
          >
            {rules.length ? (
              <table className="k-table">
                <tbody>
                  {rules.map((r) => (
                    <tr key={r.rule_id}>
                      <td>
                        <Link className="k-name" href={`/app/policies/rules/${encodeURIComponent(r.rule_id)}`}>
                          {ruleTitle(r.rule_id, r.reason)}
                        </Link>
                        <span className="sub">{plainReason(r, x)}</span>
                      </td>
                      <td className="tight"><ActionPill effect={r.effect} /></td>
                      <td className="tight"><ModePill mode={r.mode} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>No rule triggered.</Empty>
            )}
          </Card>
        );
      })}
    </>
  );
}

function Steps({ spans }: { spans: any[] }) {
  if (!spans.length) return <Card><Empty>No steps recorded.</Empty></Card>;
  const max = Math.max(1, ...spans.map((s) => s.duration_ms || 0));
  return (
    <Card flush>
      <table className="k-table">
        <thead>
          <tr>
            <th>Step</th>
            <th>Kind</th>
            <th style={{ width: "35%" }}>Time</th>
            <th className="num">Time (ms)</th>
          </tr>
        </thead>
        <tbody>
          {spans.map((s) => (
            <tr key={s.id}>
              <td>
                {s.name}
                {s.error && <span className="sub" style={{ color: "var(--bad)" }}>{s.error}</span>}
              </td>
              <td className="muted">{s.kind}</td>
              <td>
                <span className="k-stack">
                  <span className={s.status === "error" ? "k-seg-blocked" : "k-seg-solid"} style={{ width: `${((s.duration_ms || 0) / max) * 100}%` }} />
                </span>
              </td>
              <td className="num muted">{(s.duration_ms || 0).toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

async function Checks({ runs, runId }: { runs: any[]; runId: string }) {
  if (!runs.length) return <Card><Empty>No detectors ran.</Empty></Card>;
  // What was already marked on this run, newest first: the button shows it stuck.
  const marks = await safeApi<any>(`/api/guardrails/feedback?trace_id=${encodeURIComponent(runId)}&limit=200`, { feedback: [] });
  const markOf = (decision: string, detector: string): string | undefined =>
    (marks.feedback || []).find((f: any) => f.decision_id === decision && f.detector_key === detector)?.label;
  return (
    <Card flush>
      <table className="k-table">
        <thead>
          <tr>
            <th>Detector</th>
            <th>Where</th>
            <th>Found</th>
            <th className="num">Time (ms)</th>
            <th className="tight">Was it right?</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id}>
              <td>{detectorName(r.detector)}</td>
              <td className="muted">{SURFACES[r.surface] || r.surface}</td>
              <td>
                {r.findings?.length ? (
                  r.findings.map((f: any, i: number) => (
                    <span key={i} className="sub" style={{ color: "var(--text)" }}>
                      {f.entity_type} <span className="k-muted k-mono">{f.sample}</span>
                    </span>
                  ))
                ) : (
                  <span className="k-muted">—</span>
                )}
              </td>
              <td className="num muted">{(r.duration_ms || 0).toFixed(2)}</td>
              <td className="tight">
                {r.decision_id && r.findings?.length ? (
                  <span className="k-pills">
                    {(["true_positive", "false_positive"] as const).map((label) => (
                      <form key={label} action="/api/guardrails/feedback" method="POST">
                        <input type="hidden" name="decision_id" value={r.decision_id} />
                        <input type="hidden" name="detector_key" value={r.detector} />
                        {r.findings.length === 1 && <input type="hidden" name="entity_type" value={r.findings[0].entity_type} />}
                        <input type="hidden" name="label" value={label} />
                        <input type="hidden" name="return_to" value={`/app/traces/${runId}?tab=checks`} />
                        {markOf(r.decision_id, r.detector) === label ? (
                          <button type="submit" className="k-btn" aria-pressed="true" disabled>
                            {label === "true_positive" ? "Marked correct" : "Marked wrong"}
                          </button>
                        ) : (
                          <button type="submit" className="k-btn-ghost" aria-pressed="false">
                            {label === "true_positive" ? "Correct" : "Wrong"}
                          </button>
                        )}
                      </form>
                    ))}
                  </span>
                ) : (
                  <span className="k-muted">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function Origin({ decisions, taint }: { decisions: any[]; taint: any[] }) {
  const withArgs = decisions.filter((x) => x.taint?.arguments && Object.keys(x.taint.arguments).length);
  if (!withArgs.length && !taint.length) return <Card><Empty>No tool arguments to trace.</Empty></Card>;
  return (
    <>
      {withArgs.map((x) => {
        const snapshot = x.taint.arguments_snapshot || {};
        const maxTaint = x.taint.capability?.max_taint;
        return (
          <Card key={x.id} title={<span className="k-mono">{x.tool}</span>} action={maxTaint ? <span>Trusts: {trustLabel(maxTaint)}</span> : undefined} flush>
            <table className="k-table">
              <thead>
                <tr>
                  <th>Argument</th>
                  <th>Value</th>
                  <th>Came from</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(x.taint.arguments).map(([arg, source]: [string, any]) => {
                  const untrusted = (x.taint.untrusted_paths || []).includes(arg) && source !== "user";
                  return (
                    <tr key={arg}>
                      <td className="k-mono">{arg}</td>
                      <td className="k-mono muted">{snapshot[arg] === undefined ? "—" : String(JSON.stringify(snapshot[arg]))}</td>
                      <td>
                        <Pill tone={untrusted ? "held" : "neutral"}>{trustLabel(source)}</Pill>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
        );
      })}
    </>
  );
}

/** The approval a decision filed or redeemed, linked, with what became of it. */
function ApprovalLink({ id, approval }: { id: string; approval?: any }) {
  const answered = approvalOutcome(approval);
  return (
    <Link href={`/app/approvals/${encodeURIComponent(id)}`} title={approval?.rationale || undefined}>
      {answered ? <Pill tone={answered.tone}>{answered.label}</Pill> : approval?.status === "pending" ? "Waiting for approval" : "Approval"}
    </Link>
  );
}
