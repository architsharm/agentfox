import { proxyJson } from "@/lib/product/proxy";

/** Onboarding progress, per user, kept by the gateway. */
export async function GET() {
  return proxyJson("/api/onboarding/state", "GET", undefined, { cache: "no-store" });
}

export async function PATCH(req: Request) {
  return proxyJson("/api/onboarding/state", "PATCH", await req.json().catch(() => ({})));
}

/** `?reset=1`: start over at step 1. */
export async function DELETE() {
  return proxyJson("/api/onboarding/state", "DELETE");
}
