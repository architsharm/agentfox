import Link from "next/link";

export type AreaTab = { key: string; label: string; href: string };

/**
 * Reports and Settings are one sidebar row each, but each is several existing
 * pages with their own URLs. This tab bar is what makes them read as one area:
 * every page in the area renders it under the same title, so moving between
 * them feels like switching tabs rather than leaving for somewhere else — and
 * no URL had to change for it.
 *
 * Pages in an area that have sections of their own (Compliance) show those as
 * a chip row under this bar, so there is only ever one underlined tab row.
 */
export const REPORTS_TABS: AreaTab[] = [
  { key: "summary", label: "Summary", href: "/app/reports" },
  { key: "compliance", label: "Compliance", href: "/app/compliance" },
  { key: "coverage", label: "Threat coverage", href: "/app/coverage" },
  { key: "evidence", label: "Evidence", href: "/app/reports?tab=evidence" },
  { key: "audit", label: "Audit log", href: "/app/reports?tab=audit" },
];

export const SETTINGS_TABS: AreaTab[] = [
  { key: "connect", label: "Connections", href: "/app/start?tab=connect" },
  { key: "tokens", label: "API keys", href: "/app/start?tab=tokens" },
  { key: "alerts", label: "Alerts", href: "/app/settings?tab=alerts" },
  { key: "sources", label: "Verified sources", href: "/app/sources" },
  { key: "entitlement", label: "Data access", href: "/app/entitlement" },
];

export function AreaTabs({ tabs, active }: { tabs: AreaTab[]; active: string }) {
  return (
    <nav className="tabbar" aria-label="Sections">
      {tabs.map((t) => (
        <Link
          key={t.key}
          href={t.href}
          className={t.key === active ? "active" : ""}
          aria-current={t.key === active ? "page" : undefined}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
