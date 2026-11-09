import type { ReactNode } from "react";

import { DocsKicker, DocsPager } from "@/components/docs/pager";
import { DocsSidebar } from "@/components/docs/sidebar";
import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";

export default function DocsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="mk">
      <MarketingNav />
      <div className="docs-shell">
        <DocsSidebar />
        <main id="main" className="docs-main">
          <DocsKicker />
          {children}
          <DocsPager />
        </main>
      </div>
      <Footer />
    </div>
  );
}
