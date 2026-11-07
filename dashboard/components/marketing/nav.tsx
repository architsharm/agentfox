import { LpNav } from "@/components/lp/parts";
import { ScrollReveal } from "@/components/marketing/motion";

export const REPO = "https://github.com/architsharm/agentfox";

/**
 * The header for pages built on the marketing stylesheet (docs, blog, pricing and
 * the rest). It is the home page's header, so every public page has the same one.
 * ScrollReveal turns on the `.mk-up` entrance animations those pages use.
 */
export async function MarketingNav() {
  return (
    <>
      <ScrollReveal />
      <LpNav />
    </>
  );
}
