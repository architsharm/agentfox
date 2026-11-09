import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { appPageMetadata } from "@/lib/site";
import { api, apiErrorProps, safeApi } from "@/lib/product/api";
import { hasFeature } from "@/lib/product/edition";
import { ApiDown } from "@/components/ui";
import { EnterpriseOnly } from "@/components/product/EnterpriseOnly";
import { DeleteAccount, Retention } from "@/components/product/Retention";
import { Card, Empty, Header, Pill, Tabs, ago } from "@/components/kit";
import { Act } from "@/components/kit/Act";
import { NoticeToast } from "@/components/product/NoticeToast";
import { AreaTabs, SETTINGS_TABS } from "@/components/product/AreaTabs";
import { SlackForm } from "@/ee/SlackForm";
import { CodeSnippet } from "@/components/product/start/CodeSnippet";
import { publicApiBase } from "@/lib/env";
import { FeaturesEditor } from "@/components/product/features/FeaturesEditor";
import { ConnectTab, TokensTab } from "@/components/product/settings/Connections";
import { MembersTab } from "@/components/product/settings/Members";
import {
  AdvancedJudges,
  AdvancedNav,
  AdvancedPacks,
  AdvancedTuning,
  type AdvancedSection,
} from "@/components/product/policies/advanced";

export async function generateMetadata({ searchParams }: { searchParams: Promise<{ tab?: string }> }): Promise<Metadata> {
  const { tab } = await searchParams;
  const label = SETTINGS_TABS.find((t) => t.key === (tab || "connect"))?.label;
  return appPageMetadata(label ? `Settings · ${label}` : "Settings");
}
export const dynamic = "force-dynamic";

/**
 * Settings is one sidebar row over several pages that share a tab bar. Its own URL
 * holds Connections (the default), API keys, Members, Detection, Alerts and
 * Retention; Verified sources and Data access are pages of their own under the same bar.
 */
export default async function Settings({
  searchParams,
}: {
  searchParams: Promise<{
    tab?: string;
    sec?: string;
    agent?: string;
    review_notice?: string;
    review_error?: string;
    scan_run_id?: string;
    hosted_scan_run_id?: string;
    scan_error?: string;
  }>;
}) {
  const { tab = "connect", sec, agent, review_notice, review_error, scan_run_id, hosted_scan_run_id, scan_error } = await searchParams;
  // Checks was a Settings tab that only linked to Policies; it lives there now.
  if (tab === "checks") redirect("/app/policies?tab=checks");
  // Retention and Detection hold plain form posts (retention, legal holds, purge,
  // judges, suppressions, feedback) that redirect back here with their outcome.
  const toast = <NoticeToast notice={review_notice} error={review_error} />;
  if (tab === "retention") return <>{toast}<RetentionTab /></>;
  if (tab === "detection") return <>{toast}<DetectionTab sec={sec} agent={agent} /></>;
  if (tab === "connect" || tab === "tokens" || tab === "members") {
    return (
      <>
        {toast}
        <Header title="Settings" />
        <AreaTabs tabs={SETTINGS_TABS} active={tab} />
        {tab === "connect" ? (
          <ConnectTab scanRunId={scan_run_id} hostedScanRunId={hosted_scan_run_id} scanError={scan_error} />
        ) : tab === "tokens" ? (
          <TokensTab />
        ) : (
          <MembersTab />
        )}
      </>
    );
  }
  if (tab !== "alerts") redirect("/app/settings?tab=connect");
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
        hint="New issues at or above the chosen severity, and every call held for approval, are posted to this channel."
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
        <CodeSnippet code={`curl -s ${gateway}/api/export/siem \\\n  -H "Authorization: Bearer $AGENTFOX_API_KEY"`} />
      </Card>
    </>
  );
}

/** How long each class of recorded data is kept, legal holds (open core), and deleting your account. */
async function RetentionTab() {
  let retention: any;
  const me = await safeApi<any>("/api/me", null);
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
      <DeleteAccount me={me} />
    </>
  );
}

const DETECTION_SECTIONS: AdvancedSection[] = ["levels", "packs", "tuning", "judges"];

/**
 * How the workspace detects things, in one place: protection levels for every
 * project, the installed packs, detector tuning and suppressions, and which AI
 * judges may decide and what data may leave. Each section is the component it
 * was before it moved here (workspace Features, and Policies' hidden tabs).
 */
async function DetectionTab({ sec, agent }: { sec?: string; agent?: string }) {
  const section = DETECTION_SECTIONS.find((s) => s === sec) ?? "levels";
  return (
    <>
      <Header title="Settings" />
      <AreaTabs tabs={SETTINGS_TABS} active="detection" />
      <AdvancedNav section={section} agent={agent} />
      {section === "levels" && <ProtectionLevels />}
      {section === "packs" && <AdvancedPacks agent={agent} />}
      {section === "tuning" && <AdvancedTuning agent={agent} />}
      {section === "judges" && <AdvancedJudges />}
    </>
  );
}

/** Each protection's level for every project, and whether projects may lower it. */
async function ProtectionLevels() {
  let features: any;
  try {
    features = await api("/api/features");
  } catch (e: any) {
    return <ApiDown {...apiErrorProps(e)} />;
  }
  return <FeaturesEditor initial={features} />;
}
