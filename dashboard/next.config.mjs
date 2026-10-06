/** @type {import('next').NextConfig} */
const nextConfig = {
  // Deliberately no `env` block: putting NOMETRIA_API_URL there would inline it at
  // build time, so one built image could never be pointed at a different control
  // plane. All pages are server-rendered, so lib/product/api.ts reads process.env at
  // request time instead — which is what makes the same container work in dev,
  // docker-compose and a customer's VPC without a rebuild.
  output: "standalone",
  // A dev server and a production build in the same working tree otherwise share
  // one `.next`, and whichever writes second leaves the other serving a directory
  // whose manifests have just been deleted — the symptom is a live page suddenly
  // 500ing with ENOENT on `routes-manifest.json`, or rendering completely
  // unstyled. `NEXT_DIST_DIR=.next-dev npm run dev` keeps them apart. Unset, this
  // is exactly the previous behaviour, so CI and Vercel are unaffected.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Docs pages that moved in the docs rewrite. Permanent, so old links and search
  // results land on the new page; this is the only list of them.
  async redirects() {
    return [
      ["/docs/commands", "/docs/reference/cli"],
      ["/docs/connect", "/docs/guides/python-auto"],
      ["/docs/control-points", "/docs/concepts"],
      ["/docs/discovery", "/docs/guides/scan-a-repo"],
      ["/docs/access", "/docs/guides/contain-tool-calls"],
      ["/docs/runtime", "/docs/reference/policies"],
      ["/docs/hooks", "/docs/guides/coding-agents"],
      ["/docs/mcp", "/docs/guides/mcp"],
      ["/docs/test", "/docs/guides/red-team-and-evals"],
      ["/docs/evidence", "/docs/guides/audit-evidence"],
      ["/docs/compliance", "/docs/guides/audit-evidence"],
      // The operator plugin was called "the harness" until "harness" came to mean a
      // coding agent AgentFox governs.
      ["/docs/harness", "/docs/plugin"],
    ].map(([source, destination]) => ({ source, destination, permanent: true }));
  },
};
export default nextConfig;
