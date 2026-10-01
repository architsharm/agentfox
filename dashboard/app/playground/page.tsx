import type { Metadata } from "next";
import { publicPageMetadata } from "@/lib/site";
import { Playground } from "@/components/Playground";
import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";

export const dynamic = "force-dynamic";

export const metadata: Metadata = publicPageMetadata({
  title: "Red team a running agent",
  description:
    "A prompt injection, or a tool call the agent was not granted. No account. The verdict comes from the product, not a mock.",
  path: "/playground",
});

/**
 * Server Component wrapper only, so the API base URL is resolved from the
 * environment at request time on the server (`lib/api.ts`'s own stated principle:
 * one built container image must be repointable at any backend without a
 * rebuild) rather than inlined into the client bundle at build time the way a
 * `NEXT_PUBLIC_*` var would be. `<Playground>` itself is a Client Component — the
 * browser calls the gateway's public, unauthenticated `/api/playground/*` routes
 * directly, so it needs a URL the *visitor's browser* can reach, which is why this
 * is a separate variable from `NOMETRIA_API_URL` (used by every other,
 * cookie-authenticated, server-to-server page in this app and often an
 * internal-network address like `http://gateway:8080`).
 */
export default function PlaygroundPage() {
  const apiBase =
    process.env.NOMETRIA_PLAYGROUND_API_URL ||
    process.env.NOMETRIA_API_URL ||
    "http://127.0.0.1:8080";

  return (
    <div className="mk">
      <MarketingNav />
      <main className="pg">
        <Playground apiBase={apiBase} />
      </main>
      <Footer />
    </div>
  );
}
