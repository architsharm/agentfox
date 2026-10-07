import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { api, safeApi, apiErrorProps } from "@/lib/product/api";
import { ApiDown } from "@/components/ui";
import { PageHeader } from "@/components/product/PageHeader";
import { ExpandableFindingRow } from "@/components/product/ExpandableFindingRow";
import { controlTitleMap } from "@/lib/product/controls";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata(
  "Findings",
  "What the detectors and scorers flagged, ranked by what needs a human.",
);

export const dynamic = "force-dynamic";

export default async function Findings({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; severity?: string; agent?: string }>;
}) {
  const sp = await searchParams;
  const qs = new URLSearchParams({ limit: "200", status: sp.status ?? "open" });
  if (sp.severity) qs.set("severity", sp.severity);
  if (sp.agent) qs.set("agent", sp.agent);

  let data: any, agents: any, controlTitles: Record<string, string>;
  try {
    [data, agents, controlTitles] = await Promise.all([
      api(`/api/findings?${qs}`),
      safeApi("/api/agents", { agents: [] }),
      controlTitleMap(),
    ]);
  } catch (e: any) {
    return (
      <>
        <h1>Findings</h1>
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }

  return (
    <>
      <PageHeader title="Findings" sub="Every problem detected, most severe first." />

      {/* Each chip run is a group with its own name: read one chip at a time, a
          bare "high" says nothing about what it filters. `display: contents`
          keeps the chipbar's own flex wrapping exactly as it was. */}
      <form action="/app/findings" method="GET" className="chipbar">
        <span role="group" aria-label="Filter by status" style={{ display: "contents" }}>
          <span className="chipbar-label">status:</span>
          {["open", "resolved", "suppressed"].map((s) => (
            <Link
              key={s}
              href={`/app/findings?status=${s}${sp.severity ? `&severity=${sp.severity}` : ""}${sp.agent ? `&agent=${sp.agent}` : ""}`}
              className={`chip${(sp.status ?? "open") === s ? " active" : ""}`}
              aria-current={(sp.status ?? "open") === s ? "true" : undefined}
            >
              {s}
            </Link>
          ))}
        </span>
        <span role="group" aria-label="Filter by severity" style={{ display: "contents" }}>
          <span className="chipbar-label" style={{ marginLeft: 10 }}>severity:</span>
          {["critical", "high", "medium", "low"].map((s) => (
            <Link
              key={s}
              href={`/app/findings?status=${sp.status ?? "open"}&severity=${s}${sp.agent ? `&agent=${sp.agent}` : ""}`}
              className={`chip${sp.severity === s ? " active" : ""}`}
              aria-current={sp.severity === s ? "true" : undefined}
            >
              {s}
            </Link>
          ))}
          {sp.severity && (
            <Link href={`/app/findings?status=${sp.status ?? "open"}${sp.agent ? `&agent=${sp.agent}` : ""}`} className="chip">
              clear severity ×
            </Link>
          )}
        </span>
        <label htmlFor="findings-agent-filter" className="chipbar-label" style={{ marginLeft: 10 }}>
          agent:
        </label>
        <input type="hidden" name="status" value={sp.status ?? "open"} />
        {sp.severity && <input type="hidden" name="severity" value={sp.severity} />}
        <select
          id="findings-agent-filter"
          name="agent"
          defaultValue={sp.agent ?? ""}
          style={{ padding: "3px 8px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", fontSize: 12, fontFamily: "inherit" }}
        >
          <option value="">all agents</option>
          {(agents.agents || []).map((a: any) => (
            <option key={a.slug} value={a.slug}>{a.name || a.slug}</option>
          ))}
        </select>
        <button type="submit" className="chip" style={{ cursor: "pointer" }}>filter</button>
        {sp.agent && (
          <Link href={`/app/findings?status=${sp.status ?? "open"}${sp.severity ? `&severity=${sp.severity}` : ""}`} className="chip">
            clear agent ×
          </Link>
        )}
      </form>

      <div className="panel scroll-x">
        {data.findings.length === 0 ? (
          <div className="body muted small">
            No findings match. Either nothing has tripped a detector, or no traffic has been
            recorded yet — check <Link href="/app/start">Start here</Link>.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th className="w-chip">severity</th>
                <th className="w-name">agent</th>
                <th className="w-short">type</th>
                <th className="w-prose">finding</th>
                <th className="w-name">controls</th>
                <th className="w-when">raised</th>
              </tr>
            </thead>
            <tbody>
              {data.findings.map((f: any) => (
                <ExpandableFindingRow
                  key={f.id}
                  finding={f}
                  agents={agents.agents || []}
                  controlTitles={controlTitles}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
