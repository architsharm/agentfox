import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { safeApi } from "@/lib/product/api";
import { Card, Empty, Header, href } from "@/components/kit";
import { GuardrailMapLazy as GuardrailMap } from "@/components/product/agent/GuardrailMapLazy";

export const metadata: Metadata = appPageMetadata("Guardrail map", "Which guardrails apply at each step of an agent's requests.");
export const dynamic = "force-dynamic";

/** Every agent's guardrails, one map at a time: pick an agent, see where each rule acts. */
export default async function MapPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const agents = await safeApi<any>("/api/agents", { agents: [] });
  const live = (agents.agents || []).filter((a: any) => a.status !== "draft");
  const slug = sp.agent || live[0]?.slug;
  const map = slug ? await safeApi<any>(`/api/agents/${encodeURIComponent(slug)}/map`, null) : null;
  return (
    <>
      <Header title="Guardrail map" />
      {live.length > 1 && (
        <div className="chipbar">
          {live.map((a: any) => (
            <Link key={a.slug} href={href("/app/map", { agent: a.slug })} className={a.slug === slug ? "chip active" : "chip"}>
              {a.name || a.slug}
            </Link>
          ))}
        </div>
      )}
      {map ? <GuardrailMap map={map} /> : <Card><Empty action={<Link href="/app/start" className="k-btn-primary">Connect an agent</Link>}>No agents yet.</Empty></Card>}
    </>
  );
}
