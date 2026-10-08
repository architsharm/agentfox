import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { redirect } from "next/navigation";
import { api, safeApi, ApiError, apiErrorProps } from "@/lib/product/api";
import { ApiDown, InfoTip, Panel, Empty } from "@/components/ui";
import { SETTINGS_TABS } from "@/components/product/AreaTabs";
import { Header, Tabs } from "@/components/kit";
import { RepoTable } from "@/components/product/RepoTable";
import { TokenManager } from "@/components/product/TokenManager";
import { ConnectGuide, PATHS, type PathKey } from "@/components/product/start/ConnectGuide";
import { FirstRequestWatcher } from "@/components/product/start/FirstRequestWatcher";
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
  return appPageMetadata(
    "Get started",
    "Connect a repository or a hosted API, mint a token, and see the first trace.",
  );
}

export const dynamic = "force-dynamic";

const TABS = ["checklist", "connect", "tokens"];

const inputStyle = {
  width: "100%",
  padding: "6px 9px",
  borderRadius: 6,
  border: "1px solid var(--border)",
  background: "var(--panel-2)",
  color: "var(--text)",
  fontSize: 13,
  fontFamily: "inherit",
} as const;

/**
 * The id is derived from the field's own `name` (unique within a form, and
 * stable between server and client render — `useId` is not available in a
 * Server Component) so the label is actually associated with its input rather
 * than just sitting above it. Without that, a screen reader announces four
 * unlabelled text boxes and clicking the label does nothing.
 */
function Field({ label, ...props }: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  const id =
    props.id ||
    `field-${String(props.name || label).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`;
  return (
    <div>
      <label htmlFor={id} className="small muted" style={{ display: "block", marginBottom: 4 }}>
        {label}
      </label>
      <input id={id} style={inputStyle} {...props} />
    </div>
  );
}

/**
 * The setup checklist ("Get started") at the bare URL, and two Settings tabs —
 * Connections (?tab=connect) and API keys (?tab=tokens) — at the URLs they have
 * always had, so existing links and the checklist's own buttons keep working.
 */
export default async function Start({
  searchParams,
}: {
  searchParams: Promise<{
    tab?: string;
    path?: string;
    scan_run_id?: string;
    hosted_scan_run_id?: string;
    scan_error?: string;
  }>;
}) {
  const { tab: rawTab, path: rawPath, scan_run_id, hosted_scan_run_id, scan_error } = await searchParams;
  // "What's in here" was a tab here and is now two sections on the Glossary,
  // which is where the rest of the reference material lives. Without this, a
  // bookmarked ?tab=map falls through to Checklist and silently shows the wrong
  // page instead of the one that was asked for.
  if (rawTab === "map") redirect("/app/glossary#areas");
  const tab = TABS.includes(rawTab || "") ? rawTab! : "checklist";

  // Connect and API keys are Settings now: same URLs, shown under the Settings
  // tab bar so they read as part of that area. What is left at the bare URL is
  // the setup checklist — the "Get started" row.
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

  // Connect, then see it arrive, then the rest of setup — the order a developer
  // actually does it in. The checklist is unchanged; it moved below the two
  // steps that get the first request through.
  const path: PathKey = PATHS.some((p) => p.key === rawPath) ? (rawPath as PathKey) : "http";
  const onboarding = await safeApi<any>("/api/onboarding", null);

  return (
    <>
      <Header title="Get started" />

      <h2 className="k-section">1. Connect your agent</h2>
      <ConnectGuide path={path} gateway={publicApiBase()} />

      <h2 className="k-section">2. See it arrive</h2>
      {onboarding?.counts ? (
        <FirstRequestWatcher initial={onboarding.counts} />
      ) : (
        <p className="small muted">Setup status is unavailable right now.</p>
      )}

      <h2 className="k-section">3. Finish setup</h2>
      <ChecklistTab />
    </>
  );
}

async function ChecklistTab() {
  let onboarding: any;
  try {
    onboarding = await api("/api/onboarding");
  } catch (e: any) {
    return <ApiDown {...apiErrorProps(e)} />;
  }

  const { steps, completed, total, next, counts, connected } = onboarding;

  return (
    <>
      <div className="progress-line">
        <div className="progress-track">
          <span style={{ width: `${(completed / total) * 100}%` }} />
        </div>
        <span className="small muted">
          {completed} of {total} done
          {!connected && " · nothing is sending traffic yet"}
        </span>
      </div>

      <ol className="steps">
        {steps.map((step: any, i: number) => (
          <li key={step.id} className={step.done ? "done" : next?.id === step.id ? "now" : ""}>
            <span className="marker">{step.done ? "✓" : i + 1}</span>
            <div className="step-body">
              <div className="step-title">
                {step.title}
                {next?.id === step.id && <span className="tag accent">next</span>}
              </div>
              {step.id === "connect" ? (
                <Link href="/app/start?tab=connect" className="btn-scan" style={{ display: "inline-flex", marginBottom: 6 }}>
                  {step.done ? "Manage connection" : "Connect →"}
                </Link>
              ) : step.id === "boundary" ? (
                <Link href="/app/agents" className="cta" style={{ display: "inline-block", marginBottom: 6 }}>
                  {step.done ? "Manage knowledge boundaries →" : "Pick an agent to declare a boundary for →"}
                </Link>
              ) : (
                <code className="step-cmd">{step.command}</code>
              )}
              <div className="small muted">{step.detail}</div>
            </div>
          </li>
        ))}
      </ol>

      <h2>What is connected</h2>
      <div className="cards">
        <Mini n={counts.github_connections} label="github accounts" />
        <Mini n={counts.agents} label="agents" />
        <Mini n={counts.traces} label="traces" />
        <Mini n={counts.decisions} label="decisions" />
        <Mini n={counts.enforcing} label="enforced" />
        <Mini n={counts.boundaries} label="knowledge boundaries" />
        <Mini n={counts.sources} label="tiered sources" />
      </div>

      <div className="note-panel">
        <strong>Content policies start in observe.</strong> Prompt injection, PII and
        safety enforce only once you promote them.{" "}
        <strong>Tool containment ships enforcing from install.</strong>{" "}
        <InfoTip text="A governance layer that starts refusing production traffic because someone added an import is indefensible, however correct its policy — so the content-based policies start in observe and only enforce once you promote them in the last step. Tool containment is different: it reasons about the action itself (which tool, with what arguments, from what provenance), not about prompt text, so it is much less prone to false positives. It ships enforcing on purpose, because it is the one control meant to hold even when everything upstream of it — including a content filter — got fooled." />{" "}
        See the <Link href="/app/policies">Rules page</Link>.
      </div>

      <div className="note-panel">
        <strong>Not every detector is on by default.</strong>{" "}
        <InfoTip text="Microsoft Presidio for PII, IBM Granite Guardian for safety, NVIDIA NeMo Guardrails and Guardrails AI need extra install steps — a package extra, a self-hosted deployment, or licence acceptance — and are not running in every deployment. Step 7 does not on its own give you full coverage." />{" "}
        Check what is active for yours on the{" "}
        <Link href="/app/policies?tab=advanced&sec=tuning">Detectors &amp; tuning tab</Link>.
      </div>
    </>
  );
}

/**
 * The sidebar is a list of nouns. Nothing in the signed-in product said what any
 * of them are for, so a first-time reader had to open all eleven and infer.
 * One row per area: the question it answers, and the thing you actually do there.
 * The second table is the part that is genuinely invisible — capabilities that
 * work and ship today but have no screen, so nobody would ever find out they
 * exist by clicking around.
 */
function Mini({ n, label }: { n: number; label: string }) {
  return (
    <div className={`card ${n ? "" : "empty"}`}>
      <div className="n">{n}</div>
      <div className="l">{label}</div>
    </div>
  );
}

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
  let repos: { github_login: string; repos: Repo[] } | null = null;
  let connectError: { error: string; status?: number } | null = null;
  try {
    repos = await api("/api/integrations/github/repos");
  } catch (e: any) {
    if (e instanceof ApiError && e.status === 404) {
      // not connected yet — not an error, the normal first-visit state
    } else {
      connectError = apiErrorProps(e);
    }
  }

  const scan = scanRunId
    ? await safeApi<any>(`/api/integrations/github/scans/${scanRunId}`, null)
    : null;
  const hostedScan = hostedScanRunId
    ? await safeApi<any>(`/api/integrations/github/scans/${hostedScanRunId}`, null)
    : null;

  return (
    <>
      <p className="sub" style={{ marginTop: 16 }}>
        A repository, or a live API. This finds the <strong>agents</strong>; for the
        data they read from, see <Link href="/app/sources">Verified sources</Link>.{" "}
        <InfoTip text="Either way, nothing goes live until you approve it on the Agents and Rules pages." />
      </p>

      {scanError && <div className="error">Scan failed: {scanError}</div>}

      {scan && (
        <div className="panel" style={{ marginBottom: 20 }}>
          <div className="head">
            <span>Scan of {scan.repo_full_name}</span>
            <span className="note">{scan.status}</span>
          </div>
          <div className="body small">
            <div>Frameworks: {scan.summary?.frameworks?.join(", ") || "none detected"}</div>
            <div>
              Proposed:{" "}
              {scan.summary?.agents_proposed?.length || 0} agent(s),{" "}
              {scan.summary?.policies_proposed?.length || 0} polic{"y/ies"}
            </div>
            <div style={{ marginTop: 8 }}>
              <Link href="/app/agents">Review agents →</Link>
              {"  "}
              <Link href="/app/policies">Review policies →</Link>
            </div>
          </div>
        </div>
      )}

      {hostedScan && (
        <div className="panel" style={{ marginBottom: 20 }}>
          <div className="head">
            <span>Scan of {hostedScan.summary?.endpoint_url || "your API"}</span>
            <span className="note">{hostedScan.status}</span>
          </div>
          <div className="body small">
            <div>
              Operations found: {Object.values(hostedScan.summary?.sites || {}).reduce(
                (a: number, b: any) => a + Number(b),
                0,
              )}
            </div>
            <div>
              Proposed:{" "}
              {hostedScan.summary?.agents_proposed?.length || 0} agent(s),{" "}
              {hostedScan.summary?.policies_proposed?.length || 0} polic{"y/ies"}
            </div>
            <div style={{ marginTop: 8 }}>
              <Link href="/app/agents">Review agents →</Link>
              {"  "}
              <Link href="/app/policies">Review policies →</Link>
            </div>
          </div>
        </div>
      )}

      {connectError && <ApiDown {...connectError} />}

      {!repos ? (
        /* These are two ways to do one thing, not two comparable things. Side by
           side they were a 170px card next to a 360px one, with a button stretched
           the full 465px of its column because .btn-github carries width:100% for
           the login page. Reading order carries the choice instead: the one-click
           option, a rule, then the form — each the same width, nothing stretched,
           and no pretence that a button and a four-field form are peers. */
        <div className="connect-opts">
          <div className="co-opt">
            <div className="co-head">
              <h3>Connect a repository</h3>
              <span className="co-tag">one click</span>
            </div>
            <p>
              A static read of your code for LangChain, LangGraph, CrewAI and AutoGen
              usage. Nothing is imported and nothing is executed.
            </p>
            <a className="btn-github co-gh" href="/api/auth/github/login">
              <svg width="17" height="17" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.42 7.42 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
              </svg>
              Connect GitHub
            </a>
          </div>

          <div className="co-or"><span>or</span></div>

          <div className="co-opt">
            <div className="co-head">
              <h3>Point us at a hosted API</h3>
              <span className="co-tag">no repo access</span>
            </div>
            <p>
              Give us the live endpoint and, if you have one, its OpenAPI spec URL. We
              read the spec document and never call the API itself.
            </p>
            <HostedApiForm />
          </div>
        </div>
      ) : (
        // GitHub is connected — the repo table needs real width to be usable, so
        // it gets the full page instead of being squeezed into a half column next
        // to a form a fraction of its size. The hosted-API option stays above it
        // (not after) so a long repo list never scrolls it out of reach.
        <>
          <div style={{ maxWidth: 480, marginBottom: 20 }}>
            <HostedApiPanel />
          </div>

          <p className="small muted" style={{ maxWidth: "var(--measure)" }}>
            Every repository <strong>{repos.github_login}</strong> can see.{" "}
            <span className="tag ok">company account</span> marks organisation repos.{" "}
            <InfoTip text="We only read code structure to guess what AI frameworks you are using — never run, execute, or modify anything." />
          </p>
          <Panel
            title={`Repositories — ${repos.github_login}`}
            note={<a href="/api/auth/github/login">reconnect</a>}
          >
            {repos.repos.length === 0 ? (
              <Empty>No repositories visible to this GitHub account.</Empty>
            ) : (
              <RepoTable repos={repos.repos} />
            )}
          </Panel>
        </>
      )}
    </>
  );
}

/** The form on its own, for the two-option layout where the heading and the
    explanation are supplied by the surrounding option block. */
function HostedApiForm() {
  return (
    <form action="/api/integrations/hosted-api/scan" method="POST" className="stack">
      <Field
        label="API endpoint"
        type="url"
        name="endpoint_url"
        placeholder="https://api.yourcompany.com"
        required
      />
      <Field
        label="OpenAPI / Swagger spec URL (optional)"
        type="url"
        name="openapi_spec_url"
        placeholder="https://api.yourcompany.com/openapi.json"
      />
      <Field
        label="Docs URL (optional)"
        type="url"
        name="docs_url"
        placeholder="https://docs.yourcompany.com"
      />
      <Field
        label="What does it do?"
        type="text"
        name="purpose"
        placeholder="Internal support-ticket assistant"
      />
      <button type="submit" className="btn-scan">
        Connect &amp; scan
      </button>
    </form>
  );
}

/** The same form as a panel, for the already-connected view, where it sits
    above the repo table rather than beside another option. */
function HostedApiPanel() {
  return (
    <Panel title="Or point us at a hosted API">
      <div className="body">
        <p className="small muted" style={{ marginTop: 0 }}>
          No repo access needed.{" "}
          <InfoTip text="Give us the live endpoint and, if you have one, its OpenAPI/Swagger spec URL. We only read the spec document, never call the API itself." />
        </p>
        <HostedApiForm />
      </div>
    </Panel>
  );
}

function TokensTab() {
  return (
    <>
      <p className="sub" style={{ marginTop: 16 }}>
        For the CLI and SDK. Set <code className="mono">AGENTFOX_API_TOKEN</code>, or
        pass it as a bearer token to the gateway.{" "}
        <InfoTip text="A token acts as you, scoped to your workspace." />
      </p>
      <TokenManager />
    </>
  );
}
