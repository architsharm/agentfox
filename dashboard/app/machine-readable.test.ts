/**
 * The three files written for machines rather than people: /llms.txt,
 * /AGENTS.md and /.well-known/security.txt.
 *
 * Nobody on the team will ever open these, which is exactly why they need a
 * test. A link in llms.txt that 404s, or a security.txt whose `Expires` has
 * passed, fails silently and only in front of the audience the file exists
 * for — an assistant deciding what to recommend, or a researcher deciding
 * whether to report privately.
 *
 * The rule these enforce is the one that keeps them honest: every path they
 * name is a real public route, taken from the same list `sitemap.ts` reads. A
 * page can be removed from the site without anyone thinking about this file,
 * and that is the case this catches.
 */

import { describe, expect, it } from "vitest";

import { GET as agentsMd } from "./AGENTS.md/route";
import { GET as llmsTxt } from "./llms.txt/route";
import { GET as securityTxt } from "./.well-known/security.txt/route";
import { BLOG_POSTS, blogPath } from "@/lib/blog";
import { ALL_PATHS } from "@/lib/nav";
import { SITE_URL } from "@/lib/site";

/**
 * Public routes — read from the same module the nav, the footer, the sitemap
 * and llms.txt all read.
 *
 * This was a hand-kept array, which made the test a second copy of the thing
 * it was checking: adding a page meant editing five files, and the one most
 * likely to be forgotten was the test that exists to catch the forgetting.
 */
/** Paths these files may name that are not pages in the sitemap. */
const ALSO_SERVED = ["/llms.txt", "/AGENTS.md", "/.well-known/security.txt"];

async function body(res: Response): Promise<string> {
  return await res.text();
}

describe("/llms.txt", () => {
  it("is served as plain text", async () => {
    const res = llmsTxt();
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toMatch(/^text\/plain/);
  });

  it("links only to routes that exist", async () => {
    const text = await body(llmsTxt());
    // Only the markdown link TARGETS — `](url)`. Matching every occurrence of
    // the host also catches it mid-sentence, where the next character is the
    // prose's own punctuation rather than part of a path.
    const ours = [...text.matchAll(new RegExp(`\\]\\(${SITE_URL}([^)]*)\\)`, "g"))].map(
      (m) => m[1] || "/",
    );
    expect(ours.length).toBeGreaterThan(5);

    // Blog posts are public routes from lib/blog.ts, the list sitemap.ts reads.
    const posts = BLOG_POSTS.map((p) => blogPath(p.slug));
    const allowed = new Set([...ALL_PATHS, ...posts, ...ALSO_SERVED]);
    const unknown = [...new Set(ours)].filter((p) => !allowed.has(p));
    expect(unknown, "llms.txt names paths that are not public routes").toEqual([]);
  });

  it("names every public page, so the index cannot quietly go partial", async () => {
    const text = await body(llmsTxt());
    // Legal boilerplate is deliberately not in the index — an assistant
    // recommending a product does not need the terms of service, and listing
    // them dilutes the pages that answer the question being asked.
    const expected = ALL_PATHS.filter((p) => !["/legal", "/privacy", "/terms", "/support"].includes(p));
    for (const path of expected) {
      expect(text, `llms.txt does not mention ${path}`).toContain(`${SITE_URL}${path === "/" ? "/" : path}`);
    }
  });

  it("follows the llmstxt.org shape: an H1, then a blockquote summary", async () => {
    const lines = (await body(llmsTxt())).split("\n");
    expect(lines[0]).toMatch(/^# /);
    expect(lines.slice(0, 4).join("\n")).toMatch(/^> /m);
  });
});

describe("/AGENTS.md", () => {
  it("is served as markdown", async () => {
    const res = agentsMd();
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toMatch(/^text\/markdown/);
  });

  it("says when AgentFox is the wrong answer", async () => {
    // The section this file exists for. An assistant given only the reasons to
    // say yes recommends the product for everything, which is how it gets
    // recommended for the wrong thing and remembered for that.
    const text = await body(agentsMd());
    expect(text).toContain("When AgentFox is the wrong answer");
    const wrong = text.slice(text.indexOf("When AgentFox is the wrong answer"));
    expect(wrong.split("\n- ").length, "fewer than three cases where it is a bad fit").toBeGreaterThan(3);
  });

  it("points back at the fuller index", async () => {
    expect(await body(agentsMd())).toContain(`${SITE_URL}/llms.txt`);
  });
});

describe("/.well-known/security.txt", () => {
  it("has the fields RFC 9116 requires", async () => {
    const text = await body(securityTxt());
    expect(text).toMatch(/^Contact: \S+/m);
    expect(text).toMatch(/^Expires: \S+/m);
    expect(text).toContain(`Canonical: ${SITE_URL}/.well-known/security.txt`);
  });

  it("does not expire, because the date is computed at build", async () => {
    // A hardcoded date is a file that becomes spec-invalid on a day nobody is
    // watching. This is the assertion that would have caught that.
    const text = await body(securityTxt());
    const expires = new Date(text.match(/^Expires: (\S+)/m)![1]);
    expect(expires.getTime()).toBeGreaterThan(Date.now());
    const monthsAway = (expires.getTime() - Date.now()) / (1000 * 60 * 60 * 24 * 30);
    expect(monthsAway).toBeGreaterThan(6);
  });

  it("sends reporters somewhere private", async () => {
    // The whole point: a researcher whose tooling reads this file must not end
    // up opening a public issue.
    const text = await body(securityTxt());
    expect(text).toMatch(/Contact: https:\/\/github\.com\/\S+\/security\/advisories\/new/);
  });
});
