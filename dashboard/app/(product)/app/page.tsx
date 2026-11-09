import { redirect } from "next/navigation";
import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";

// `appPageMetadata`, not a literal: it also clears the canonical URL, so this page
// does not declare itself a duplicate of the marketing home page. Named like the
// page it opens.
export const metadata: Metadata = appPageMetadata("Agents");
export const dynamic = "force-dynamic";

/**
 * Signing in lands on Agents (/app/map), whatever the way in (a pasted key, GitHub,
 * Google); with no project yet that page shows the setup card: Create a key, run
 * `agentfox init`, add what it found.
 */
export default async function Home() {
  redirect("/app/map");
}
