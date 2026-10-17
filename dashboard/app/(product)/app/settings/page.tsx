import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { appPageMetadata } from "@/lib/site";
import { api, apiErrorProps, safeApi } from "@/lib/product/api";
import { hasFeature } from "@/lib/product/edition";
import { ApiDown } from "@/components/ui";
import { EnterpriseOnly } from "@/components/product/EnterpriseOnly";
import { Retention } from "@/components/product/Retention";
import { Card, Empty, Header, Pill, Tabs, ago } from "@/components/kit";
import { Act } from "@/components/kit/Act";
import { AreaTabs, SETTINGS_TABS } from "@/components/product/AreaTabs";
import { SlackForm } from "@/ee/SlackForm";
import { CodeSnippet } from "@/components/product/start/CodeSnippet";
import { publicApiBase } from "@/lib/env";

export const metadata: Metadata = appPageMetadata("Settings");
export const dynamic = "force-dynamic";

/**
 * Settings is one sidebar row over several pages that share a tab bar. Its own
 * URL holds the Alerts tab; without a tab it lands on the first one, Connections.
 */
export default async function Settings({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const { tab } = await searchParams;
  // Checks was a Settings tab that only linked to Policies; it lives there now.
  if (tab === "checks") redirect("/app/policies?tab=checks");
  if (tab === "retention") return <RetentionTab />;
  if (tab !== "alerts") redirect("/app/start?tab=connect");
  if (!(await hasFeature("monitoring"))) {
    return (
      <>
        <Header title="Settings" />
        <AreaTabs tabs={SETTINGS_TABS} active="alerts" />
        <EnterpriseOnly feature="monitoring" />
      </>
    );
  }

  const [slack, monitors] = await Promise.all([
    safeApi<any>("/api/alerts/slack", { configured: false }),
    safeApi<any>("/api/monitors", { monitors: [], kinds: {} }),
  ]);
  const gateway = publicApiBase();

  return (
    <>
      <Header title="Settings" />
      <AreaTabs tabs={SETTINGS_TABS} active="alerts" />
      <Card
        title="Slack"
        hint="New issues at or above the chosen severity are posted to this channel."
        action={slack.configured ? <Pill tone="ok">Connected</Pill> : <Pill tone="outline">Not connected</Pill>}
      >
        {slack.egress_allowed === false && <div className="k-muted" style={{ marginBottom: 8 }}>Outbound messages are switched off for this deployment.</div>}
        <SlackForm configured={Boolean(slack.configured)} minSeverity={slack.min_severity} />
      </Card>

      <Card title="Monitors" hint="Connected repos, APIs and MCP servers that are re-checked on a schedule." flush>
        {monitors.monitors?.length ? (
          <ul className="k-list">
            {monitors.monitors.map((m: any) => (
              <li key={m.id}>
                <div className="k-list-main">
                  <span className="k-name">{m.name || m.target || m.id}</span>
                  <span className="muted">
                    {m.kind?.replace(/_/g, " ")} · last run {ago(m.last_run_at)}
                  </span>
                </div>
                <div className="k-list-end">
                  {!m.enabled ? <Pill tone="outline">Paused</Pill> : <Pill tone="ok">Active</Pill>}
                  <Act url={`/api/monitors/${m.id}/run`} className="k-btn" done="Started">Run now</Act>
                  <Act url={`/api/monitors/${m.id}/${!m.enabled ? "resume" : "pause"}`} className="k-btn-ghost">
                    {!m.enabled ? "Resume" : "Pause"}
                  </Act>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>Nothing is being monitored. Connect a repo or API to start.</Empty>
        )}
      </Card>

      <Card title="SIEM export" hint="Decisions and findings in a format your SIEM can ingest.">
        <CodeSnippet code={`curl -s ${gateway}/api/export/siem \\\n  -H "Authorization: Bearer $AGENTFOX_API_TOKEN"`} />
      </Card>
    </>
  );
}

/** How long each class of recorded data is kept, and legal holds (open core). */
async function RetentionTab() {
  let retention: any;
  try {
    retention = await api("/api/retention");
  } catch (e: any) {
    return (
      <>
        <Header title="Settings" />
        <AreaTabs tabs={SETTINGS_TABS} active="retention" />
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }
  return (
    <>
      <Header title="Settings" />
      <AreaTabs tabs={SETTINGS_TABS} active="retention" />
      <Retention retention={retention} />
    </>
  );
}
