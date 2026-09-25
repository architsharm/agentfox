import type { ReactNode } from "react";

/**
 * The top of every signed-in page.
 *
 * There was no such component. Ten pages hand-rolled `<h1>` + `<p className="sub">`,
 * and two of them (`/app/agents`, `/app/sources`) wrapped the heading in a `.row` with an
 * action button and set `marginBottom: 0` on the `<h1>` to cancel a margin the
 * other eight kept — so the gap between a title and its subtitle was one value on
 * eight pages and another on two, and the action button existed in two shapes.
 *
 * `sub` is capped at a measure by `.sub` in globals.css rather than by an inline
 * style, because the inline ones had drifted to three different values.
 */
export function PageHeader({
  title,
  sub,
  action,
}: {
  title: string;
  sub?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className="page-head-row">
        <h1>{title}</h1>
        {action}
      </div>
      {sub && <p className="sub">{sub}</p>}
      {/* The hero's checkpoint, seen edge-on. Every signed-in page opens with
          the same mark the public site's hero is built from — which is what
          makes it an identity rather than one good picture on one page. */}
      <div className="gate-rule" aria-hidden />
    </header>
  );
}
