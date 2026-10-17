import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import { api, apiErrorProps } from "@/lib/product/api";
import { ApiDown } from "@/components/ui";
import { Header } from "@/components/kit";
import { FeaturesEditor } from "@/components/product/features/FeaturesEditor";

export const metadata: Metadata = appPageMetadata("Features", "What every project gets, unless it changes it.");
export const dynamic = "force-dynamic";

/**
 * The workspace's switches: each protection's level, whether projects may lower it,
 * and which checks run. Every project starts from these and changes them on its own
 * Features view.
 */
export default async function WorkspaceFeatures() {
  let features: any;
  try {
    features = await api("/api/features");
  } catch (e: any) {
    return (
      <>
        <Header title="Features" />
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }
  return (
    <>
      <Header title="Features" hint="What every project gets. A project changes these for itself on its own Features view." />
      <FeaturesEditor initial={features} />
    </>
  );
}
