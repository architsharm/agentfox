import type { Metadata } from "next";
import { PageHeader } from "@/components/product/PageHeader";
import { Breakdown } from "@/components/product/observe/Breakdown";
import { safeApi } from "@/lib/product/api";
import { observeScope } from "@/lib/product/observeScope";
import { appPageMetadata } from "@/lib/site";

export const metadata: Metadata = appPageMetadata("Models");
export const dynamic = "force-dynamic";

/** The LLMs the project's agents called this week: how often, what it cost, what failed. */
export default async function Models({ searchParams }: { searchParams: Promise<{ agent?: string }> }) {
  const { agent } = await searchParams;
  const scope = await observeScope(agent);
  const map = scope.project ? await safeApi<any>(`/api/projects/${encodeURIComponent(scope.project)}/map`, null) : null;
  const declared: string[] = [...new Set<string>((map?.agents ?? []).flatMap((a: any) => a.models))];
  const { rows } = await safeApi<any>("/api/metrics/breakdown?dim=model&range=7d", { rows: [] });
  // Calls whose model was not recorded say nothing about any model, so they are left out;
  // with a project chosen, only the models its agents run on.
  const known = (rows ?? []).filter((r: any) => r.key && !["None", "(unknown)", "unknown"].includes(r.key));
  const shown = declared.length ? known.filter((r: any) => declared.includes(r.key)) : known;
  return (
    <>
      <PageHeader
        title="Models"
        sub={`${scope.project ?? "no project"} · LLM calls in the last 7 days${declared.length ? ` · runs on ${declared.join(", ")}` : ""}`}
      />
      <Breakdown
        rows={shown}
        label="Model"
        cost
        empty="no LLM calls recorded yet. guard the model call (or turn on OpenTelemetry) and they show up here."
      />
    </>
  );
}
