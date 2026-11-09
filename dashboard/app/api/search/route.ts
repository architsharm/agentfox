import { NextResponse } from "next/server";
import { api } from "@/lib/product/api";
import { buildIndex } from "@/lib/product/searchIndex";

export const dynamic = "force-dynamic";

/**
 * The records Cmd-K searches (agents, tools, rules, open issues, suites, controls,
 * evidence packs), from list
 * endpoints the app already uses, in one round trip. Each source is best effort: one
 * that fails (an edition without it, a slow gateway) leaves the others searchable.
 */
export async function GET() {
  const get = (path: string) => api<any>(path).catch(() => null);
  const [agents, tools, policies, findings, suites, controls, evidence] = await Promise.all([
    get("/api/agents"),
    get("/api/tools"),
    get("/api/policies?full=1"),
    get("/api/findings?status=open&limit=200"),
    get("/api/eval/suites"),
    // Enterprise only; without it these fail and are left out.
    get("/api/controls"),
    get("/api/evidence"),
  ]);
  return NextResponse.json(
    {
      items: buildIndex({
        agents: agents?.agents,
        tools: tools?.tools,
        policies: policies?.policies,
        findings: findings?.findings,
        suites: suites?.suites,
        controls: controls?.controls,
        evidence: evidence?.packages,
      }),
    },
    { headers: { "Cache-Control": "private, no-store" } },
  );
}
