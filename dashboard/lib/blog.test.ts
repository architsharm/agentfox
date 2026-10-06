/**
 * The blog's invariants: what a search result shows fits, every image a post
 * points at ships, and every internal link in a post lands on a real page.
 *
 * The last one is the reason this file exists. A post is the page most likely
 * to be read a year after it was written, and a docs page renamed in the
 * meantime turns its links into 404s that nothing else would notice.
 */

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { BLOG_POSTS, SLUGS, blogPath } from "@/lib/blog";
import { DOC_PAGES } from "@/lib/docs";
import { ALL_PATHS } from "@/lib/nav";
import sitemap from "@/app/sitemap";

const ROOT = process.cwd();
const POSTS_DIR = join(ROOT, "components", "blog", "posts");

const KNOWN = new Set<string>([
  ...ALL_PATHS,
  ...DOC_PAGES.map((p) => p.href),
  ...BLOG_POSTS.map((p) => blogPath(p.slug)),
]);

function postSource(slug: string): string {
  return readFileSync(join(POSTS_DIR, `${slug}.tsx`), "utf8");
}

describe("the blog", () => {
  it("registers every post once, newest slugs unique", () => {
    expect(new Set(SLUGS).size).toBe(SLUGS.length);
    expect(BLOG_POSTS.map((p) => p.slug).sort()).toEqual([...SLUGS].sort());
  });

  it("has a body file for every post and no orphan bodies", () => {
    const files = readdirSync(POSTS_DIR)
      .filter((f) => f.endsWith(".tsx"))
      .map((f) => f.replace(/\.tsx$/, ""))
      .sort();
    expect(files).toEqual([...SLUGS].sort());
  });

  it("keeps titles and descriptions inside what a search result shows", () => {
    for (const post of BLOG_POSTS) {
      const title = post.seoTitle ?? post.title;
      // The template appends " | AgentFox" (11 characters); Google cuts near 60.
      expect(title.length + 11, `${post.slug} <title>`).toBeLessThanOrEqual(60);
      expect(post.description.length, `${post.slug} description`).toBeGreaterThanOrEqual(110);
      expect(post.description.length, `${post.slug} description`).toBeLessThanOrEqual(160);
      expect(post.keywords.length).toBeGreaterThanOrEqual(3);
    }
  });

  it("ships every image a post uses", () => {
    for (const post of BLOG_POSTS) {
      const srcs = [post.image.src, ...[...postSource(post.slug).matchAll(/src="(\/[^"]+)"/g)].map((m) => m[1])];
      for (const src of srcs) {
        expect(existsSync(join(ROOT, "public", src)), `${post.slug}: ${src}`).toBe(true);
      }
    }
  });

  it("links only to pages that exist", () => {
    for (const post of BLOG_POSTS) {
      const hrefs = [
        ...post.pillars.map((p) => p.href),
        ...[...postSource(post.slug).matchAll(/href="(\/[^"#]*)/g)].map((m) => m[1]),
      ];
      const dead = hrefs.filter((h) => !KNOWN.has(h));
      expect(dead, `${post.slug} links to pages with no route`).toEqual([]);
    }
  });

  it("puts every post in the sitemap", () => {
    const urls = sitemap().map((e) => e.url);
    for (const post of BLOG_POSTS) {
      expect(urls.some((u) => u.endsWith(blogPath(post.slug)))).toBe(true);
    }
    expect(urls.some((u) => u.endsWith("/blog"))).toBe(true);
  });
});
