import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/**
 * The circuit breaker card's two forms: save settings (PUT on the gateway, with the
 * minutes and percent the form shows turned back into seconds and a ratio) or resume
 * now (`action=reset`).
 */
export async function POST(req: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const form = await req.formData();
  const back = `/app/agents/${encodeURIComponent(slug)}?tab=settings`;
  const base = `/api/agents/${encodeURIComponent(slug)}/breaker`;
  if (form.get("action") === "reset") {
    return proxyCustomBody(req, "POST", `${base}/reset`, back, { reason: String(form.get("reason") || "") }, {
      successNotice: "breaker closed",
    });
  }
  const n = (k: string) => {
    const v = String(form.get(k) ?? "").trim();
    return v === "" || Number.isNaN(Number(v)) ? undefined : Number(v);
  };
  const minutes = (k: string) => (n(k) === undefined ? undefined : n(k)! * 60);
  const pct = n("block_percent");
  return proxyCustomBody(
    req,
    "PUT",
    base,
    back,
    {
      mode: String(form.get("mode") || "") || undefined,
      window_seconds: minutes("window_minutes"),
      cooldown_seconds: minutes("cooldown_minutes"),
      min_calls: n("min_calls"),
      block_ratio: pct === undefined ? undefined : pct / 100,
      probe_calls: n("probe_calls"),
    },
    { successNotice: "breaker settings saved" },
  );
}
