"use client";

import { usePathname, useRouter } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { SetupCard } from "@/components/product/onboarding/SetupCard";
import { WORKSPACE_NAV } from "@/lib/product/nav";

const ROWS = WORKSPACE_NAV.flatMap(({ items }) => items);

/** Pages that still work while a project is being added: nothing on them belongs to a project. */
const OPEN = ["/app/settings", "/app/start", "/app/sources", "/app/entitlement", "/app/projects/"];
export const gateOpen = (pathname: string) => OPEN.some((p) => pathname.startsWith(p));

/** What each page will show once the project is connected, for its empty cards. */
const EMPTY: Record<string, string[]> = {
  Agents: ["Agents", "Tools", "Guardrails"],
  Policies: ["Rules", "Checks", "Packs"],
  Approvals: ["Waiting", "History"],
  Issues: ["Open", "Resolved"],
  Testing: ["Last run", "Attacks blocked"],
  Overview: ["Requests", "Blocked", "Held for a person", "Errors"],
  Events: ["Events"],
  Sessions: ["Sessions"],
  Tools: ["Tool calls"],
  Models: ["LLM calls"],
  Errors: ["Errors"],
  Security: ["Attacks", "Data leaks"],
  Evaluations: ["Runs"],
};

/**
 * Every page while a new project is being added: its own title and its cards, empty,
 * and the connection card. Nothing from another project shows, so it is never unclear
 * which project a number belongs to.
 */
/** Set by "Skip for now": a new user can look around before connecting anything. */
export const SKIP_COOKIE = "agentfox_setup_skipped";

export function NewProjectPage({ server, first = false }: { server: string; first?: boolean }) {
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
  const cards = EMPTY[label] ?? [label];
  return (
    <div className="np">
      <header className="page-head">
        <div className="page-head-row">
          <h1>{label}</h1>
        </div>
        <p className="sub">{first ? "nothing here until your first agent is connected" : "new project · nothing here until its agents are connected"}</p>
      </header>
      <div className="np-cards" aria-hidden>
        {cards.map((c) => (
          <div key={c} className="np-card">
            <span>{c}</span>
            <b>—</b>
            <i />
          </div>
        ))}
      </div>
      {skipped ? (
        <div className="np-skipped">
          <span>Connect your first agent to see its {label.toLowerCase()} here.</span>
          <button type="button" className="btn-primary" onClick={unskip}>
            Connect an agent
          </button>
        </div>
      ) : (
        <Suspense>
          <SetupCard server={server} hasProjects={!first} onSkip={() => setSkipped(true)} />
        </Suspense>
      )}
    </div>
  );
}
