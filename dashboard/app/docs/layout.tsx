import type { ReactNode } from "react";

import { DocsArticleLd } from "@/components/docs/article-ld";
import { DocsPager } from "@/components/docs/pager";
import { DocsSidebar } from "@/components/docs/sidebar";
import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";
import { SITE_URL } from "@/lib/site";

export default function DocsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="mk">
      <MarketingNav />
      <div className="docs-shell">
        <DocsSidebar />
        <main id="main" className="docs-main">
          <DocsArticleLd siteUrl={SITE_URL} />
          {children}
          <DocsPager />
        </main>
      </div>
      <Footer />
    </div>
  );
}
