import type { ReactNode } from "react";

import { DocsSidebar } from "@/components/docs/sidebar";
import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";

export default function DocsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="mk">
      <MarketingNav />
      <div className="docs-shell">
        <DocsSidebar />
        <div className="docs-main">{children}</div>
      </div>
      <Footer />
    </div>
  );
}
