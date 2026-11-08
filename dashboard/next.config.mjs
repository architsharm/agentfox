/** @type {import('next').NextConfig} */
const nextConfig = {
  // Deliberately no `env` block: putting AGENTFOX_API_URL there would inline it at
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
  // URLs that moved. Permanent, so old links, in-app links and search results land
  // on the new page; this is the only list of them. Each points at the final page, never
  // at another redirect. Docs pages are listed in lib/docs/pages.ts.
  async redirects() {
    return [
      ["/docs/install", "/docs/reference/install"],
      ["/docs/plugin", "/docs/connect/coding-agents"],
      ["/docs/guides/walkthrough", "/docs/quickstart/cli"],
      ["/docs/guides/scan-a-repo", "/docs/discover"],
      ["/docs/guides/monitoring", "/docs/discover"],
      ["/docs/guides/python-auto", "/docs/connect/python"],
      ["/docs/guides/contain-tool-calls", "/docs/govern"],
      ["/docs/guides/langgraph", "/docs/connect/langgraph"],
      ["/docs/guides/litellm", "/docs/connect/litellm"],
      ["/docs/guides/mcp", "/docs/connect/mcp"],
      ["/docs/guides/coding-agents", "/docs/connect/coding-agents"],
      ["/docs/guides/codex", "/docs/connect/coding-agents"],
      ["/docs/guides/gateway", "/docs/connect/http"],
      ["/docs/guides/rag", "/docs/govern/data-access"],
      ["/docs/guides/approvals", "/docs/govern/approvals"],
      ["/docs/guides/business-rules", "/docs/protect/custom-rules"],
      ["/docs/guides/import-policies", "/docs/protect/custom-rules"],
      ["/docs/guides/red-team-and-evals", "/docs/test/ci"],
      ["/docs/guides/live-probes", "/docs/test/ci"],
      ["/docs/guides/tuning", "/docs/protect/tuning"],
      ["/docs/guides/migrate-from-llm-guard", "/docs/reference/migrate-from-llm-guard"],
      ["/docs/guides/owasp-agentic-top-10", "/docs/reference/owasp"],
      ["/docs/guides/audit-evidence", "/docs/prove/audit"],
      ["/docs/guides/observability", "/docs/prove/integrations"],
      ["/docs/app", "/docs/quickstart"],
      ["/docs/app/start", "/docs/quickstart"],
      ["/docs/app/projects", "/docs/discover"],
      ["/docs/app/findings", "/docs/prove"],
      ["/docs/app/traces", "/docs/prove"],
      ["/docs/app/policies", "/docs/protect"],
      ["/docs/app/approvals", "/docs/govern/approvals"],
      ["/docs/app/access-and-sources", "/docs/govern/data-access"],
      ["/docs/app/evals", "/docs/test/ci"],
      ["/docs/app/compliance", "/docs/prove/audit"],
      ["/docs/app/playground", "/docs/test"],
      // From the docs rewrite before this one.
      ["/docs/commands", "/docs/reference/cli"],
      ["/docs/control-points", "/docs/concepts"],
      ["/docs/discovery", "/docs/discover"],
      ["/docs/access", "/docs/govern"],
      ["/docs/runtime", "/docs/reference/policies"],
      ["/docs/hooks", "/docs/connect/coding-agents"],
      ["/docs/mcp", "/docs/connect/mcp"],
      ["/docs/evidence", "/docs/prove/audit"],
      ["/docs/compliance", "/docs/prove/audit"],
      // The operator plugin was called "the harness" until "harness" came to mean a
      // coding agent AgentFox governs.
      ["/docs/harness", "/docs/connect/coding-agents"],
      // Marketing pages folded into the home page, the benchmark or the docs.
      ["/product", "/"],
      ["/how-it-works", "/docs/concepts"],
      ["/control-points", "/docs/concepts"],
      ["/hooks", "/docs/connect/coding-agents"],
      ["/mcp", "/docs/connect/mcp"],
      ["/discovery", "/docs/discover"],
      ["/grants", "/docs/govern"],
      ["/runtime", "/docs/reference/policies"],
      ["/evidence", "/docs/prove/audit"],
      ["/frameworks", "/docs/prove/audit"],
      ["/coverage", "/docs/limits"],
      ["/compare", "/benchmark"],
      ["/legal", "/terms"],
      ["/lp", "/"],
      ["/lp/:path*", "/"],
    ].map(([source, destination]) => ({ source, destination, permanent: true }));
  },
};
export default nextConfig;
