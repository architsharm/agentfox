import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

/**
 * The old Get started checklist and two Settings tabs used to share this URL. Settings
 * has its own URL now (/app/settings), and getting started is the setup card on Agents
 * (/app/map), the one first screen whatever the way in. Old links still land.
 */
export default async function Start({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  if (sp.tab === "map") redirect("/app/glossary#areas");
  if (sp.tab === "connect" || sp.tab === "tokens") {
    const q = new URLSearchParams();
    q.set("tab", sp.tab);
    for (const k of ["scan_run_id", "hosted_scan_run_id", "scan_error"]) if (sp[k]) q.set(k, sp[k]!);
    redirect(`/app/settings?${q}`);
  }
  redirect(sp.agent ? `/app/projects/${encodeURIComponent(sp.agent)}` : "/app/map");
}
