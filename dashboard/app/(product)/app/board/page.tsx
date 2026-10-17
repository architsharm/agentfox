import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import { legacyTabRedirect } from "@/lib/product/legacyRedirect";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata("Compliance board");

/**
 * Board view used to be its own nav item; it's now the "Board" tab on the
 * Compliance page, which already computed most of the same data. This keeps
 * old links and bookmarks working.
 */
export default async function BoardRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  return legacyTabRedirect(searchParams, "/app/compliance", "board");
}
