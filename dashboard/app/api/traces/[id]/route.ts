import { proxyJson } from "@/lib/product/proxy";

/**
 * Client-fetchable mirror of the server-only `api()` helper, scoped to one
 * trace. Exists for the Traces list's inline-expand: the list response
 * (`search_traces`) is flat summary fields only — decisions/detector_runs/taint
 * live solely on the full-trace read, so expanding a row in place needs its own
 * request rather than reusing data already on the page.
 */
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return proxyJson(`/api/traces/${id}`, "GET", undefined, { cache: "no-store" });
}
