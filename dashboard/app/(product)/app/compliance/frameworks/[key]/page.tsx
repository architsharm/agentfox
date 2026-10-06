import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import { api, apiErrorProps } from "@/lib/product/api";
import { Breadcrumbs } from "@/components/product/Breadcrumbs";
import { ApiDown } from "@/components/ui";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata("Framework");

export const dynamic = "force-dynamic";

/**
 * A control-to-framework mapping is a regulatory claim ("this control satisfies
 * EU AI Act Art. 9"). evidence.build() ships every mapping, but any still marked
 * "draft" (Appendix B §B.6) carries a "DRAFT — UNVERIFIED / NOT LEGAL ADVICE" chip
 * rather than being silently dropped, so an auditor can see exactly what is
 * outstanding. This page is where the underlying review actually happens — until
 * a mapping is reviewed here, it keeps carrying that chip in every package.
 */
export default async function FrameworkReview({
  params,
  searchParams,
}: {
  params: Promise<{ key: string }>;
  searchParams: Promise<{ review_error?: string }>;
}) {
  const { key } = await params;
  const { review_error } = await searchParams;

  let coverage: any;
  try {
    coverage = await api(`/api/frameworks/${key}`);
  } catch (e: any) {
    return (
      <>
        <h1>Frameworks</h1>
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }

  return (
    <>
      <Breadcrumbs crumbs={[{ label: "Frameworks", href: "/app/compliance?tab=frameworks" }]} />
      <h1>{coverage.title}</h1>
      <p className="sub">
        {coverage.controls_mapped} of {coverage.controls_total} controls mapped,{" "}
        {coverage.mappings_reviewed} of {coverage.mappings_total} mappings reviewed.
        Reviewing a mapping is a human confirming the control really does satisfy
        that framework clause — evidence packages carry anything still marked
        draft with a DRAFT — UNVERIFIED / NOT LEGAL ADVICE chip, so this is what
        turns it into a real compliance claim rather than a flagged, computed
        guess.
      </p>

      {review_error && <div className="error">{review_error}</div>}

      {coverage.declared_gaps?.length > 0 && (
        <div className="note-panel" style={{ marginBottom: 18 }}>
          <strong>Declared gaps</strong>
          <ul style={{ margin: "6px 0 0" }}>
            {coverage.declared_gaps.map((g: string) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="panel scroll-x">
        <table>
          <thead>
            <tr>
              <th>control</th>
              <th>reference(s)</th>
              <th>status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {coverage.controls.map((c: any) => (
              <tr key={c.key}>
                <td>
                  <div className="small">{c.title}</div>
                  <div className="mono small muted">{c.key}</div>
                </td>
                <td className="small muted">{(c.references || []).join(", ") || "—"}</td>
                <td>
                  <span className={`tag ${c.review_status === "reviewed" ? "ok" : "warn"}`}>
                    {c.review_status}
                  </span>
                </td>
                <td>
                  {c.review_status !== "reviewed" && (
                    <form action="/api/frameworks/review" method="POST">
                      <input type="hidden" name="control_key" value={c.key} />
                      <input type="hidden" name="framework" value={key} />
                      <button type="submit" className="btn-approve" style={{ fontSize: 12 }}>
                        Mark reviewed
                      </button>
                    </form>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
