import { NextRequest } from "next/server";
import { proxyRedirectWithHandler } from "@/lib/product/proxy";

/**
 * A full independent re-derivation of the audit-chain hash, on demand — the
 * same check an evidence package runs at build time, but without having to
 * build a package first just to ask "is the chain intact right now?"
 */
export async function POST(req: NextRequest) {
  return proxyRedirectWithHandler(
    req,
    "POST",
    "/api/audit/verify",
    "/app/reports?tab=audit",
    undefined,
    (res, body) => {
      if (!res.ok) return { error: body.detail || res.statusText };
      if (body.valid) {
        return {
          notice: `chain verified — ${body.entries_checked} entr${body.entries_checked === 1 ? "y" : "ies"} (seq ${body.first_seq ?? "—"}–${body.last_seq ?? "—"}), ${body.checkpoints_checked} checkpoint(s), intact`,
        };
      }
      return {
        error: `chain verification FAILED at seq ${body.first_break?.seq ?? "?"}: ${body.first_break?.detail ?? "unknown break"}`,
      };
    },
  );
}
