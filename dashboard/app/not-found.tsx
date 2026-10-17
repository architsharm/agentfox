import Link from "next/link";

/**
 * A URL that matches no route at all, and the fallback for any `notFound()` a
 * page throws without its own boundary. Renders inside the shell so the sidebar
 * is still there — the usual cause is a stale bookmark or a renamed page, and
 * the fastest recovery is the nav the reader already knows.
 *
 * Pages that know what kind of record is missing should keep using the
 * `NotFound` component in components/ui/index.tsx instead: "no finding at this id" is
 * a more useful sentence than "no such page".
 */
export default function NotFound() {
  return (
    <>
      <h1>Page not found</h1>
      <div className="hero empty">
        <div className="hero-title">There is nothing at this address</div>
        <p>
          The link may be from an older version of the dashboard, or the page it
          pointed at was renamed. Nothing is wrong with your account or the
          control plane.
        </p>
        <p className="small muted">
          Every page is also reachable from the sidebar, or by name from the
          search box in the top bar.
        </p>
        <p>
          <Link href="/" className="cta">
            Back to Overview →
          </Link>
        </p>
      </div>
    </>
  );
}
