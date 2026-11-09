import { describe, expect, it } from "vitest";
import { PAGE_PROMISE, pagePromise } from "./NewProjectGate";
import { WORKSPACE_NAV } from "@/lib/product/nav";

describe("empty pages before anything is connected", () => {
  it("each page says what it will show, in its own words", () => {
    const labels = WORKSPACE_NAV.flatMap(({ items }) => items.map(([label]) => label)).filter((l) => l !== "Settings");
    const said = labels.map(pagePromise);
    for (const l of labels) expect(PAGE_PROMISE[l], l).toBeTruthy();
    expect(new Set(said).size).toBe(labels.length);
  });
});
