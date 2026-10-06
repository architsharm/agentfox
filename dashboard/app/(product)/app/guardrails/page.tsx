import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import { legacyTabRedirect } from "@/lib/product/legacyRedirect";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata("Guardrail tuning");

/**
 * Guardrails used to be its own nav item; it's now the "Guardrail tuning" tab
 * on the Policies page. This keeps old links and bookmarks working.
 */
export default async function GuardrailsRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  return legacyTabRedirect(searchParams, "/app/policies", "guardrails");
}
