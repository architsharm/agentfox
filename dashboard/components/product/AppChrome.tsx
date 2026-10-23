"use client";

import { usePathname } from "next/navigation";
import { NewProjectPage, gateOpen } from "@/components/product/NewProjectGate";

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
  children,
}: {
  side: React.ReactNode;
  topbar: React.ReactNode;
  /** Above the page on normal routes (the setup banner); never on full-screen ones. */
  banner?: React.ReactNode;
  /** A project is being added (see NEW_PROJECT): pages show their empty state and the connection card. */
  newProject?: { server: string; first: boolean } | null;
  children: React.ReactNode;
}) {
  const pathname = usePathname() || "";
  const fullScreen = FULL_SCREEN.some((p) => pathname.startsWith(p));
  if (fullScreen) return <>{children}</>;
  // The setup card is the setup prompt; the banner would ask for the same thing twice.
  const showBanner = !pathname.startsWith("/app/onboarding");
  return (
    <div className="shell">
      {side}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        {topbar}
        <main>
          {showBanner && banner}
          {newProject && !gateOpen(pathname) ? <NewProjectPage server={newProject.server} first={newProject.first} /> : children}
        </main>
      </div>
    </div>
  );
}
