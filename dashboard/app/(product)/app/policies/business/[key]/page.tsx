import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

/**
 * A business rule has one page, the same as every other rule's
 * (`/app/policies/rules/business.<key>`): its mode, hits, history and, under Change,
 * its limits. Old links to this one land there.
 */
export default async function BusinessRulePage({ params, searchParams }: { params: Promise<{ key: string }>; searchParams: Promise<Record<string, string | undefined>> }) {
  const { key: raw } = await params;
  const sp = await searchParams;
  const key = decodeURIComponent(raw);
  const tab = sp.tab || "tune";
  redirect(`/app/policies/rules/${encodeURIComponent(`business.${key}`)}?tab=${encodeURIComponent(tab)}`);
}
