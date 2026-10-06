import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { api, safeApi, apiErrorProps } from "@/lib/product/api";
import { ApiDown, Panel, ts } from "@/components/ui";
import { Breadcrumbs } from "@/components/product/Breadcrumbs";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata("Evaluation suite");

export const dynamic = "force-dynamic";

export default async function SuiteDetail({
  params,
  searchParams,
}: {
  params: Promise<{ key: string }>;
  searchParams: Promise<{ review_error?: string }>;
}) {
  const { key } = await params;
  const { review_error } = await searchParams;
  let suite: any, runs: any, scorers: any, agents: any;
  try {
    [suite, runs, scorers, agents] = await Promise.all([
      api(`/api/eval/suites/${key}`),
      api(`/api/eval/runs?suite=${key}&limit=20`),
      safeApi("/api/eval/scorers", { scorers: [] }),
      safeApi("/api/agents", { agents: [] }),
    ]);
  } catch (e: any) {
    return (
      <>
        <h1>Suite</h1>
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }

  return (
    <>
      <Breadcrumbs crumbs={[{ label: "Evaluation", href: "/app/evals" }]} />
      <h1>{suite.name || suite.key}</h1>
      <p className="sub">{suite.description || "No description."}</p>
      {review_error && <div className="error">{review_error}</div>}

      <h2>Cases ({suite.cases.length})</h2>
      {suite.cases.length === 0 ? (
        <div className="hero empty" style={{ marginBottom: 20 }}>
          <div className="hero-title">No cases yet</div>
          <p>
            A suite with no cases has nothing to run. Add one below, or — the faster
            path once you have real traffic — promote an actual production trace
            into a regression case from its ID (find one on{" "}
            <Link href="/app/traces">Traces</Link>).
          </p>
        </div>
      ) : (
        <div className="panel scroll-x" style={{ marginBottom: 16 }}>
          <table>
            <thead>
              <tr><th>prompt</th><th>expected</th><th>split</th><th>source</th></tr>
            </thead>
            <tbody>
              {suite.cases.map((c: any) => (
                <tr key={c.id} id={`case-${c.id}`}>
                  <td className="small wrap" style={{ maxWidth: 320 }}>{c.input?.prompt || "—"}</td>
                  <td className="small wrap muted" style={{ maxWidth: 260 }}>{c.expected?.goal || "—"}</td>
                  <td className="small muted">{c.split}</td>
                  <td className="small muted">
                    {c.source_trace_id ? (
                      <Link href={`/app/traces/${c.source_trace_id}`} className="mono">{c.source_trace_id}</Link>
                    ) : "hand-authored"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid2" style={{ marginBottom: 24 }}>
        <Panel title="Add a case">
          <form action={`/api/eval/suites/${key}/cases`} method="POST" className="body stack">
            <div>
              <label className="small muted" style={{ display: "block", marginBottom: 4 }}>Prompt</label>
              <textarea
                name="prompt" required rows={2}
                style={{ width: "100%", padding: "6px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
              />
            </div>
            <div>
              <label className="small muted" style={{ display: "block", marginBottom: 4 }}>Expected goal (optional — what a correct answer accomplishes)</label>
              <textarea
                name="goal" rows={2}
                style={{ width: "100%", padding: "6px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
              />
            </div>
            <div>
              <button type="submit" className="btn-primary">Add case</button>
            </div>
          </form>
        </Panel>

        <Panel title="Promote a trace" note="turn a real production execution into a regression case">
          <form action={`/api/eval/suites/${key}/promote`} method="POST" className="body row" style={{ gap: 6 }}>
            <input
              type="text" name="trace_id" placeholder="trc_..." required
              style={{ flex: 1, padding: "6px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "var(--mono)" }}
            />
            <button type="submit" className="btn-scan">Promote</button>
          </form>
        </Panel>
      </div>

      <h2>Run this suite</h2>
      <Panel title="New run">
        <form action="/api/eval/runs" method="POST" className="body stack">
          <input type="hidden" name="suite" value={key} />
          <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
            <div>
              <label className="small muted" style={{ display: "block", marginBottom: 4 }}>Agent (optional — fits reliability envelope if set)</label>
              <select
                name="agent"
                style={{ padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
              >
                <option value="">— none —</option>
                {(agents.agents || []).map((a: any) => (
                  <option key={a.slug} value={a.slug}>{a.slug}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="small muted" style={{ display: "block", marginBottom: 4 }}>Provider</label>
              <input
                type="text" name="provider" defaultValue="echo"
                style={{ width: 100, padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
              />
            </div>
            <div>
              <label className="small muted" style={{ display: "block", marginBottom: 4 }}>Model</label>
              <input
                type="text" name="model" defaultValue="echo-1"
                style={{ width: 100, padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
              />
            </div>
          </div>
          <div>
            <label className="small muted" style={{ display: "block", marginBottom: 4 }}>Scorers (none selected = engine default set)</label>
            <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
              {(scorers.scorers || []).map((s: any) => (
                <label key={s.key} className="small" style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <input type="checkbox" name="scorers" value={s.key} />
                  {s.key}
                </label>
              ))}
            </div>
          </div>
          <div>
            <button type="submit" className="btn-primary" disabled={suite.cases.length === 0}>
              {suite.cases.length === 0 ? "Add a case first" : "Run"}
            </button>
          </div>
        </form>
      </Panel>

      <h2>Runs</h2>
      <div className="panel scroll-x">
        {runs.runs.length === 0 ? (
          <div className="body muted small">No runs yet.</div>
        ) : (
          <table>
            <thead>
              <tr><th>run</th><th>runner</th><th>status</th><th className="num">cases</th><th>when</th></tr>
            </thead>
            <tbody>
              {runs.runs.map((r: any) => (
                <tr key={r.id}>
                  <td><Link href={`/app/evals/${key}/runs/${r.id}`} className="mono small">{r.id}</Link></td>
                  <td className="small muted">{r.runner}</td>
                  <td>
                    <span className={`tag ${r.status === "completed" ? "ok" : r.status === "failed" ? "bad" : "warn"}`}>
                      {r.status}
                    </span>
                  </td>
                  <td className="num small">{r.summary?.cases ?? "—"}</td>
                  <td className="small muted">{ts(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
