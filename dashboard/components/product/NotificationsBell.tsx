"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";
import { Severity, ts } from "@/components/ui";

/**
 * The shell had no persistent cross-page signal for "something needs you" —
 * Overview's "Needs attention" table is not visible from anywhere else. This is
 * the same underlying data (`/api/attention`), surfaced everywhere. The rest of
 * the list lives on Issues (`/app` itself now redirects to the map).
 */
export function NotificationsBell({
  items,
  total,
}: {
  items: { severity: string; title: string; href: string; type: string; at: string }[];
  total: number;
}) {
  const count = items.length;
  // A <details> stays open until its summary is clicked again; a dropdown should
  // also close on Escape, a click outside it, and on moving to another page.
  const ref = useRef<HTMLDetailsElement>(null);
  const pathname = usePathname();
  useEffect(() => {
    if (ref.current) ref.current.open = false;
  }, [pathname]);
  useEffect(() => {
    const close = () => {
      if (ref.current) ref.current.open = false;
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && ref.current?.open) {
        close();
        ref.current.querySelector("summary")?.focus();
      }
    };
    const onDown = (e: MouseEvent) => {
      if (ref.current?.open && !ref.current.contains(e.target as Node)) close();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, []);
  return (
    <details className="notif-bell" ref={ref}>
      <summary aria-label={`${total} item(s) need attention`}>
        <BellIcon />
        {total > 0 && <span className="notif-count">{total > 99 ? "99+" : total}</span>}
      </summary>
      <div className="notif-body">
        <div className="notif-head">Needs attention</div>
        {count === 0 ? (
          <div className="notif-empty small muted">
            No open findings, breached hand-offs, or unregistered agents right now — this
            doesn't cover the Compliance risk register or unassessed/unowned agents,
            see <Link href="/app/compliance?tab=board">Board view</Link> for those.
          </div>
        ) : (
          <>
            {items.map((item, i) => (
              <Link key={i} href={item.href} className="notif-item">
                <Severity value={item.severity} />
                <span className="notif-item-body">
                  <span className="small">{item.title}</span>
                  <span className="small muted">{ts(item.at)}</span>
                </span>
              </Link>
            ))}
            {total > count && (
              <Link href="/app/findings" className="notif-more small muted">
                {total - count} more on Issues →
              </Link>
            )}
          </>
        )}
      </div>
    </details>
  );
}

function BellIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 3.5c-3.1 0-5.6 2.5-5.6 5.6v3.1L4.8 15.3c-.3.4 0 1 .5 1h13.4c.5 0 .8-.6.5-1l-1.6-3.1V9.1c0-3.1-2.5-5.6-5.6-5.6Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path d="M9.8 19a2.3 2.3 0 0 0 4.4 0" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
