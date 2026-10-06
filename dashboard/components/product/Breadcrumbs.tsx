import Link from "next/link";

/**
 * Every detail page (agent, finding, policy, trace, eval suite) rendered as an
 * orphaned H1 with no way back except the browser's own back button. `crumbs` is
 * the trail excluding the current page; the current page's own name is the H1.
 */
export function Breadcrumbs({ crumbs }: { crumbs: { label: string; href: string }[] }) {
  return (
    <div className="breadcrumbs">
      {crumbs.map((c, i) => (
        <span key={c.href}>
          <Link href={c.href}>{c.label}</Link>
          <span className="sep">/</span>
        </span>
      ))}
    </div>
  );
}
