import type { Metadata } from "next";
import Link from "next/link";

import { Comment } from "@/components/lp/parts";
import { VARIANTS, VARIANT_SLUGS } from "@/lib/lp/variants";

export const metadata: Metadata = { title: "Landing variants", robots: { index: false } };

/** Internal review index: the three variants side by side. */
export default function Page() {
  return (
    <div className="lp">
      <main className="lp-index">
        <div className="lp-wrap">
          <Comment>internal review</Comment>
          <h1>Three landing pages, one theme each</h1>
          <div className="lp-index-grid">
            {VARIANT_SLUGS.map((s, i) => {
              const v = VARIANTS[s];
              return (
                <article key={s}>
                  <span className="lp-comment" style={{ margin: 0 }}>v{i + 1} · {v.label}</span>
                  <h3>{v.headline}</h3>
                  <p>{v.sub}</p>
                  <div className="lp-actions">
                    <Link className="lp-btn lp-btn-primary" href={`/lp/${s}`}>Landing page</Link>
                    <Link className="lp-btn" href={`/lp/${s}/benchmark`}>Benchmark</Link>
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      </main>
    </div>
  );
}
