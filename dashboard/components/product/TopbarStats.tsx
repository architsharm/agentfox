import Link from "next/link";

/**
 * The critical/high counts otherwise only live in cards partway down Overview —
 * scroll past them once and they're gone until you scroll back up. This mirrors
 * the same `/api/attention` counts the bell already uses, but as always-visible
 * numbers rather than something you have to open a dropdown to see.
 */
export function TopbarStats({ counts }: { counts: { critical?: number; high?: number } }) {
  const critical = counts.critical || 0;
  const high = counts.high || 0;
  // Each count opens Issues filtered to it (`/app` itself now redirects to the map).
  return (
    <span className="topbar-stats" title="Critical / high-priority problems">
      <Link href="/app/findings?severity=critical" className={`topbar-stat${critical ? " bad" : ""}`}>
        <strong>{critical}</strong> critical
      </Link>
      <Link href="/app/findings?severity=high" className={`topbar-stat${high ? " warn" : ""}`}>
        <strong>{high}</strong> high
      </Link>
    </span>
  );
}
