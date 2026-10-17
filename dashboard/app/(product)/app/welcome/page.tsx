import type { Metadata } from "next";
import Link from "next/link";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { api, apiErrorProps, ApiError, safeApi } from "@/lib/product/api";
import { appPageMetadata } from "@/lib/site";
import { publicApiBase } from "@/lib/env";
import { ApiDown } from "@/components/ui";
import { Card, Header } from "@/components/kit";
import { CodeSnippet } from "@/components/product/start/CodeSnippet";
import { WelcomeFlow } from "@/components/product/welcome/WelcomeFlow";
import { INSTALL_SPEC, sortRepos, type Repo } from "@/lib/product/welcome";

export const metadata: Metadata = appPageMetadata("Welcome", "Scan a repository, see what it found, and set it up.");
export const dynamic = "force-dynamic";

/**
 * Where GitHub sign-in lands. One page, three steps, the browser version of
 * `agentfox up`: a real result from the user's own repository in about a minute,
 * set up in one click, then one pre-answered command for the part only their
 * machine can do.
 *
 * A workspace that has already scanned something or received traffic is past this
 * page and goes to Home; `?again=1` brings it back, for scanning another repository.
 */
export default async function Welcome({ searchParams }: { searchParams: Promise<{ again?: string }> }) {
  const { again } = await searchParams;
  // The address this page is served at, not SITE_URL: that falls back to the hosted
  // product's when unset, which would tell a self-hosted install it is Cloud.
  const h = await headers();
  const host = (h.get("x-forwarded-host") || h.get("host") || "").split(",")[0].trim();
  const proto = (h.get("x-forwarded-proto") || "https").split(",")[0].trim();
  const siteUrl = `${proto}://${host}`;
  const onboarding = await safeApi<any>("/api/onboarding", null);
  const counts = onboarding?.counts || { traces: 0, agents: 0, decisions: 0, scans: 0 };
  if (!again && (counts.scans > 0 || counts.traces > 0)) redirect("/app");

  let repos: { github_login: string; repos: Repo[] } | null = null;
  try {
    repos = await api("/api/integrations/github/repos");
  } catch (e: any) {
    if (!(e instanceof ApiError && e.status === 404)) {
      return (
        <>
          <Header title="Welcome" />
          <ApiDown {...apiErrorProps(e)} />
        </>
      );
    }
  }

  return (
    <>
      <Header title="Welcome to AgentFox" />
      <p className="sub wf-lede">
        Three steps, a few minutes. Every result here comes from your own code: nothing is sample data.
      </p>
      {repos && repos.repos.length ? (
        <WelcomeFlow
          repos={sortRepos(repos.repos)}
          githubLogin={repos.github_login}
          gateway={publicApiBase()}
          siteUrl={siteUrl}
          counts={counts}
        />
      ) : (
        <NoGithub hasAccount={Boolean(repos)} />
      )}
    </>
  );
}

/**
 * Signed in with an API token (a self-hosted install), or a GitHub account with no
 * repositories: the scan runs on the user's machine instead, and its summary lands
 * in this workspace the same way.
 */
function NoGithub({ hasAccount }: { hasAccount: boolean }) {
  return (
    <Card title={hasAccount ? "No repositories on this GitHub account" : "Scan from your machine"}>
      <div className="gs-action">
        <p className="gs-detail">
          {hasAccount
            ? "Scan a repository from your machine instead. "
            : "This workspace has no GitHub account connected. "}
          Run this in the repository: it scans it, then sets AgentFox up with a recommended answer for every question.
        </p>
        <CodeSnippet label="In your repository" code={`uvx --from ${INSTALL_SPEC} agentfox up`} />
        <div className="gs-row">
          {!hasAccount && (
            <a href="/api/auth/github/login" className="k-btn-primary">
              Connect GitHub instead
            </a>
          )}
          <Link href="/app/start?tab=tokens" className="k-btn">
            Create an API key
          </Link>
          <Link href="/app/start" className="k-btn-ghost">
            Full checklist
          </Link>
        </div>
      </div>
    </Card>
  );
}
