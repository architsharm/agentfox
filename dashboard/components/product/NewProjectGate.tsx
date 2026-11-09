"use client";

import { usePathname, useRouter } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { SetupCard } from "@/components/product/onboarding/SetupCard";
import { WORKSPACE_NAV } from "@/lib/product/nav";

const ROWS = WORKSPACE_NAV.flatMap(({ items }) => items);

/** Pages that still work while a project is being added: nothing on them belongs to a project.
 * /app/welcome is itself a way to add one (scan a repository), so it must never be covered
 * by the card that links to it. */
const OPEN = ["/app/settings", "/app/start", "/app/sources", "/app/entitlement", "/app/projects/", "/app/welcome"];
export const gateOpen = (pathname: string) => OPEN.some((p) => pathname.startsWith(p));

/**
 * What each page will show once an agent is connected, said on the page while it is
 * empty. Each page used to show the same line ("Connect your first agent to see its
 * issues here") over dashed placeholder tiles that read as loading.
 */
export const PAGE_PROMISE: Record<string, string> = {
  Agents: "Every agent agentfox init finds in your code: the map of what it talks to, the tools it can call, and the guardrails on each step.",
  Policies: "The rules that check each message and tool call, which agents they apply to, and whether each one watches or blocks.",
  Approvals: "Tool calls an agent was held on until a person allows or denies them, with what the agent was about to do.",
  Issues: "What the attack test and your agents' traffic found: attacks that got through, data that leaked, tools used without permission.",
  Testing: "Attack tests on your agents (before and after guardrails), and a box to try a message or a tool call against your real rules.",
  Activity: "Each request your app makes: the model and tool calls, and every check each one went through.",
  Reports: "What you show others: a summary of what was stopped, threat coverage, and the audit log.",
};

/** The one thing to do to fill a page: connect an agent (the setup card). */
export function pagePromise(label: string): string {
  return PAGE_PROMISE[label] ?? "What your agents do, once one is connected.";
}

/**
 * Every page while a new project is being added: its own title and its cards, empty,
 * and the connection card. Nothing from another project shows, so it is never unclear
 * which project a number belongs to.
 */
/** Set by "Skip for now": a new user can look around before connecting anything. */
export const SKIP_COOKIE = "agentfox_setup_skipped";

export function NewProjectPage({ server, first = false, github = false }: { server: string; first?: boolean; github?: boolean }) {
  const pathname = usePathname() || "/app";
  const router = useRouter();
  const [skipped, setSkipped] = useState(false);
  useEffect(() => setSkipped(first && document.cookie.split("; ").includes(`${SKIP_COOKIE}=1`)), [first]);
  const unskip = () => {
    document.cookie = `${SKIP_COOKIE}=; path=/; max-age=0; samesite=lax`;
    setSkipped(false);
    router.refresh();
  };
  const row = ROWS.find(([, href, also]) =>
    [href, ...(also || [])].some((h) => {
      const path = h.split("?")[0];
      return pathname === path || pathname.startsWith(`${path}/`);
    }),
  );
  const label = row?.[0] ?? "Agents";
  return (
    <div className="np">
      <header className="page-head">
        <div className="page-head-row">
          <h1>{label}</h1>
        </div>
        <p className="sub">{pagePromise(label)}</p>
      </header>
      {skipped ? (
        <div className="np-skipped">
          <span>
            {first ? "Empty until your first agent is connected." : "Empty until this project's agents are connected."} It takes about a minute:
            create a key, run <code>agentfox init</code> where your agents live.
          </span>
          <button type="button" className="btn-primary" onClick={unskip}>
            Connect an agent
          </button>
        </div>
      ) : (
        <Suspense>
          <SetupCard server={server} hasProjects={!first} github={github} onSkip={() => setSkipped(true)} />
        </Suspense>
      )}
    </div>
  );
}
