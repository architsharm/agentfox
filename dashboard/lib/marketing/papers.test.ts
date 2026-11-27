import { describe, expect, it } from "vitest";
import { bibtex, PAPERS } from "./papers";

describe("papers", () => {
  it("has a unique slug and a stamped PDF name per paper", () => {
    expect(new Set(PAPERS.map((p) => p.slug)).size).toBe(PAPERS.length);
  });
  it("writes BibTeX authors as Last, First", () => {
    const bib = bibtex(PAPERS[0], "https://example.test/p");
    expect(bib).toContain("author    = {Sharma, Archit and Mann, Garima}");
    expect(bib).toContain("url       = {https://example.test/p}");
  });
});
