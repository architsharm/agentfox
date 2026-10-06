import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { api, safeApi, apiErrorProps } from "@/lib/product/api";
import { ApiDown } from "@/components/ui";
import { PageHeader } from "@/components/product/PageHeader";
import { ExpandableTraceRow } from "@/components/product/ExpandableTraceRow";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata(
  "Traces",
  "The execution-path record of what each agent actually did, call by call.",
);

export const dynamic = "force-dynamic";

export default async function Traces({
  searchParams,
}: {
  searchParams: Promise<{ agent?: string; verdict?: string; entity_type?: string }>;
}) {
  const sp = await searchParams;
  const qs = new URLSearchParams({ limit: "150" });
  if (sp.agent) qs.set("agent", sp.agent);
  if (sp.verdict) qs.set("verdict", sp.verdict);
  if (sp.entity_type) qs.set("entity_type", sp.entity_type);

  let data: any, agents: any;
  try {
    [data, agents] = await Promise.all([
      api(`/api/traces?${qs}`),
      safeApi("/api/agents", { agents: [] }),
    ]);
  } catch (e: any) {
    return (
      <>
        <h1>Traces</h1>
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }

  const agentQs = sp.agent ? `&agent=${sp.agent}` : "";

  return (
    <>
      <PageHeader title="Traces" sub="What an agent actually did on one request, end to end." />

      <form action="/app/traces" method="GET" className="chipbar">
        {/* `display: contents` so naming the group costs nothing in layout. */}
        <span role="group" aria-label="Filter traces by outcome" style={{ display: "contents" }}>
          <span className="chipbar-label">filter:</span>
          <Link href={`/app/traces?${agentQs.replace(/^&/, "")}`} className={`chip${!sp.verdict && !sp.entity_type ? " active" : ""}`} aria-current={!sp.verdict && !sp.entity_type ? "true" : undefined}>all</Link>
          <Link href={`/app/traces?verdict=block${agentQs}`} className={`chip${sp.verdict === "block" ? " active" : ""}`} aria-current={sp.verdict === "block" ? "true" : undefined}>blocked</Link>
          <Link href={`/app/traces?verdict=escalate${agentQs}`} className={`chip${sp.verdict === "escalate" ? " active" : ""}`} aria-current={sp.verdict === "escalate" ? "true" : undefined}>escalated</Link>
          <Link href={`/app/traces?entity_type=INJECTION${agentQs}`} className={`chip${sp.entity_type === "INJECTION" ? " active" : ""}`} aria-current={sp.entity_type === "INJECTION" ? "true" : undefined}>injection</Link>
          <Link href={`/app/traces?entity_type=PII${agentQs}`} className={`chip${sp.entity_type === "PII" ? " active" : ""}`} aria-current={sp.entity_type === "PII" ? "true" : undefined}>PII</Link>
          <Link href={`/app/traces?entity_type=SECRET${agentQs}`} className={`chip${sp.entity_type === "SECRET" ? " active" : ""}`} aria-current={sp.entity_type === "SECRET" ? "true" : undefined}>secrets</Link>
        </span>
        <label htmlFor="traces-agent-filter" className="chipbar-label" style={{ marginLeft: 10 }}>
          agent:
        </label>
        {sp.verdict && <input type="hidden" name="verdict" value={sp.verdict} />}
        {sp.entity_type && <input type="hidden" name="entity_type" value={sp.entity_type} />}
        <select
          id="traces-agent-filter"
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
          <Link href={`/app/traces?${sp.verdict ? `verdict=${sp.verdict}` : ""}${sp.entity_type ? `${sp.verdict ? "&" : ""}entity_type=${sp.entity_type}` : ""}`} className="chip">
            clear agent ×
          </Link>
        )}
      </form>

      <div className="panel scroll-x">
        {data.traces.length === 0 ? (
          <div className="body muted small">
            No traces match{sp.agent || sp.verdict || sp.entity_type ? " this filter" : ""}.
            Either nothing has run yet — check <Link href="/app/start">Start here</Link> — or try
            clearing the filter above.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>trace</th><th>agent</th><th>verdict</th><th>env</th>
                <th>model</th><th>intent</th><th>when</th>
              </tr>
            </thead>
            <tbody>
              {data.traces.map((t: any) => (
                <ExpandableTraceRow key={t.id} trace={t} agents={agents.agents || []} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
