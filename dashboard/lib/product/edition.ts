import { cache } from "react";
import { safeApi } from "@/lib/product/api";

/**
 * What this deployment can do: the open core alone, or with AgentFox Enterprise
 * (`ee/`). The gateway says so in `/api/version` (`edition`, `features`); the
 * navigation and the enterprise pages read it here, once per request.
 */
export type Feature = "compliance" | "evidence" | "monitoring" | "access_checks";

export type Edition = {
  edition: "open-source" | "enterprise" | "unknown";
  features: { has(feature: string): boolean };
};

/** Everything is shown when the gateway cannot be asked: the page's own call then
 * reports the outage, instead of an upsell for something the deployment may have. */
const UNKNOWN: Edition = { edition: "unknown", features: { has: () => true } };

export const getEdition = cache(async (): Promise<Edition> => {
  const version = await safeApi<any>("/api/version", null);
  if (!version) return UNKNOWN;
  return {
    edition: version.edition === "enterprise" ? "enterprise" : "open-source",
    features: new Set<string>(version.features || []),
  };
});

export async function hasFeature(feature: Feature): Promise<boolean> {
  return (await getEdition()).features.has(feature);
}
