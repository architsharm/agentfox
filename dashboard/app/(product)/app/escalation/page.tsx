import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import { legacyTabRedirect } from "@/lib/product/legacyRedirect";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata("Escalation");

/**
 * Escalation used to be its own nav item; it's now the "Escalation" tab on
 * the Approvals page. This keeps old links and bookmarks working.
 */
export default async function EscalationRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  return legacyTabRedirect(searchParams, "/app/approvals", "escalation");
}
