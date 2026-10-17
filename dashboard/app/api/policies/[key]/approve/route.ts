import { NextRequest } from "next/server";
import { proxyReviewAction } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

// Folder is `[key]` to share the path with the sibling save/mode routes (Next.js
// requires one dynamic-segment name per path position) — the value that actually
// lands here is the draft policy's *id*, per the caller in policies/page.tsx.
export async function POST(req: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key: policyId } = await params;
  return proxyReviewAction(req, `/api/policies/${policyId}/approve`, "/app/policies");
}
