import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { appPageMetadata } from "@/lib/site";
import { sectionHref } from "@/components/product/policies/advanced";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata("Detector tuning");

/**
 * Guardrails used to be its own nav item, then a hidden Policies tab; detector
 * tuning is a section of Settings → Detection now. This keeps old links and
 * bookmarks working, with the agent filter they carried.
 */
export default async function GuardrailsRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const { agent } = await searchParams;
  redirect(sectionHref("tuning", typeof agent === "string" ? agent : undefined));
}
