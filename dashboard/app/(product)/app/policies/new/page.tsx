import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { safeApi } from "@/lib/product/api";
import { ActionPill, Card, Empty, Header, ModePill, OutcomePill, Pill, Tabs, href } from "@/components/kit";
import { CustomRule } from "@/components/product/policies/CustomRule";
import { DescribeRule } from "@/components/product/policies/DescribeRule";
import { ImportGuard } from "@/components/product/policies/ImportGuard";
import { LibraryPacks } from "@/components/product/policies/LibraryPacks";
import { SURFACES, WOULD, outcomeOf, ruleTitle } from "@/lib/product/vocab";

export const metadata: Metadata = appPageMetadata("Add rule");
export const dynamic = "force-dynamic";

type SP = Record<string, string | undefined>;

/**
 * Every way to add a rule, in one place: words and topics, approval limits written
 * as a policy sentence, tool access, a pack, an import from another tool — or start
 * from a run that went wrong.
 */
export default async function NewRule({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const tabs = [
    ...(sp.run ? [{ key: "run", label: "From this run" }] : []),
    { key: "custom", label: "Words & topics" },
    { key: "describe", label: "Approval limits" },
    { key: "access", label: "Tool access" },
    { key: "packs", label: "Packs" },
    { key: "import", label: "Import" },
  ];
  const tab = tabs.some((t) => t.key === sp.from) ? sp.from! : tabs[0].key;
  const keep = { run: sp.run, agent: sp.agent };

  return (
    <>
      <Header back={{ href: "/app/policies", label: "Policies" }} title={sp.agent ? `Add rule for ${sp.agent}` : "Add rule"} />
      <Tabs items={tabs.map((t) => ({ ...t, href: href("/app/policies/new", { ...keep, from: t.key }) }))} active={tab} />
      {tab === "run" && sp.run && <FromRun id={sp.run} />}
      {tab === "describe" && (
        <Card>
          <DescribeRule agent={sp.agent} />
        </Card>
      )}
      {tab === "custom" && (
        <Card>
          <CustomRule agent={sp.agent} />
        </Card>
      )}
      {tab === "packs" && <LibraryPacks />}
      {tab === "import" && (
        <Card title="From Guardrails AI">
          <ImportGuard />
        </Card>
      )}
      {tab === "access" && <ToolAccess agent={sp.agent} />}
    </>
  );
}

async function FromRun({ id }: { id: string }) {
  const d = await safeApi<any>(`/api/traces/${encodeURIComponent(id)}`, null);
  if (!d) return <Card><Empty>Run not found.</Empty></Card>;
  const t = d.trace;
  const decisions: any[] = d.decisions || [];
  const fired = decisions.flatMap((x) => (x.rules_fired || []).map((r: any) => ({ ...r, decision: x })));
  const watching = fired.filter((r) => r.mode === "observe" && ["block", "escalate", "redact", "mask", "tokenize"].includes(r.effect));
  const unique = Array.from(new Map(watching.map((r) => [r.rule_id, r])).values());
  const tools = Array.from(new Set(decisions.map((x) => x.tool).filter(Boolean)));
  const what = t.intent || tools.join(", ") || Array.from(new Set(decisions.map((x) => SURFACES[x.surface] || x.surface))).join(" · ");

  return (
    <>
      <Card>
        <div className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
          <Link className="k-name" href={`/app/traces/${id}`}>{what || "Run"}</Link>
          <OutcomePill outcome={outcomeOf(t.verdict)} />
          {t.agent && <Pill tone="outline">{t.agent}</Pill>}
        </div>
      </Card>

      {unique.length > 0 && (
        <Card title="Start enforcing a rule that only watched" flush>
          <ul className="k-list">
            {unique.map((r) => (
              <li key={r.rule_id}>
                <div className="k-list-main">
                  <span className="k-name">{ruleTitle(r.rule_id)}</span>
                  <span className="muted">{WOULD[r.effect]} this run</span>
                </div>
                <div className="k-list-end">
                  <ActionPill effect={r.effect} />
                  <ModePill mode="observe" />
                  <Link className="k-btn-primary" href={href(`/app/policies/rules/${encodeURIComponent(r.rule_id)}`, { tab: "tune" })}>
                    Set up
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {tools.length > 0 && t.agent && (
        <Card title="Change what the agent may do" flush>
          <ul className="k-list">
            {tools.map((tool) => (
              <li key={tool}>
                <div className="k-list-main">
                  <span className="k-mono">{tool}</span>
                  <span className="muted">Require approval, add a limit, or remove it for {t.agent}</span>
                </div>
                <Link className="k-btn" href={href(`/app/agents/${encodeURIComponent(t.agent)}`, { tab: "access", grant: tool })}>
                  Open access
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Or describe the rule">
        <DescribeRule agent={t.agent || undefined} />
      </Card>
    </>
  );
}

async function ToolAccess({ agent }: { agent?: string }) {
  const agents = await safeApi<any>("/api/agents", { agents: [] });
  const list = (agents.agents || []).filter((a: any) => a.status !== "draft" && (!agent || a.slug === agent));
  return (
    <Card flush>
      {list.length ? (
        <ul className="k-list">
          {list.map((a: any) => (
            <li key={a.slug}>
              <div className="k-list-main">
                <span className="k-name">{a.name || a.slug}</span>
                <span className="muted">{a.declared_tools?.length || 0} tools declared</span>
              </div>
              <Link className="k-btn" href={href(`/app/agents/${encodeURIComponent(a.slug)}`, { tab: "access" })}>
                Edit access
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <Empty>No agents.</Empty>
      )}
    </Card>
  );
}
