import type { Metadata } from "next";
import { PageHeader } from "@/components/product/PageHeader";
import { Breakdown } from "@/components/product/observe/Breakdown";
import { safeApi } from "@/lib/product/api";
import { observeScope } from "@/lib/product/observeScope";
import { appPageMetadata } from "@/lib/site";

export const metadata: Metadata = appPageMetadata("Tools");
export const dynamic = "force-dynamic";

/** Every tool the project's agents called this week: how often, and what was let through. */
export default async function Tools({ searchParams }: { searchParams: Promise<{ agent?: string }> }) {
  const { agent } = await searchParams;
  const scope = await observeScope(agent);
  const map = scope.project ? await safeApi<any>(`/api/projects/${encodeURIComponent(scope.project)}/map`, null) : null;
  const mine = new Set<string>((map?.agents ?? []).flatMap((a: any) => a.tools));
  const { rows } = await safeApi<any>("/api/metrics/breakdown?dim=tool&range=7d", { rows: [] });
  const shown = (rows ?? []).filter((r: any) => !scope.project || mine.has(r.key));
  return (
    <>
      <PageHeader title="Tools" sub={`${scope.project ?? "no project"} · tool calls in the last 7 days, busiest first`} />
      <Breakdown rows={shown} label="Tool" empty="no tool calls in the last 7 days." />
    </>
  );
}
