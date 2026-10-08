import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/**
 * The knowledge-boundary declaration (PUT /api/answerability/boundary) had no UI at
 * all before this — a raw API call surfaced as copyable text on Start here. This is
 * a plain HTML form POST (no client JS), same pattern as the other review-action
 * routes, but it builds its own body rather than using the generic Form* helpers:
 * several fields are comma-separated lists and one is a set of checkboxes, which
 * need parsing into JSON arrays, not passed through as single strings.
 */
export async function POST(req: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const form = await req.formData();
  const list = (name: string) =>
    (form.get(name) as string || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  const num = (name: string) => {
    const v = form.get(name) as string;
    return v && v.trim() ? Number(v) : null;
  };

  const body = {
    agent: slug,
    systems_of_record: list("systems_of_record"),
    coverage_months: num("coverage_months"),
    entity_types: list("entity_types"),
    answerable_types: form.getAll("answerable_types"),
    out_of_scope_topics: list("out_of_scope_topics"),
    freshness_hours: num("freshness_hours"),
    mode: (form.get("mode") as string) || "observe",
  };

  return proxyCustomBody(req, "PUT", "/api/answerability/boundary", `/app/agents/${slug}?tab=access`, body);
}
