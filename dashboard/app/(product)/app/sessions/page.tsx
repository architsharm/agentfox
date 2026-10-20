import type { Metadata } from "next";
import { PageHeader } from "@/components/product/PageHeader";
import { AgentLink, Empty, ObsTable, SessionId, Time, Verdict } from "@/components/product/observe/parts";
import { safeApi } from "@/lib/product/api";
import { agentQuery, observeScope } from "@/lib/product/observeScope";
import { appPageMetadata } from "@/lib/site";

export const metadata: Metadata = appPageMetadata("Sessions");
export const dynamic = "force-dynamic";

/** One row per conversation: what the user asked, how many steps, which tools, how it ended. */
export default async function Sessions({ searchParams }: { searchParams: Promise<{ agent?: string }> }) {
  const { agent } = await searchParams;
  const scope = await observeScope(agent);
  const { traces } = await safeApi<any>(`/api/traces?${agentQuery(scope.agents)}group=true&limit=100`, { traces: [] });
  const rows = (traces ?? []).filter((t: any) => scope.agents.includes(t.agent));

  return (
    <>
      <PageHeader title="Sessions" sub={`${scope.project ?? "no project"} · one row per conversation, newest first`} />
      <ObsTable head={["Started", "Session", "Agent", "First message", "Steps", "Tools", "Outcome"]} empty={!rows.length && <Empty>no sessions yet.</Empty>}>
        {rows.map((t: any) => (
          <tr key={t.id}>
            <td><Time at={t.started_at} /></td>
            <td><SessionId id={t.session_id} /></td>
            <td><AgentLink slug={t.agent} /></td>
            <td className="obs-summary">{t.summary || <span className="muted">—</span>}</td>
            <td className="mono">{t.runs ?? t.checks ?? 1}</td>
            <td className="mono obs-summary">{t.tools?.length ? t.tools.join(", ") : <span className="muted">—</span>}</td>
            <td><Verdict verdict={t.verdict} would={t.would_verdict} /></td>
          </tr>
        ))}
      </ObsTable>
    </>
  );
}
