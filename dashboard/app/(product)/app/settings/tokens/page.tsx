import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import { legacyTabRedirect } from "@/lib/product/legacyRedirect";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata("API tokens");

/**
 * API tokens used to be its own nav item; it's now the "API tokens" tab on
 * the Start here page. This keeps old links and bookmarks working.
 */
export default async function TokensRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  return legacyTabRedirect(searchParams, "/app/start", "tokens");
}
