import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { NotFound, removedByRetention } from "./index";

describe("a run removed by retention", () => {
  it("reads the purge date from the gateway's 404", () => {
    expect(removedByRetention('{"detail":"removed by retention on 2026-11-09"}')).toBe("2026-11-09");
    expect(removedByRetention('{"detail":"unknown trace"}')).toBeNull();
    expect(removedByRetention(undefined)).toBeNull();
  });

  it("says so instead of 'nothing has created one yet'", () => {
    const html = renderToStaticMarkup(createElement(NotFound, { what: "run", removedOn: "2026-11-09" }));
    expect(html).toContain("removed by retention");
    expect(html).toContain("2026-11-09");
    expect(html).not.toContain("nothing has created one yet");
  });
});
