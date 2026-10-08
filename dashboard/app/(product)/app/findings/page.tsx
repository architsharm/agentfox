import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { api, apiErrorProps, safeApi } from "@/lib/product/api";
import { ApiDown, findingTypeInfo } from "@/components/ui";
import { Card, Empty, Header, SeverityPill, Tabs, ago, href, num } from "@/components/kit";
import { FilterBar } from "@/components/kit/FilterBar";
import { severityRank } from "@/lib/product/vocab";

export const metadata: Metadata = appPageMetadata("Issues", "Problems that need a person, most severe first.");
export const dynamic = "force-dynamic";

type SP = Record<string, string | undefined>;

const STATUSES = [
  { key: "open", label: "Open" },
  { key: "resolved", label: "Resolved" },
  { key: "suppressed", label: "Accepted" },
];

const SEVERITIES = ["critical", "high", "medium", "low"];

export default async function Issues({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const status = STATUSES.some((s) => s.key === sp.status) ? sp.status! : "open";
  const qs = new URLSearchParams({ limit: "200", status });
  if (sp.severity) qs.set("severity", sp.severity);
  if (sp.agent) qs.set("agent", sp.agent);

  let data: any;
  try {
    data = await api(`/api/findings?${qs}`);
  } catch (e: any) {
    return (
      <>
        <Header title="Issues" />
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }
  const [agents, counts] = await Promise.all([
    safeApi<any>("/api/agents", { agents: [] }),
    Promise.all(STATUSES.map((s) => safeApi<any>(`/api/findings?status=${s.key}&limit=500${sp.agent ? `&agent=${sp.agent}` : ""}`, { findings: [] }))),
  ]);
  const rows = [...(data.findings || [])].sort(
    (a, b) => severityRank(a.severity) - severityRank(b.severity) || String(b.last_seen_at).localeCompare(String(a.last_seen_at)),
  );
  const keep = { agent: sp.agent, severity: sp.severity };

  return (
    <>
      <Header title="Issues" />
      <Tabs
        active={status}
        items={STATUSES.map((s, i) => ({
          key: s.key,
          label: s.label,
          count: counts[i].findings?.length,
          href: href("/app/findings", { ...keep, status: s.key === "open" ? undefined : s.key }),
        }))}
      />
      <FilterBar range={false} agents={(agents.agents || []).map((a: any) => ({ slug: a.slug, name: a.name }))}>
        <div className="k-seg" role="group" aria-label="Severity">
          <Link href={href("/app/findings", { agent: sp.agent, status: sp.status })} className={!sp.severity ? "active" : ""} scroll={false}>
            All
          </Link>
          {SEVERITIES.map((s) => (
            <Link key={s} href={href("/app/findings", { agent: sp.agent, status: sp.status, severity: s })} className={sp.severity === s ? "active" : ""} scroll={false}>
              {s[0].toUpperCase() + s.slice(1)}
            </Link>
          ))}
        </div>
      </FilterBar>
      <Card flush>
        {rows.length ? (
          <table className="k-table">
            <thead>
              <tr>
                <th className="tight">Severity</th>
                <th>Issue</th>
                <th>Agent</th>
                <th className="num">Times</th>
                <th className="tight">Last seen</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f: any) => (
                <tr key={f.id}>
                  <td className="tight"><SeverityPill value={f.severity} /></td>
                  <td>
                    <Link className="k-name" href={`/app/findings/${f.id}`}>{f.title}</Link>
                    <span className="sub">{findingTypeInfo(f.type).label}</span>
                  </td>
                  <td>
                    {f.agent_slug ? <Link href={`/app/agents/${encodeURIComponent(f.agent_slug)}`}>{f.agent_slug}</Link> : <span className="k-muted">—</span>}
                  </td>
                  <td className="num">{num(f.occurrences || 1)}</td>
                  <td className="tight muted">{ago(f.last_seen_at || f.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{status === "open" ? "No open issues." : "Nothing here."}</Empty>
        )}
      </Card>
    </>
  );
}
