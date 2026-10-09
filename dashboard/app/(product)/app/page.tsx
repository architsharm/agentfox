import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { safeApi } from "@/lib/product/api";
import { Card, Dot, Empty, Grid, Header, Kpi, Pill, SeverityPill, StackBar, TimeChart, ago, href, num, pctOf } from "@/components/kit";
import { Countdown } from "@/components/product/Countdown";
import { SetupProgress } from "@/components/product/home/SetupProgress";
import { runsHref } from "@/lib/product/observe";
import { activeRange } from "@/lib/product/range";
import { RANGE_WORDS, severityRank } from "@/lib/product/vocab";

// `appPageMetadata`, not a literal: it also clears the canonical URL, so this page
// does not declare itself a duplicate of the marketing home page.
export const metadata: Metadata = appPageMetadata("Home");
export const dynamic = "force-dynamic";

type SP = { review_notice?: string; review_error?: string };

/**
 * Home answers one question: does anything need me? Then, at a glance, how the
 * week went and which agents did it. Everything else is one click away.
 */
export default async function Home({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  // The week, or the smallest window that holds the latest traffic in a quiet workspace.
  const { range, last } = await activeRange();
  const f = { range };
  const [onboarding, summary, byAgent, agents, approvals, findings, policies] = await Promise.all([
    safeApi<any>("/api/onboarding", null),
    safeApi<any>(`/api/metrics/summary?range=${range}`, null),
    safeApi<any>(`/api/metrics/breakdown?dim=agent&range=${range}`, { rows: [] }),
    safeApi<any>("/api/agents", { agents: [] }),
    safeApi<any>("/api/approvals?status=pending", { approvals: [] }),
    safeApi<any>("/api/findings?status=open&limit=200", { findings: [] }),
    safeApi<any>("/api/policies", { policies: [] }),
  ]);

  const t = summary?.totals || {};
  const p = summary?.previous || {};
  const b = summary?.buckets || [];
  const pending: any[] = approvals.approvals || [];
  const urgent = (findings.findings || [])
    .filter((x: any) => x.severity === "critical" || x.severity === "high")
    .sort((a: any, c: any) => severityRank(a.severity) - severityRank(c.severity))
    .slice(0, 4);
  const agentName: Record<string, string> = Object.fromEntries((agents.agents || []).map((a: any) => [a.id, a.name || a.slug]));
  const watching = (policies.policies || []).filter((x: any) => x.mode === "observe" && x.rules > 0);
  const usage: Record<string, any> = Object.fromEntries((byAgent.rows || []).map((r: any) => [r.key, r]));
  const live = (agents.agents || []).filter((a: any) => a.status !== "draft");
  const max = Math.max(1, ...Object.values(usage).map((r: any) => r.requests));
  const noTraffic = !last;

  return (
    <>
      <Header title="Home" />
      {sp.review_notice && <div className="note-panel">Request {sp.review_notice}.</div>}
      {sp.review_error && <div className="error">{sp.review_error}</div>}
      {onboarding && <SetupProgress onboarding={onboarding} />}

      <Card
        title={pending.length + urgent.length ? `Needs you · ${pending.length + urgent.length}` : "Needs you"}
        action={<Link href="/app/findings">All issues</Link>}
        flush
      >
        {pending.length + urgent.length === 0 ? (
          <Empty>All clear.</Empty>
        ) : (
          <ul className="k-list">
            {pending.slice(0, 3).map((a) => (
              <li key={a.id}>
                <div className="k-list-main">
                  <span>
                    <strong>{agentName[a.agent_id] || "An agent"}</strong> wants to run <span className="k-mono">{a.tool}</span>
                  </span>
                  <span className="muted">
                    {Object.entries(a.arguments || {})
                      .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
                      .join(" · ")}
                    {" · expires "}
                    <Countdown at={a.expires_at} />
                  </span>
                </div>
                <div className="k-list-end">
                  <form action={`/api/approvals/${a.id}/deny`} method="POST">
                    <input type="hidden" name="return_to" value="/app" />
                    <button type="submit" className="k-btn-ghost">Deny</button>
                  </form>
                  <form action={`/api/approvals/${a.id}/approve`} method="POST">
                    <input type="hidden" name="return_to" value="/app" />
                    <button type="submit" className="k-btn-primary">Approve</button>
                  </form>
                </div>
              </li>
            ))}
            {pending.length > 3 && (
              <li>
                <Link href="/app/approvals">{pending.length - 3} more approvals waiting</Link>
              </li>
            )}
            {urgent.map((x: any) => (
              <li key={x.id}>
                <div className="k-list-main">
                  <Link href={`/app/findings/${x.id}`}>{x.title}</Link>
                  <span className="muted">{x.agent_slug || ""}</span>
                </div>
                <SeverityPill value={x.severity} />
              </li>
            ))}
          </ul>
        )}
      </Card>

      {noTraffic ? (
        <Card>
          <Empty action={<Link href="/app/start" className="k-btn-primary">Connect an agent</Link>}>No requests yet.</Empty>
        </Card>
      ) : (
        <>
          <Grid cols={4}>
            <Kpi label={`Requests · ${RANGE_WORDS[range]}`} value={num(t.requests)} current={t.requests} prev={p.requests} better="none" href={href("/app/observe", { range })} spark={b.map((x: any) => x.allowed + x.masked + x.held + x.blocked)} />
            <Kpi label="Blocked" value={num(t.blocked)} current={t.blocked} prev={p.blocked} href={runsHref(f, { outcome: "blocked" })} spark={b.map((x: any) => x.blocked)} />
            <Kpi label="Held for a person" value={num(t.held)} current={t.held} prev={p.held} href={runsHref(f, { outcome: "held" })} spark={b.map((x: any) => x.held)} />
            <Kpi label="Errors" value={num(t.errors)} current={t.errors} prev={p.errors} tone={t.errors ? "bad" : undefined} href={runsHref(f, { errors: true })} />
          </Grid>
          <Grid cols={2}>
            <Card title="Requests" action={<Link href="/app/observe">Observe</Link>}>
              <TimeChart buckets={b} bucketSeconds={summary.bucket_seconds} height={120} linkFor={(start, end) => runsHref(f, { start, end })} />
            </Card>
            <Card title="Agents" action={<Link href="/app/agents">All agents</Link>} flush>
              <table className="k-table">
                <tbody>
                  {live.slice(0, 6).map((a: any) => {
                    const u = usage[a.slug] || { requests: 0, held: 0, blocked: 0 };
                    return (
                      <tr key={a.slug}>
                        <td>
                          <span className="k-pills">
                            <Dot tone={a.control_state && a.control_state !== "active" ? "bad" : a.last_seen_at ? "ok" : "idle"} />
                            <Link className="k-name" href={`/app/agents/${encodeURIComponent(a.slug)}`}>{a.name || a.slug}</Link>
                            {!a.registered && <Pill tone="bad">Unregistered</Pill>}
                          </span>
                        </td>
                        <td style={{ width: "34%" }}><StackBar s={u} total={u.requests} scale={max} /></td>
                        <td className="num tight">{num(u.requests)}</td>
                        <td className="num tight muted">{u.requests ? pctOf(u.held + u.blocked, u.requests) : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Card>
          </Grid>
        </>
      )}

      {watching.length > 0 && (
        <div className="protect-banner">
          <span>
            <strong>{watching.length === 1 ? "1 pack is" : `${watching.length} packs are`} only watching</strong>
            <span className="k-muted"> · {watching.map((x: any) => x.name).join(", ")}</span>
          </span>
          <Link href="/app/policies" className="k-btn-primary">Review</Link>
        </div>
      )}
      {live.length > 0 && <div className="k-muted" style={{ fontSize: "var(--t-micro)", marginTop: 14 }}>Last activity {ago(live.map((a: any) => a.last_seen_at).filter(Boolean).sort().pop())}</div>}
    </>
  );
}
