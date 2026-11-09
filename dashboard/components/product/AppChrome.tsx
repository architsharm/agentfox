"use client";

import { usePathname } from "next/navigation";
import { NewProjectPage, gateOpen } from "@/components/product/NewProjectGate";
import { PendingAgents } from "@/components/product/onboarding/PendingAgents";

/**
 * The sidebar and topbar around every `/app` page — except the ones that are
 * deliberately full screen. Decided from `usePathname()`, which is correct on
 * a full page load and on every client-side navigation alike, so the layout's
 * own warning about computing chrome from a request header does not apply.
 */
/** The step-by-step test flow (/app/onboarding/{step}) is full screen; the setup card at
 * /app/onboarding itself sits inside the dashboard. */
const FULL_SCREEN = ["/app/onboarding/"];

export function AppChrome({
  side,
  topbar,
  banner,
  newProject,
  signedIn = false,
  children,
}: {
  side: React.ReactNode;
  topbar: React.ReactNode;
  /** Above the page on normal routes (the setup banner); never on full-screen ones. */
  banner?: React.ReactNode;
  /** A project is being added (see NEW_PROJECT): pages show their empty state and the connection card. */
  newProject?: { server: string; first: boolean; github?: boolean } | null;
  /** Signed in: ask to add what `agentfox init` found until it is added (PendingAgents). */
  signedIn?: boolean;
  children: React.ReactNode;
}) {
  const pathname = usePathname() || "";
  const fullScreen = FULL_SCREEN.some((p) => pathname.startsWith(p));
  if (fullScreen) return <>{children}</>;
  // The setup card is the setup prompt; the banner would ask for the same thing twice.
  const showBanner = !pathname.startsWith("/app/onboarding");
  return (
    <div className="shell">
      <a href="#main" className="lp-skip">
        Skip to content
      </a>
      {side}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        {topbar}
        <main id="main">
          {showBanner && banner}
          {signedIn && <PendingAgents hidden={Boolean(newProject && !gateOpen(pathname))} />}
          {newProject && !gateOpen(pathname) ? <NewProjectPage server={newProject.server} first={newProject.first} github={newProject.github} /> : children}
        </main>
      </div>
    </div>
  );
}
