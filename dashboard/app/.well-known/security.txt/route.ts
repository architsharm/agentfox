/**
 * /.well-known/security.txt — RFC 9116.
 *
 * SECURITY.md in the repository already says where to report a vulnerability,
 * and a researcher who found something in the *hosted* site has no reason to
 * look there. This is the file their tooling checks first, and its absence is
 * the difference between a private advisory and a public issue.
 *
 * `Expires` is required by the RFC and a stale one is a spec violation, so it
 * is computed at build rather than typed: a year from the deploy, recomputed
 * every deploy. A hardcoded date is a file that silently becomes invalid.
 *
 * The contact is GitHub's private advisory form rather than an email address.
 * That is deliberate — it is the route SECURITY.md already directs people to,
 * it creates a private thread the maintainers actually watch, and it does not
 * put an inbox on a page that scrapers read.
 */

import { REPO_URL, SITE_URL } from "@/lib/site";

export const dynamic = "force-static";

export function GET(): Response {
  const expires = new Date();
  expires.setUTCFullYear(expires.getUTCFullYear() + 1);

  const body = `# Reporting a vulnerability in AgentFox or ${SITE_URL}
# The full policy, including what is in and out of scope: ${REPO_URL}/blob/main/SECURITY.md

Contact: ${REPO_URL}/security/advisories/new
Expires: ${expires.toISOString().replace(/\.\d{3}Z$/, "Z")}
Preferred-Languages: en
Canonical: ${SITE_URL}/.well-known/security.txt
Policy: ${REPO_URL}/blob/main/SECURITY.md

# Two things are deliberately not vulnerabilities, because the project says so
# in public and measures them: a detector missing an adaptive attack, and the
# playground running untrusted input on purpose. SECURITY.md has the detail.
`;

  return new Response(body, {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "public, max-age=3600, s-maxage=86400",
    },
  });
}
