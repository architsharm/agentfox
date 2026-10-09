import { describe, expect, it } from "vitest";
import { importFiles } from "./files";

describe("importFiles", () => {
  it("keeps string files and drops everything else", () => {
    expect(importFiles({ "a.rego": "package a", "b.rego": 3, c: null })).toEqual({ "a.rego": "package a" });
  });
  it("is empty for anything that is not a map", () => {
    expect(importFiles(undefined)).toEqual({});
    expect(importFiles(["a.rego"])).toEqual({});
    expect(importFiles("package a")).toEqual({});
  });
});
