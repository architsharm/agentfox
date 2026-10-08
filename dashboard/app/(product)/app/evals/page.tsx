import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { api, safeApi, apiErrorProps } from "@/lib/product/api";
import { AgentLink, ApiDown, Empty, InfoTip, InventoryStrip, Panel, ts } from "@/components/ui";

/** Scores are ratios; two decimal places is all any of them carry. */
function score(v: unknown): string {
  return typeof v === "number" && Number.isFinite(v) ? v.toFixed(2) : "—";
}
import { Header } from "@/components/kit";
import { Explainer } from "@/components/product/Explainer";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata(
  "Test",
  "Pre-release test suites, red-team runs and the drift between them.",
);

export const dynamic = "force-dynamic";

export default async function Evals({
  searchParams,
}: {
  searchParams: Promise<{ review_error?: string; review_notice?: string; drift_agent?: string; drift_scorer?: string }>;
}) {
  const { review_error, review_notice, drift_agent, drift_scorer } = await searchParams;
  let suites: any, runs: any, scorers: any, campaigns: any, slos: any, agents: any;
  try {
    [suites, runs, scorers, campaigns, slos, agents] = await Promise.all([
      api("/api/eval/suites"),
      api("/api/eval/runs?limit=20"),
      safeApi("/api/eval/scorers", { scorers: [], runners: {} }),
      safeApi("/api/redteam/campaigns", { campaigns: [] }),
      safeApi("/api/eval/slos", { slos: [] }),
      safeApi("/api/agents", { agents: [] }),
    ]);
  } catch (e: any) {
    return (
      <>
        <h1>Evaluation</h1>
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }

  let drift: any = null;
  if (drift_agent && drift_scorer) {
    drift = await safeApi(
      `/api/eval/drift?agent=${encodeURIComponent(drift_agent)}&scorer=${encodeURIComponent(drift_scorer)}`,
      null,
    );
  }

  const latest = runs.runs[0];
  const latestSuite = latest
    ? suites.suites.find((s: any) => s.id === latest.suite_id)
    : null;

  return (
    <>
      <Header back={{ href: "/app/test", label: "Test" }} title="Evaluation details" />

      {/* Four tiles for four inventory counts — none of them is a number that
          wants a person, they are just what exists. A strip says the same thing
          without claiming the top of the page. */}
      <InventoryStrip
        items={[
          { n: suites.suites.length, label: "suites", href: "/app/evals" },
          { n: runs.runs.length, label: "recent runs", href: "/app/evals" },
          { n: scorers.scorers.length, label: "scorers", href: "/app/evals" },
          { n: campaigns.campaigns.length, label: "red-team campaigns", href: "/app/evals" },
        ]}
      />

      {review_error && <div className="error">{review_error}</div>}
      {review_notice && <div className="note-panel">{review_notice}</div>}

      {latest?.summary?.scorers && (
        <>
          <h2>Latest run</h2>
          <Panel
            title={`${latest.runner} · ${latest.mode} · ${latest.summary.cases} cases`}
            note={ts(latest.created_at)}
          >
            <table>
              <thead>
                <tr><th>scorer</th><th className="num">mean</th><th className="num">min</th><th className="num">max</th><th className="num">pass rate</th></tr>
              </thead>
              <tbody>
                {Object.entries(latest.summary.scorers).map(([k, v]: any) => (
                  <tr key={k}>
                    <td className="mono small">{k}</td>
                    {/* Raw floats arrive at whatever precision the scorer produced,
                        so a column read 0.6, 0.73, 0.2, 0.2005, 0.8 — five different
                        decimal lengths in five rows, which makes a scored column look
                        unreviewed. Two places for everything, and scores are a ratio
                        so two places is all any of them carry. */}
                    <td className="num">{score(v.mean)}</td>
                    <td className="num muted">{score(v.min)}</td>
                    <td className="num muted">{score(v.max)}</td>
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
          {latest.summary.failing_count > 0 && (
            <p className="small" style={{ marginTop: 10 }}>
              <span className="tag bad">{latest.summary.failing_count}</span>{" "}
              <span className="muted">
                case(s) flagged.{" "}
                {latestSuite ? (
                  <>
                    <Link href={`/app/evals/${latestSuite.key}`}>Promote a production failure</Link>{" "}
                    into this suite as a regression case.
                  </>
                ) : (
                  "Promote a production failure into a suite as a regression case."
                )}
              </span>
            </p>
          )}
        </>
      )}

      <h2>
        Reliability &amp; SLOs
        <InfoTip text="A declared reliability target for one agent and scorer pair, such as '95% of sampled production answers stay grounded, measured weekly'. Error budget tracks how much room is left before that target is breached." />
      </h2>
      <div className="panel">
        {(slos.slos || []).length === 0 ? (
          <div className="body muted small">
            No reliability objectives declared yet. Declare one below and this table
            shows how much room is left before you breach it.
            <InfoTip text="Without one, a falling score is something you notice rather than something that is tracked." />
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>agent</th>
                <th>scorer</th>
                <th>objective</th>
                <th className="num">target</th>
                <th className="num">attainment</th>
                <th className="num">error budget</th>
                <th>drift</th>
              </tr>
            </thead>
            <tbody>
              {slos.slos.map((s: any) => (
                <tr key={s.slo_id}>
                  <td className="small"><AgentLink slug={s.agent} agents={agents.agents || []} /></td>
                  <td className="mono small">{s.scorer}</td>
                  <td className="small wrap muted" style={{ maxWidth: 260 }}>{s.objective || "—"}</td>
                  <td className="num small">{s.target ?? "—"}</td>
                  <td className="num small">
                    {s.attainment === undefined ? (
                      <span className="muted">no data</span>
                    ) : (
                      <span className={`tag ${s.status === "burned" ? "bad" : "ok"}`}>
                        {Math.round(s.attainment * 100)}%
                      </span>
                    )}
                  </td>
                  <td className="num small">
                    {s.error_budget_remaining === undefined ? (
                      "—"
                    ) : (
                      <span className={s.error_budget_remaining > 0 ? "" : "tag bad"}>
                        {Math.round(s.error_budget_remaining * 100)}%
                      </span>
                    )}
                  </td>
                  <td className="small">
                    <Link href={`/app/evals?drift_agent=${encodeURIComponent(s.agent)}&drift_scorer=${encodeURIComponent(s.scorer)}#drift`}>
                      check drift →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="body" style={{ borderTop: "1px solid var(--border)" }}>
          <form action="/api/eval/slos" method="POST" className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            <select
              name="agent" required aria-label="Agent this SLO applies to"
              style={{ padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
            >
              <option value="">agent…</option>
              {(agents.agents || []).map((a: any) => (
                <option key={a.slug} value={a.slug}>{a.name || a.slug}</option>
              ))}
            </select>
            <select
              name="scorer" required aria-label="Scorer this SLO measures"
              style={{ padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
            >
              <option value="">scorer…</option>
              {(scorers.scorers || []).map((s: any) => (
                <option key={s.key} value={s.key}>{s.key}</option>
              ))}
            </select>
            <input
              type="text" name="objective" placeholder="objective, e.g. '95% of answers stay grounded'"
              style={{ flex: 1, minWidth: 220, padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
            />
            <select
              name="window" defaultValue="7d" aria-label="Measurement window"
              style={{ padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
            >
              <option value="1d">1 day</option>
              <option value="7d">7 days</option>
              <option value="30d">30 days</option>
            </select>
            <input
              type="number" name="target" aria-label="Target, between 0 and 1" step="0.01" min="0" max="1" defaultValue="0.9" required
              style={{ width: 80, padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
            />
            <button type="submit" className="btn-primary">Declare SLO</button>
          </form>
        </div>
      </div>

      <h2>
        Score real production traffic
        <InfoTip text="Runs the scorers an offline suite uses (groundedness, task completion, silent failure) against traces already recorded for an agent: no synthetic model call, no suite to author first. An SLO's attainment above is measured from this." />
      </h2>
      <p className="sub">
        Fastest way to get a real number: sample an agent that has traffic, rather than
        writing cases first.
      </p>
      <form action="/api/eval/online" method="POST" className="row" style={{ gap: 6, marginBottom: 24, flexWrap: "wrap" }}>
        <select
          name="agent" required defaultValue="" aria-label="Agent whose traffic to sample"
          style={{ padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
        >
          <option value="" disabled>choose an agent…</option>
          {(agents.agents || []).map((a: any) => (
            <option key={a.slug} value={a.slug}>{a.name || a.slug}</option>
          ))}
        </select>
        <select
          name="since_days" defaultValue="30" aria-label="How far back to sample"
          style={{ padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
        >
          <option value="1">last 1 day</option>
          <option value="7">last 7 days</option>
          <option value="30">last 30 days</option>
          <option value="90">last 90 days</option>
        </select>
        <button type="submit" className="btn-scan">Sample &amp; score</button>
      </form>

      {drift_agent && drift_scorer && (
        <div id="drift" className={`note-panel ${drift?.drifted ? "" : ""}`} style={{ borderLeftColor: drift?.drifted ? "var(--bad)" : "var(--accent)" }}>
          <strong>
            Drift check: {drift_agent} / {drift_scorer}
            <InfoTip text="Whether this scorer's results have shifted from its own baseline, measured by PSI (population stability index), a standard statistic for how much a distribution has moved. Above ~0.1 usually means worth a look; above ~0.25 usually means something real changed." />
          </strong>
          {!drift || drift.drifted === null ? (
            <div>
              Not enough online samples in the current and baseline windows. Sample
              production traffic with <code className="mono">POST /api/eval/online</code> first.
            </div>
          ) : (
            <div>
              {drift.drifted ? (
                <>Drifted ({drift.band}) — shift score {drift.psi?.toFixed(3)}, mean moved from{" "}
                {drift.mean_baseline?.toFixed(3)} to {drift.mean_current?.toFixed(3)}.</>
              ) : (
                <>No significant drift — shift score {drift.psi?.toFixed(3)}, mean {drift.mean_current?.toFixed(3)}{" "}
                (baseline {drift.mean_baseline?.toFixed(3)}).</>
              )}
              {" "}Compared {drift.n_current} recent sample(s) against {drift.n_baseline} baseline sample(s).
            </div>
          )}
        </div>
      )}

      <h2>Suites</h2>
      <div className="panel">
        {/* Said once, inside the panel where the missing rows are. A paragraph
            above an empty table reads as a caption for something, and then the
            something is a bare column header. */}
        {suites.suites.length === 0 ? (
          <Empty>
            No suite exists in this workspace yet. Create one below, or promote a real
            production trace into one.
            <InfoTip text="That is why this reads 0, not because evaluation is broken." />
          </Empty>
        ) : (
        <table>
          <thead><tr><th>suite</th><th>description</th><th>tags</th><th className="num">cases</th></tr></thead>
          <tbody>
            {suites.suites.map((s: any) => (
              <tr key={s.id}>
                <td className="mono small"><Link href={`/app/evals/${s.key}`}>{s.key}</Link></td>
                <td className="small wrap muted" style={{ maxWidth: 460 }}>{s.description}</td>
                <td className="small muted">{(s.tags || []).join(", ")}</td>
                <td className="num">{s.cases}</td>
              </tr>
            ))}
          </tbody>
        </table>
        )}
        <div className="body" style={{ borderTop: "1px solid var(--border)" }}>
          <form action="/api/eval/suites" method="POST" className="row" style={{ gap: 6 }}>
            <input
              type="text" name="key" aria-label="Suite key" placeholder="key, e.g. support-quality" required
              style={{ width: 200, padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
            />
            <input
              type="text" name="name" aria-label="Suite name (optional)" placeholder="name (optional)"
              style={{ width: 200, padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
            />
            <input
              type="text" name="description" aria-label="Suite description (optional)" placeholder="description (optional)"
              style={{ flex: 1, minWidth: 200, padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
            />
            <button type="submit" className="btn-primary">Create suite</button>
          </form>
        </div>
      </div>

      <h2 id="redteam">Red-team posture</h2>
      <p className="sub">
        A campaign runs the built-in attack probes against one agent and reports how
        many got through.
        <InfoTip text="It uses that agent's real grants and policy bindings rather than a mock. Run one before you promote a policy to enforce, and again after, so the number means something." />
      </p>
      {/* Three unrelated things in one paragraph with three tooltips wedged
          between them: the caveat on what a score means, where the probe list
          lives, and what an --adaptive run does. Only the first changes how
          somebody reads the number underneath, so only the first stays here. */}
      <p className="caveat-line">
        <strong>A high score is a narrow claim.</strong> It says the probes in this
        library did not get through — not that the agent is safe. An attack nobody
        wrote a probe for scores exactly the same as one that was stopped.
      </p>
      <form action="/api/redteam/campaigns" method="POST" className="row" style={{ gap: 8, marginBottom: 10, alignItems: "center" }}>
        <select
          name="agent"
          required
          defaultValue=""
          aria-label="Agent to run probes against"
          style={{ padding: "5px 9px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 13, fontFamily: "inherit" }}
        >
          <option value="" disabled>choose an agent…</option>
          {(agents.agents || []).map((a: any) => (
            <option key={a.slug} value={a.slug}>{a.name || a.slug}</option>
          ))}
        </select>
        <button type="submit" className="btn-scan">Run built-in probes</button>
        <span className="small muted">
          Or from the CLI: <code className="mono">agentfox test redteam &lt;agent&gt;</code>
        <InfoTip text="Add --adaptive and it mutates a blocked probe and retries it, reporting the change in posture against the last comparable campaign instead of a pass rate. It exits zero whatever it finds, so read the output rather than the exit code. The probes it can draw on are catalogued on the Policies page." />
        </span>
      </form>
      <div className="panel">
        {campaigns.campaigns.length === 0 ? (
          <div className="body muted small">
            No campaigns yet. Pick an agent above and run one; it takes the built-in
            probe library and needs no test cases of your own.
            <InfoTip text="It is usually the first real number you can get out of this page." />
          </div>
        ) : (
          <table>
            <thead>
              <tr><th>campaign</th><th>runner</th><th className="num">probes</th><th className="num">blocked</th><th className="num">got through</th><th className="num">posture</th><th>when</th></tr>
            </thead>
            <tbody>
              {campaigns.campaigns.map((c: any) => (
                <tr key={c.id}>
                  <td className="small">{c.name}</td>
                  <td className="small muted">{c.runner}</td>
                  <td className="num">{c.summary?.probes_run}</td>
                  <td className="num">{c.summary?.attacks_blocked}</td>
                  <td className="num">
                    {c.summary?.attacks_succeeded ? (
                      <span className="tag bad">{c.summary.attacks_succeeded}</span>
                    ) : "0"}
                  </td>
                  <td className="num">
                    <span className={`tag ${c.summary?.posture_score >= 0.9 ? "ok" : "warn"}`}>
                      {Math.round((c.summary?.posture_score ?? 0) * 100)}%
                    </span>
                  </td>
                  <td className="small muted">{ts(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* "Scorers" and "Failing a build on a regression" were two more open
          sections at the foot of this page: a read-only registry table, and a
          four-row command reference. Neither is something you come to this page
          to do — they are what you read once to understand how the page works.
          One button, both behind it, and the page ends on its own content. */}
      <div className="section-head">
        <h2>How scoring and gating work</h2>
        <Explainer label="Scorers and the CI gate" title="Scorers and the CI gate">
          <p>
            A <strong>scorer</strong> is one judgement applied to an answer — accuracy,
            groundedness, safety. They ship with the product and are fixed: the
            threshold below is each scorer&rsquo;s built-in default, not a setting.
            The number you actually choose is a <strong>reliability objective</strong>,
            set per agent against a scorer, and visible on an agent&rsquo;s{" "}
            <Link href="/app/agents">Activity tab</Link>.
          </p>

          <h4>Scorers that ship</h4>
          <div className="panel scroll-x">
            <table>
              <thead><tr><th>scorer</th><th>kind</th><th>direction</th><th className="num">default threshold</th></tr></thead>
              <tbody>
                {scorers.scorers.map((s: any) => (
                  <tr key={s.key}>
                    <td className="mono small">{s.key}</td>
                    <td className="small muted">{s.kind}</td>
                    <td className="small muted">
                      {s.higher_is_better ? "higher is better" : "lower is better"}
                    </td>
                    <td className="num small">{s.threshold ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h4>Failing a build on a regression</h4>
          <p>
            The same suite, run from your build against a baseline, exiting non-zero
            when the score drops. It is a command, not a screen — runs otherwise
            happen when someone remembers, and a gate fails the pull request instead
            of a person noticing later.
          </p>
          <div className="panel scroll-x">
            <table>
              <thead>
                <tr><th>step</th><th>command</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td className="small">Record the run to be judged against</td>
                  <td className="mono small">agentfox test baseline RUN_ID --label main</td>
                </tr>
                <tr>
                  <td className="small">Gate a build on it</td>
                  <td className="mono small">agentfox test gate SUITE --baseline RUN_ID</td>
                </tr>
                <tr>
                  <td className="small">Or gate on an absolute floor instead</td>
                  <td className="mono small">agentfox test gate SUITE --min-pass-rate 0.9</td>
                </tr>
                <tr>
                  <td className="small">Write results your CI already reads</td>
                  <td className="mono small">--junit results.xml --sarif results.sarif</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p>
            The gate exits 1 on a regression and takes a suite, not an agent. The
            default model provider is <span className="mono">echo</span> — offline,
            answering with a fixed stub — so a gate left on the default tells you the
            pipeline runs and nothing about a real model. A passing gate says this
            suite did not get worse; it says nothing about the cases nobody wrote.
            Also over HTTP as <span className="mono">POST /api/eval/gate</span>.
          </p>
        </Explainer>
      </div>
    </>
  );
}

