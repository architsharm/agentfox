import type { Metadata } from "next";
import { Suspense, type ReactNode } from "react";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { redirect } from "next/navigation";
import { api, safeApi, ApiError, apiErrorProps } from "@/lib/product/api";
import { ApiDown } from "@/components/ui";
import { SETTINGS_TABS } from "@/components/product/AreaTabs";
import { Card, Empty, Header, Pill, Tabs } from "@/components/kit";
import { RepoTable } from "@/components/product/RepoTable";
import { PackMode } from "@/components/product/policies/PackMode";
import { TokenManager } from "@/components/product/TokenManager";
import { CodeSnippet } from "@/components/product/start/CodeSnippet";
import { ConnCard } from "@/components/product/start/ConnCard";
import { FirstRequestWatcher } from "@/components/product/start/FirstRequestWatcher";
import {
  CreateKey,
  IntegrationPicker,
  RegisterAgent,
  StartKeyProvider,
  StepDetails,
  TestRequest,
} from "@/components/product/start/StartFlow";
import { publicApiBase } from "@/lib/env";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export async function generateMetadata({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string }>;
}): Promise<Metadata> {
  const { tab } = await searchParams;
  if (tab === "connect") return appPageMetadata("Connections");
  if (tab === "tokens") return appPageMetadata("API keys");
  return appPageMetadata("Get started", "Register an agent, create a key, send the first request, and turn enforcement on.");
}

export const dynamic = "force-dynamic";

const TABS = ["checklist", "connect", "tokens"];

/**
 * Get started at the bare URL, and two Settings tabs, Connections (?tab=connect)
 * and API keys (?tab=tokens), at the URLs they have always had.
 *
 * Every data read sits behind a Suspense boundary, so the frame paints at once and
 * the slow parts (a GitHub repo listing is a call to GitHub) arrive on their own.
 */
export default async function Start({
  searchParams,
}: {
  searchParams: Promise<{
    tab?: string;
    agent?: string;
    scan_run_id?: string;
    hosted_scan_run_id?: string;
    scan_error?: string;
  }>;
}) {
  const { tab: rawTab, agent, scan_run_id, hosted_scan_run_id, scan_error } = await searchParams;
  // "What's in here" was a tab here and is now two sections on the Glossary.
  if (rawTab === "map") redirect("/app/glossary#areas");
  const tab = TABS.includes(rawTab || "") ? rawTab! : "checklist";

  if (tab === "connect" || tab === "tokens") {
    return (
      <>
        <Header title="Settings" />
        <Tabs items={SETTINGS_TABS} active={tab} />
        {tab === "connect" ? (
          <ConnectTab scanRunId={scan_run_id} hostedScanRunId={hosted_scan_run_id} scanError={scan_error} />
        ) : (
          <TokensTab />
        )}
      </>
    );
  }

  return (
    <>
      <Header title="Get started" />
      <Suspense fallback={<StepsSkeleton />}>
        <Checklist agentParam={agent} gateway={publicApiBase()} />
      </Suspense>
    </>
  );
}

// --- Get started ---------------------------------------------------------------

type Step = { id: string; title: string; done: boolean; command: string; detail: string };

async function Checklist({ agentParam, gateway }: { agentParam?: string; gateway: string }) {
  let onboarding: any;
  try {
    onboarding = await api("/api/onboarding");
  } catch (e: any) {
    return <ApiDown {...apiErrorProps(e)} />;
  }
  const { steps, completed, total, next, counts } = onboarding as {
    steps: Step[];
    completed: number;
    total: number;
    next: Step | null;
    counts: any;
  };
  const agents: string[] = onboarding.agents || [];
  const agent = agentParam && agents.includes(agentParam) ? agentParam : agents[0] || null;
  const agentHref = (suffix = "") => (agent ? `/app/agents/${encodeURIComponent(agent)}${suffix}` : "/app/agents");

  const body: Record<string, ReactNode> = {
    agent: <RegisterAgent agents={agents} current={agent} />,
    key: <CreateKey done={steps.find((s) => s.id === "key")?.done ?? false} />,
    instrument: (
      <>
        <IntegrationPicker gateway={gateway} agent={agent} />
        <TestRequest agent={agent} />
        <FirstRequestWatcher initial={counts} />
      </>
    ),
    protect: agent ? (
      <div className="gs-row">
        <Link href={agentHref("/protect")} className="k-btn-primary">
          Protect {agent}
        </Link>
        <Link href={agentHref("?tab=access")} className="k-btn">
          Grant tools
        </Link>
      </div>
    ) : (
      <NeedsAgent />
    ),
    boundary: agent ? (
      <div className="gs-row">
        <Link href={agentHref("?tab=access#boundary")} className="k-btn-primary">
          Declare a boundary
        </Link>
      </div>
    ) : (
      <NeedsAgent />
    ),
    enforce: steps.find((s) => s.id === "enforce")?.done ? (
      <div className="gs-row">
        <Link href="/app/policies" className="k-btn">
          Open policies
        </Link>
      </div>
    ) : (
      <Suspense fallback={<div className="k-skel" style={{ height: 32, width: 220 }} />}>
        <EnforceControl />
      </Suspense>
    ),
  };

  return (
    <StartKeyProvider>
      <div className="progress-line">
        <div className="progress-track">
          <span style={{ width: `${(completed / total) * 100}%` }} />
        </div>
        <span className="small muted">
          {completed} of {total} done
        </span>
      </div>

      <ol className="gs-steps">
        {steps.map((step, i) => (
          <li key={step.id} className={step.done ? "done" : next?.id === step.id ? "now" : ""}>
            <StepDetails
              defaultOpen={next?.id === step.id || (!next && i === 0)}
              summary={
                <>
                  <span className="gs-marker" aria-hidden>
                    {step.done ? "✓" : i + 1}
                  </span>
                  <span className="gs-title">{step.title}</span>
                  {step.done ? <Pill tone="ok">Done</Pill> : next?.id === step.id ? <Pill tone="info">Next</Pill> : null}
                </>
              }
            >
              <div className="gs-body">
                <p className="gs-detail">{step.detail}</p>
                {body[step.id]}
                <p className="gs-cli">
                  Or from the command line: <code>{agent ? step.command.replace("my-agent", agent) : step.command}</code>
                </p>
              </div>
            </StepDetails>
          </li>
        ))}
      </ol>

      <p className="small muted">
        Not ready to change code? <Link href="/app/start?tab=connect">Scan a repository or an API</Link> to find
        your agents first.
      </p>
    </StartKeyProvider>
  );
}

function NeedsAgent() {
  return <p className="k-muted gs-note">Register an agent first.</p>;
}

/** The enforce step's control, read only when that step is still open. */
async function EnforceControl() {
  const baseline = await safeApi<any>("/api/policies/baseline", null);
  if (!baseline) {
    return (
      <Link href="/app/policies" className="k-btn-primary">
        Choose what to enforce
      </Link>
    );
  }
  return (
    <PackMode
      packKey="baseline"
      mode={baseline.mode}
      body={baseline.live_body || baseline.body || ""}
      version={baseline.bound_version ?? baseline.latest_version ?? null}
    />
  );
}

function StepsSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading">
      <div className="k-skel" style={{ height: 8, width: "100%", margin: "4px 0 22px" }} />
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="k-skel" style={{ height: 44, marginBottom: 8 }} />
      ))}
    </div>
  );
}

// --- Settings > Connections -------------------------------------------------------

type Repo = {
  full_name: string;
  private: boolean;
  default_branch: string;
  description: string;
  updated_at: string;
};

async function ConnectTab({
  scanRunId,
  hostedScanRunId,
  scanError,
}: {
  scanRunId?: string;
  hostedScanRunId?: string;
  scanError?: string;
}) {
  const gateway = publicApiBase();
  const [onboarding, scan, hostedScan] = await Promise.all([
    safeApi<any>("/api/onboarding", null),
    scanRunId ? safeApi<any>(`/api/integrations/github/scans/${scanRunId}`, null) : null,
    hostedScanRunId ? safeApi<any>(`/api/integrations/github/scans/${hostedScanRunId}`, null) : null,
  ]);
  const counts = onboarding?.counts || {};
  const github = Number(counts.github_connections || 0) > 0;
  const traffic = Number(counts.traces || 0) > 0;
  const hostedScans = Number(counts.hosted_api_scans || 0);

  return (
    <>
      {scanError && <div className="error">Scan failed: {scanError}</div>}
      {scan && <ScanResult title={`Scan of ${scan.repo_full_name}`} scan={scan} />}
      {hostedScan && <ScanResult title={`Scan of ${hostedScan.summary?.endpoint_url || "your API"}`} scan={hostedScan} />}

      <div className="conn-grid">
        <ConnCard
          title="Gateway"
          status={traffic ? <Pill tone="ok">Receiving traffic</Pill> : <Pill tone="outline">No traffic yet</Pill>}
          text="The endpoint your agents call for a verdict. OpenAI-compatible clients use it as their base URL."
          expandLabel="Show endpoint"
        >
          <CodeSnippet label="API base" code={gateway} />
          <CodeSnippet label="OpenAI-compatible base URL" code={`${gateway}/v1`} />
          <p className="k-muted gs-note">
            Calls need an API key. <Link href="/app/start?tab=tokens">Create one</Link>.
          </p>
        </ConnCard>

        <ConnCard
          id="github"
          title="GitHub"
          status={github ? <Pill tone="ok">Connected</Pill> : <Pill tone="outline">Not connected</Pill>}
          text="Find agents in your repositories. Code is read, never run."
          action={
            github ? (
              <a href="#repos" className="k-btn-primary">
                Choose a repository
              </a>
            ) : (
              <a href="/api/auth/github/login" className="k-btn-primary">
                Connect GitHub
              </a>
            )
          }
        />

        <ConnCard
          title="Hosted API"
          status={hostedScans ? <Pill tone="ok">{hostedScans} scanned</Pill> : <Pill tone="outline">None yet</Pill>}
          text="Read an API's OpenAPI document to find the operations an agent could call. The API is never called."
          expandLabel="Add an API"
        >
          <HostedApiForm />
        </ConnCard>

        <ConnCard
          title="SDK"
          status={<Pill tone="neutral">Python, TypeScript</Pill>}
          text="Check each message and tool call from your agent's own code."
          expandLabel="Show setup"
        >
          <IntegrationPicker gateway={gateway} agent={null} paths={["python", "typescript", "http"]} />
        </ConnCard>

        <ConnCard
          title="Coding agents"
          status={<Pill tone="neutral">Claude Code, Codex</Pill>}
          text="Hooks check shell commands, file edits and MCP calls before they run."
          expandLabel="Show setup"
        >
          <IntegrationPicker gateway={gateway} agent={null} paths={["claude-code", "codex"]} />
        </ConnCard>

        <ConnCard
          title="OpenTelemetry"
          status={<Pill tone="neutral">Observe only</Pill>}
          text="Send the traces you already export over OTLP/HTTP. Agents found this way show up for review."
          expandLabel="Show setup"
        >
          <IntegrationPicker gateway={gateway} agent={null} paths={["otlp"]} />
        </ConnCard>
      </div>

      {github && (
        <Suspense
          fallback={
            <Card title="Repositories">
              <div className="k-skel" style={{ height: 120 }} />
            </Card>
          }
        >
          <Repos />
        </Suspense>
      )}
    </>
  );
}

/** The repo picker. A call to GitHub, so it streams in after the cards. */
async function Repos() {
  let repos: { github_login: string; repos: Repo[] } | null = null;
  try {
    repos = await api("/api/integrations/github/repos");
  } catch (e: any) {
    if (e instanceof ApiError && e.status === 404) return null;
    return <ApiDown {...apiErrorProps(e)} />;
  }
  return (
    <div id="repos">
      <Card
        title={`Repositories of ${repos!.github_login}`}
        hint="Scanning reads code structure to find AI frameworks. Nothing is run or changed, and nothing goes live until you approve it."
        action={<a href="/api/auth/github/login">Reconnect</a>}
        flush
      >
        {repos!.repos.length === 0 ? (
          <Empty>No repositories visible to this GitHub account.</Empty>
        ) : (
          <RepoTable repos={repos!.repos} />
        )}
      </Card>
    </div>
  );
}

function ScanResult({ title, scan }: { title: string; scan: any }) {
  const sites = scan.summary?.sites
    ? Object.values(scan.summary.sites).reduce((a: number, b: any) => a + Number(b), 0)
    : null;
  return (
    <Card title={title} action={<Pill tone={scan.status === "completed" ? "ok" : "neutral"}>{scan.status}</Pill>}>
      <div className="small">
        {scan.summary?.frameworks && <div>Frameworks: {scan.summary.frameworks.join(", ") || "none detected"}</div>}
        {sites !== null && <div>Operations found: {sites}</div>}
        <div>
          Proposed: {scan.summary?.agents_proposed?.length || 0} agent(s), {scan.summary?.policies_proposed?.length || 0}{" "}
          {scan.summary?.policies_proposed?.length === 1 ? "policy" : "policies"}
        </div>
        <div className="gs-row" style={{ marginTop: 8 }}>
          <Link href="/app/agents" className="k-btn-primary">
            Review agents
          </Link>
          <Link href="/app/policies" className="k-btn">
            Review policies
          </Link>
        </div>
      </div>
    </Card>
  );
}

function HostedApiForm() {
  return (
    <form action="/api/integrations/hosted-api/scan" method="POST" className="k-form">
      <div className="k-field">
        <label htmlFor="h-endpoint">API endpoint</label>
        <input id="h-endpoint" className="k-input" type="url" name="endpoint_url" placeholder="https://api.yourcompany.com" required />
      </div>
      <div className="k-field">
        <label htmlFor="h-spec">OpenAPI spec URL</label>
        <input id="h-spec" className="k-input" type="url" name="openapi_spec_url" placeholder="https://api.yourcompany.com/openapi.json (optional)" />
      </div>
      <div className="k-field">
        <label htmlFor="h-docs">Docs URL</label>
        <input id="h-docs" className="k-input" type="url" name="docs_url" placeholder="https://docs.yourcompany.com (optional)" />
      </div>
      <div className="k-field">
        <label htmlFor="h-purpose">What it does</label>
        <input id="h-purpose" className="k-input" type="text" name="purpose" placeholder="Internal support-ticket assistant" />
      </div>
      <div>
        <button type="submit" className="k-btn-primary">
          Scan the API
        </button>
      </div>
    </form>
  );
}

function TokensTab() {
  return (
    <>
      <p className="sub" style={{ marginTop: 16 }}>
        For your agents, the CLI and the SDK. Send one as a bearer token; the CLI reads{" "}
        <code className="mono">AGENTFOX_API_TOKEN</code>.
      </p>
      <TokenManager />
    </>
  );
}
