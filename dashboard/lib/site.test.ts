import { describe, expect, it } from "vitest";
import { publicPageMetadata } from "./site";

describe("publicPageMetadata", () => {
  const base = { title: "Pricing", description: "What it costs.", path: "/pricing" };

  // A page that sets its own `openGraph` block drops the root's image file, so the
  // helper has to name the card or the page unfurls with no picture.
  it("names the site card for Open Graph and X", () => {
    const m = publicPageMetadata(base);
    expect(m.openGraph.images).toEqual([expect.objectContaining({ url: "/opengraph-image", width: 1200, height: 630 })]);
    expect(m.twitter.images).toEqual([expect.objectContaining({ url: "/twitter-image" })]);
    expect(m.openGraph.images?.[0].alt).toBeTruthy();
    expect(m.twitter.card).toBe("summary_large_image");
  });

  // An explicit image beats a file in the page's own segment, so "/" and the blog
  // posts leave it out and keep their own (hashed) image files.
  it("leaves images out for a route with its own image file", () => {
    const m = publicPageMetadata({ ...base, ownImage: true });
    expect(m.openGraph).not.toHaveProperty("images");
    expect(m.twitter).not.toHaveProperty("images");
  });

  it("restates title and description for unfurls", () => {
    const m = publicPageMetadata(base);
    expect(m.openGraph).toMatchObject({ title: "Pricing", description: "What it costs.", url: "/pricing" });
    expect(m.twitter).toMatchObject({ title: "Pricing", description: "What it costs." });
  });
});
