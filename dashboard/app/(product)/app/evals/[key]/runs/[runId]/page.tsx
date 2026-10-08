import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { ApiError, api, safeApi, apiErrorProps } from "@/lib/product/api";
import { ApiDown, InfoTip, NotFound, Panel, ts } from "@/components/ui";
import { Header } from "@/components/kit";
import { Modal } from "@/components/product/Modal";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata("Evaluation run");

export const dynamic = "force-dynamic";

export default async function RunDetail({
  params,
  searchParams,
}: {
  params: Promise<{ key: string; runId: string }>;
  searchParams: Promise<{ review_error?: string; review_notice?: string }>;
}) {
  const { key, runId } = await params;
  const { review_error, review_notice } = await searchParams;
  let run: any;
  try {
    run = await api(`/api/eval/runs/${runId}`);
  } catch (e: any) {
    return (
      <>
        <h1>Run</h1>
        {e instanceof ApiError && e.status === 404 ? (
          <NotFound what="run" detail={runId} back={{ href: `/app/evals/${key}`, label: key }} />
        ) : (
          <ApiDown {...apiErrorProps(e)} />
        )}
      </>
    );
  }

  // P4 — borderline results (score near the scorer's own threshold, or scorers
  // disagreeing on the same case) worth a human's attention. Best-effort: a run
  // page must still render its scores if this queue fails.
  const queue = await safeApi(
    `/api/eval/annotations/queue?run_id=${encodeURIComponent(runId)}&limit=200`,
    { results: [] },
  );
  const needsReview: any[] = queue.results || [];
  const redirectTo = `/app/evals/${key}/runs/${runId}`;

  return (
    <>
      <Header back={{ href: `/app/evals/${key}`, label: key }} title="Test run" />
      <p className="sub">
        <Link href={`/app/evals/${key}`}>{key}</Link>{" "}
        <span className="mono small muted">{run.runner}</span>{" "}
        <span className={`tag ${run.status === "completed" ? "ok" : run.status === "failed" ? "bad" : "warn"}`}>
          {run.status}
        </span>{" "}
        <span className="small muted">{ts(run.created_at)}</span>
      </p>

      {review_error && <div className="error">{review_error}</div>}
      {review_notice && <div className="note-panel">{review_notice}</div>}

      {run.summary?.scorers && (
        <>
          <h2>Summary</h2>
          <Panel title={`${run.mode} · ${run.summary.cases} cases`}>
            <table>
              <thead>
                <tr><th>scorer</th><th className="num">mean</th><th className="num">min</th><th className="num">max</th><th className="num">pass rate</th></tr>
              </thead>
              <tbody>
                {Object.entries(run.summary.scorers).map(([k, v]: any) => (
                  <tr key={k}>
                    <td className="mono small">{k}</td>
                    <td className="num">{v.mean}</td>
                    <td className="num muted">{v.min}</td>
                    <td className="num muted">{v.max}</td>
                    <td className="num">
                      {v.pass_rate === null ? "—" : (
                        <span className={`tag ${v.pass_rate >= 0.9 ? "ok" : v.pass_rate >= 0.7 ? "warn" : "bad"}`}>
                          {Math.round(v.pass_rate * 100)}%
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}

      {needsReview.length > 0 && (
        <>
          <h2>
            Needs human review
            <InfoTip text="Score within 0.1 of the scorer's own pass/fail threshold, or scorers disagreeing on the same case — both are the shape a human should look at rather than trust blindly, not a finding-in-itself the way a failed scorer already is." />
          </h2>
          <div className="panel scroll-x" style={{ marginBottom: 20 }}>
            <table>
              <thead>
                <tr><th>case</th><th>scorer</th><th className="num">score</th><th>passed</th><th></th></tr>
              </thead>
              <tbody>
                {needsReview.map((r: any) => (
                  <tr key={r.id}>
                    <td className="mono small">
                      {r.case_id ? (
                        <Link href={`/app/evals/${key}#case-${r.case_id}`}>{r.case_id}</Link>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="small muted">{r.scorer}</td>
                    <td className="num small">{r.score}</td>
                    <td>
                      <span className={`tag ${r.passed ? "ok" : "bad"}`}>{r.passed ? "pass" : "fail"}</span>
                    </td>
                    <td className="small" style={{ textAlign: "right" }}>
                      {r.annotated ? (
                        <span className="tag ok">reviewed</span>
                      ) : (
                        <Modal trigger="Annotate" triggerClassName="chip" title="Record a human judgment">
                          <p className="small muted" style={{ marginTop: 0, marginBottom: 12 }}>
                            Case <span className="mono">{r.case_id || "—"}</span>,{" "}
                            scorer <span className="mono">{r.scorer}</span>, score{" "}
                            <span className="mono">{r.score}</span> ({r.passed ? "passed" : "failed"}).
                            Requires a note — an unrecorded verdict is how a real disagreement
                            about scorer correctness disappears without anyone having looked.
                          </p>
                          <form
                            action={`/api/eval/results/${r.id}/annotate`}
                            method="POST"
                            className="stack"
                          >
                            <input type="hidden" name="redirect_to" value={redirectTo} />
                            <div>
                              <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
                                Was the scorer right?
                              </label>
                              <select
                                name="verdict"
                                defaultValue="agree"
                                style={{ width: "100%", padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
                              >
                                <option value="agree">Agree — the score is right</option>
                                <option value="disagree">Disagree — the score is wrong</option>
                              </select>
                            </div>
                            <div>
                              <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
                                Note (required)
                              </label>
                              <textarea
                                name="note"
                                required
                                rows={3}
                                style={{ width: "100%", padding: "6px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
                              />
                            </div>
                            <div>
                              <button type="submit" className="btn-primary">Save annotation</button>
                            </div>
                          </form>
                        </Modal>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>Case results</h2>
      <div className="panel scroll-x">
        {(run.results || []).length === 0 ? (
          <div className="body muted small">No results recorded.</div>
        ) : (
          <table>
            <thead>
              <tr><th>case</th><th>scorer</th><th className="num">score</th><th>passed</th><th>output</th></tr>
            </thead>
            <tbody>
              {run.results.map((r: any, i: number) => (
                <tr key={i}>
                  <td className="mono small">
                    {r.case_id ? (
                      <Link href={`/app/evals/${key}#case-${r.case_id}`}>{r.case_id}</Link>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="small muted">{r.scorer}</td>
                  <td className="num small">{r.score}</td>
                  <td>
                    <span className={`tag ${r.passed ? "ok" : "bad"}`}>{r.passed ? "pass" : "fail"}</span>
                  </td>
                  <td className="small wrap muted" style={{ maxWidth: 300 }}>
                    {typeof r.output === "string" ? r.output : JSON.stringify(r.output)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
