import type { Metadata } from "next";
import { PageHeader } from "@/components/product/PageHeader";
import { AgentLink, Empty, EventBadge, ObsTable, SessionId, Time, Verdict } from "@/components/product/observe/parts";
import { safeApi } from "@/lib/product/api";
import { agentQuery, observeScope } from "@/lib/product/observeScope";
import { appPageMetadata } from "@/lib/site";

export const metadata: Metadata = appPageMetadata("Events");
export const dynamic = "force-dynamic";

/** Every guarded step, newest first: a message in, a tool call, a tool's result, a reply out. */
export default async function Events({ searchParams }: { searchParams: Promise<{ agent?: string }> }) {
  const { agent } = await searchParams;
  const scope = await observeScope(agent);
  const { traces } = await safeApi<any>(`/api/traces?${agentQuery(scope.agents)}limit=200`, { traces: [] });
  const rows = (traces ?? []).filter((t: any) => scope.agents.includes(t.agent));

  return (
    <>
      <PageHeader title="Events" sub={`${scope.project ?? "no project"} · every guarded step, newest first`} />
      <ObsTable head={["Time", "Event", "Decision", "Agent", "Session", "Summary"]} empty={!rows.length && <Empty>no events yet. they show up the moment an agent runs.</Empty>}>
        {rows.map((t: any) => (
          <tr key={t.id}>
            <td><Time at={t.started_at} /></td>
            <td><EventBadge surface={t.surfaces?.[0]} /></td>
            <td><Verdict verdict={t.verdict} would={t.would_verdict} /></td>
            <td><AgentLink slug={t.agent} /></td>
            <td><SessionId id={t.session_id} /></td>
            <td className="obs-summary">
              {t.tools?.length ? <span className="mono">{t.tools.join(", ")}</span> : t.summary || <span className="muted">—</span>}
              {t.rules?.length ? <span className="obs-rules"> ← {t.rules.join(", ")}</span> : null}
            </td>
          </tr>
        ))}
      </ObsTable>
    </>
  );
}
