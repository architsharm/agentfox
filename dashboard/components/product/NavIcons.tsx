/**
 * The sidebar had zero visual icons and no active-page indicator — every item
 * was identical plain text regardless of where you were. Minimal stroke icons,
 * one per nav destination, matching the convention used across this team's other
 * products (24x24, currentColor stroke, no fill).
 *
 * The keys are nav hrefs. A missing key returns null rather than throwing, which
 * means a renamed route loses its icon silently — so when these move, they move
 * with `NAV` in app/layout.tsx and the sidebar is looked at afterwards.
 */
const PATHS: Record<string, React.ReactNode> = {
  "/app": <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  "/app/start": <><path d="M5 3v18" /><path d="M5 4h12l-2.2 4L17 12H5" /></>,
  "/app/agents": <><rect x="5" y="8" width="14" height="11" rx="2.5" /><path d="M12 3v5" /><circle cx="9.2" cy="13.5" r="1.1" /><circle cx="14.8" cy="13.5" r="1.1" /><path d="M9 17h6" /></>,
  "/app/findings": <><path d="M12 3 2.5 20h19L12 3Z" /><path d="M12 10v4.5" /><path d="M12 17.5h.01" /></>,
  "/app/traces": <path d="M3 12h4l2-7 4 14 2-7h6" />,
  "/app/policies": <><rect x="5.5" y="3" width="13" height="18" rx="2" /><path d="M9 3v2h6V3" /><path d="M9 11h6M9 15h6" /></>,
  "/app/entitlement": <><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V7.5a4 4 0 0 1 8 0V11" /></>,
  "/app/approvals": <><path d="M9 12.5l2 2 4-4.5" /><rect x="3.5" y="3.5" width="17" height="17" rx="2.5" /></>,
  "/app/evals": <><rect x="3.5" y="3.5" width="17" height="17" rx="2.5" /><path d="M9 12l2 2 4-4.5" /></>,
  "/app/sources": <><ellipse cx="12" cy="5.5" rx="7.5" ry="2.6" /><path d="M4.5 5.5v13c0 1.4 3.4 2.6 7.5 2.6s7.5-1.2 7.5-2.6v-13" /><path d="M4.5 12c0 1.4 3.4 2.6 7.5 2.6s7.5-1.2 7.5-2.6" /></>,
  "/app/compliance": <><circle cx="12" cy="8" r="5" /><path d="M9 12.3 7 21l5-3 5 3-2-8.7" /></>,
  "/app/observe": <><path d="M3 20h18" /><path d="M5 16l4-5 4 3 6-8" /></>,
  "/app/test": <><path d="M9 3h6" /><path d="M10 3v6l-5 9a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-9V3" /></>,
  "/app/reports": <><path d="M7 3h7l5 5v13H7z" /><path d="M14 3v5h5" /><path d="M10 13h6M10 17h6" /></>,
  "/app/coverage": <><path d="M4 20V10" /><path d="M10 20V4" /><path d="M16 20v-7" /><path d="M3 20h18" /></>,
  "/app/settings": <><circle cx="12" cy="12" r="3" /><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1" /></>,
};

export function NavIcon({ href }: { href: string }) {
  const path = PATHS[href.split("?")[0]];
  if (!path) return null;
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {path}
    </svg>
  );
}
