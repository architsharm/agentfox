import type { CSSProperties } from "react";
import type { Metadata } from "next";
import Link from "next/link";

import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";
import {
  DIRECTION_LABEL,
  fetchShowcase,
  ofTotal,
  REVALIDATE_SECONDS,
  type Showcase,
  type ShowcaseResult,
} from "@/lib/showcase";
import { publicPageMetadata } from "@/lib/site";

/**
 * /live — AgentFox probing its own demo agent, every hour, in public.
 *
 * The numbers come from the gateway's unauthenticated `GET /api/public/showcase`
 * (agentfox/apps/showcase.py), which reads only the showcase tenant. Nothing on
 * this page is typed in by hand: if an attack got through on the last run, the page
 * says so, and the open findings say so too.
 *
 * Server-rendered and revalidated every five minutes. The gateway caches its answer
 * for a minute and runs the probes hourly, so a fresher page would not show fresher
 * data.
 */

export const revalidate = 300;

export const metadata: Metadata = publicPageMetadata({
  title: "Live: AgentFox probing its own agent",
  description:
    "Every hour AgentFox attacks its own demo support agent through the real enforcement path. The results, unedited, including what got through.",
  path: "/live",
});

const SCROLLER: CSSProperties = { padding: 0, overflowX: "auto" };
const TABLE: CSSProperties = {
  width: "100%",
  minWidth: 620,
  borderCollapse: "collapse",
  fontSize: "var(--t-small)",
};
const TH: CSSProperties = {
  padding: "12px 14px",
  borderBottom: "1px solid var(--mk-border-strong)",
  textAlign: "left",
  fontWeight: 600,
};
const TD: CSSProperties = {
  padding: "11px 14px",
  borderBottom: "1px solid var(--mk-border)",
  verticalAlign: "top",
  color: "var(--mk-muted)",
};
const TD_HEAD: CSSProperties = { ...TD, color: "var(--mk-text)", fontWeight: 500 };

function when(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

function Outcome({ result }: { result: ShowcaseResult }) {
  switch (result.status) {
    case "contained":
      return (
        <span className="mk-chip mk-chip-go">
          {result.contained_by === "blocked" ? "Contained: blocked" : "Contained"}
        </span>
      );
    case "escaped":
      return <span className="mk-chip mk-chip-stop">Got through</span>;
    case "answered":
      return <span className="mk-chip mk-chip-go">Answered</span>;
    case "over_blocked":
      return <span className="mk-chip mk-chip-hold">Wrongly blocked</span>;
    default:
      return <span className="mk-chip mk-chip-hold">{result.status === "error" ? "Error" : "Skipped"}</span>;
  }
}

function Head({ eyebrow, title, lede }: { eyebrow: string; title: string; lede?: string }) {
  return (
    <div className="mk-narrow mk-up">
      <span className="mk-eyebrow">{eyebrow}</span>
      <h2 className="mk-h2" style={{ marginTop: 14 }}>
        {title}
      </h2>
      {lede && (
        <p className="mk-lede" style={{ marginTop: 14 }}>
          {lede}
        </p>
      )}
    </div>
  );
}

function Notice({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mk-section mk-reveal">
      <div className="mk-wrap">
        <div className="mk-narrow mk-card">
          <h2 className="mk-h3">{title}</h2>
          <p className="mk-body" style={{ margin: "10px 0 0" }}>
            {children}
          </p>
        </div>
      </div>
    </section>
  );
}

function Live({ data }: { data: Showcase }) {
  const { totals, latest, runs, findings } = data;
  const attacks = latest.results.filter((r) => r.expect_blocked);
  const controls = latest.results.filter((r) => !r.expect_blocked);
  const lastRun = latest.run;
  return (
    <>
      <section className="mk-section mk-band mk-reveal">
        <div className="mk-wrap">
          <Head
            eyebrow={`The last ${data.window_days} days`}
            title={
              totals.escaped === 0
                ? "Every attack sent was contained"
                : `${totals.escaped} attack${totals.escaped === 1 ? "" : "s"} got through`
            }
            lede={`Last run ${when(data.last_updated)}. ${totals.runs} run${totals.runs === 1 ? "" : "s"}, the same ${attacks.length || data.target.probes.length} attacks each time.`}
          />
          <div className="mk-grid mk-grid-5" style={{ marginTop: 36 }}>
            <div className="mk-card mk-stat">
              <b>{totals.attacks_attempted}</b>
              <span>Attacks sent</span>
            </div>
            <div className="mk-card mk-stat">
              <b>{totals.contained}</b>
              <span>Contained</span>
            </div>
            <div className="mk-card mk-stat">
              <b style={totals.escaped ? { color: "var(--mk-stop)" } : undefined}>{totals.escaped}</b>
              <span>Got through</span>
            </div>
            <div className="mk-card mk-stat">
              <b>{findings.open}</b>
              <span>Findings open now</span>
            </div>
            <div className="mk-card mk-stat">
              <b>{findings.closed_in_window}</b>
              <span>Findings closed</span>
            </div>
          </div>
          {totals.errors > 0 && (
            <p className="mk-fine" style={{ marginTop: 14 }}>
              {totals.errors} probe{totals.errors === 1 ? "" : "s"} errored and {totals.errors === 1 ? "is" : "are"}{" "}
              counted as neither contained nor got through.
            </p>
          )}
        </div>
      </section>

      <section className="mk-section mk-reveal">
        <div className="mk-wrap">
          <Head
            eyebrow="The last run"
            title="Attack by attack"
            lede={latest.headline ?? undefined}
          />
          <div className="mk-card mk-up mk-d2" style={{ ...SCROLLER, marginTop: 36 }}>
            <table style={TABLE}>
              <thead>
                <tr>
                  <th style={TH}>Probe</th>
                  <th style={TH}>What it tries</th>
                  <th style={TH}>OWASP</th>
                  <th style={TH}>Result</th>
                </tr>
              </thead>
              <tbody>
                {[...attacks, ...controls].map((r) => (
                  <tr key={r.key}>
                    <td style={TD_HEAD}>
                      <code>{r.key}</code>
                    </td>
                    <td style={TD}>{r.description}</td>
                    <td style={TD}>{r.owasp_id ?? "—"}</td>
                    <td style={TD}>
                      <Outcome result={r} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {lastRun && lastRun.over_blocked > 0 && (
            <p className="mk-fine" style={{ marginTop: 14 }}>
              The two benign questions are controls: blocking them is over-blocking, and it is
              reported, not hidden.
            </p>
          )}
        </div>
      </section>

      <section className="mk-section mk-band mk-reveal">
        <div className="mk-wrap">
          <Head
            eyebrow="Run history"
            title="Did it get weaker?"
            lede="Each run is compared with the previous one. An attack that was contained and now gets through opens a finding; it closes when a later run contains it again."
          />
          <div className="mk-card mk-up mk-d2" style={{ ...SCROLLER, marginTop: 36 }}>
            <table style={TABLE}>
              <thead>
                <tr>
                  <th style={TH}>Finished</th>
                  <th style={TH}>Contained</th>
                  <th style={TH}>Got through</th>
                  <th style={TH}>Against the run before</th>
                  <th style={TH}>Findings</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td style={TD_HEAD}>{when(run.finished_at)}</td>
                    <td style={TD}>{ofTotal(run.contained, run.attacks_attempted)}</td>
                    <td style={TD}>{ofTotal(run.escaped, run.attacks_attempted)}</td>
                    <td style={TD}>{DIRECTION_LABEL[run.direction ?? ""] ?? "—"}</td>
                    <td style={TD}>
                      {run.findings_opened || run.findings_closed
                        ? `${run.findings_opened} opened, ${run.findings_closed} closed`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {findings.recent.length > 0 && (
        <section className="mk-section mk-reveal">
          <div className="mk-wrap">
            <Head
              eyebrow="Findings"
              title="What it raised"
              lede={`${findings.opened_in_window} opened and ${findings.closed_in_window} closed in the last ${data.window_days} days.`}
            />
            <div className="mk-card mk-up mk-d2" style={{ ...SCROLLER, marginTop: 36 }}>
              <table style={TABLE}>
                <thead>
                  <tr>
                    <th style={TH}>Finding</th>
                    <th style={TH}>Severity</th>
                    <th style={TH}>Status</th>
                    <th style={TH}>Opened</th>
                    <th style={TH}>Seen</th>
                  </tr>
                </thead>
                <tbody>
                  {findings.recent.map((f) => (
                    <tr key={`${f.title}-${f.opened_at}`}>
                      <td style={TD_HEAD}>{f.title}</td>
                      <td style={TD}>{f.severity}</td>
                      <td style={TD}>
                        {f.status === "open" ? (
                          <span className="mk-chip mk-chip-stop">Open</span>
                        ) : (
                          <span className="mk-chip mk-chip-go">Closed {when(f.resolved_at)}</span>
                        )}
                      </td>
                      <td style={TD}>{when(f.opened_at)}</td>
                      <td style={TD}>
                        {f.occurrences} run{f.occurrences === 1 ? "" : "s"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      <section className="mk-section mk-band mk-reveal">
        <div className="mk-wrap">
          <Head eyebrow="Read this before quoting it" title="What this measures, and what it does not" />
          <div className="mk-grid mk-grid-2" style={{ marginTop: 36 }}>
            <div className="mk-card">
              <span className="mk-label">How a probe is scored</span>
              <p className="mk-body" style={{ margin: "8px 0 0", fontSize: "var(--t-small)" }}>
                {data.how_scored}
              </p>
            </div>
            <div className="mk-card">
              <span className="mk-label">What it is not</span>
              <p className="mk-body" style={{ margin: "8px 0 0", fontSize: "var(--t-small)" }}>
                {data.what_this_measures}
              </p>
            </div>
          </div>
          <p className="mk-fine" style={{ marginTop: 18 }}>
            The agent is {data.agent.name}: {data.agent.purpose} It runs on {data.target.model ?? "an offline model"},
            which costs nothing and never calls out, in a tenant of its own. The same probes run
            against your agents once you opt in:{" "}
            <Link href="/docs/guides/live-probes">probing deployed agents</Link>.
          </p>
        </div>
      </section>
    </>
  );
}

export default async function LivePage() {
  const feed = await fetchShowcase();
  return (
    <div className="mk">
      <MarketingNav />
      <main>
        <section className="mk-section mk-page-hero mk-ink-act">
          <div className="mk-wrap">
            <span className="mk-eyebrow mk-up">Live</span>
            <h1 className="mk-h1 mk-up mk-d1">AgentFox, attacking its own agent</h1>
            <p className="mk-lede mk-up mk-d2" style={{ marginTop: 20 }}>
              Every hour the same set of attacks goes to our demo support agent, through the
              enforcement path you would run. These are the results as recorded, including the
              ones that got through.
            </p>
            <div className="mk-row mk-up mk-d3" style={{ marginTop: 26, gap: 10 }}>
              <Link href="/playground" className="mk-btn mk-btn-primary">
                Attack it yourself
              </Link>
              <Link href="/docs/guides/live-probes" className="mk-btn mk-btn-outline">
                Probe your own agent
              </Link>
            </div>
          </div>
        </section>

        {feed.state === "live" && <Live data={feed.data} />}
        {feed.state === "off" && (
          <Notice title="The live run is not switched on here">
            This deployment is not running the showcase, so there is nothing to show yet. No
            numbers are filled in while it is off.
          </Notice>
        )}
        {feed.state === "unavailable" && (
          <Notice title="The live feed could not be read just now">
            This page asks the gateway for the latest results every {REVALIDATE_SECONDS / 60}{" "}
            minutes, and the last attempt failed. Nothing is shown in its place.
          </Notice>
        )}
      </main>
      <Footer />
    </div>
  );
}
