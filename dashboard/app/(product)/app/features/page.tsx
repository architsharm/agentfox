import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { appPageMetadata } from "@/lib/site";
import { sectionHref } from "@/components/product/policies/advanced";

export const metadata: Metadata = appPageMetadata("Protection levels");

/**
 * Workspace Features (each protection's level for every project) is the first
 * section of Settings → Detection now. This keeps old links and bookmarks working.
 */
export default function WorkspaceFeaturesRedirect() {
  redirect(sectionHref("levels"));
}
