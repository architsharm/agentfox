import { Suspense } from "react";
import Link from "next/link";
import { api, safeApi, ApiError, apiErrorProps } from "@/lib/product/api";
import { ApiDown } from "@/components/ui";
import { Card, Empty, Pill } from "@/components/kit";
import { RepoTable } from "@/components/product/RepoTable";
import { TokenManager } from "@/components/product/TokenManager";
import { CodeSnippet } from "@/components/product/start/CodeSnippet";
import { ConnCard } from "@/components/product/start/ConnCard";
import { IntegrationPicker } from "@/components/product/start/StartFlow";
import { publicApiBase } from "@/lib/env";

/**
 * Settings > Connections and Settings > API keys (/app/settings?tab=connect and
 * ?tab=tokens). They lived at /app/start, beside the old Get started checklist;
 * that URL now redirects here.
 */

// --- Settings > Connections -------------------------------------------------------

type Repo = {
  full_name: string;
  private: boolean;
  default_branch: string;
  description: string;
  updated_at: string;
};

export async function ConnectTab({
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
  // Without an OAuth app, "Connect GitHub" can only fail; say so instead of offering it.
  const githubReady = Boolean(process.env.GITHUB_CLIENT_ID);

  return (
    <>
      {scanError && <div className="error">Scan failed: {scanError}</div>}
      {scan && <ScanResult title={`Scan of ${scan.repo_full_name}`} scan={scan} />}
      {hostedScan && <ScanResult title={`Scan of ${hostedScan.summary?.endpoint_url || "your API"}`} scan={hostedScan} />}

      {/* The cards' titles are h3s; screen readers need an h2 above them. */}
      <h2 className="sr-only">Connections</h2>
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
            Calls need an API key. <Link href="/app/settings?tab=tokens">Create one</Link>.
          </p>
        </ConnCard>

        <ConnCard
          id="github"
          title="GitHub"
          status={
            github ? (
              <Pill tone="ok">Connected</Pill>
            ) : githubReady ? (
              <Pill tone="outline">Not connected</Pill>
            ) : (
              <Pill tone="outline">Not configured on this server</Pill>
            )
          }
          text="Find agents in your repositories. Code is read, never run."
          action={
            github ? (
              <a href="#repos" className="k-btn-primary">
                Choose a repository
              </a>
            ) : githubReady ? (
              <a href="/api/auth/github/login" className="k-btn-primary">
                Connect GitHub
              </a>
            ) : undefined
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
          <Link href="/app/projects" className="k-btn-primary">
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

export function TokensTab() {
  return (
    <>
      <p className="sub" style={{ marginTop: 16 }}>
        For your agents, the CLI and the SDK. Send one as a bearer token; the CLI reads{" "}
        <code className="mono">AGENTFOX_API_KEY</code>.
      </p>
      <TokenManager />
    </>
  );
}
