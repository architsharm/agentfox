import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Retention, purgeSummary } from "./Retention";

describe("purgeSummary", () => {
  it("names what it deleted instead of one summed number", () => {
    expect(purgeSummary({ runs_deleted: 2, spans_deleted: 4, links_deleted: 0, turns_deleted: 1 })).toBe(
      "2 runs, 4 spans, 1 conversation turn deleted",
    );
  });

  it("says what a legal hold kept rather than 'Nothing due'", () => {
    expect(purgeSummary({ runs_deleted: 0, spans_deleted: 0, runs_held: 3 })).toBe("3 runs kept by a legal hold");
    expect(purgeSummary({ runs_deleted: 0, runs_held: 0 })).toBe("Nothing due");
    expect(purgeSummary({ skipped: "legal hold" })).toBe("Held by a legal hold");
  });
});

describe("Retention", () => {
  const retention = {
    classes: [
      { data_class: "traces", label: "Runs", covers: "", action: "delete", retain_days: null, default_days: 365 },
    ],
    legal_holds: [{ id: "lh_1", scope: {}, reason: "case", placed_by: "a@example.com", placed_at: "2026-11-09T00:00:00Z" }],
    last_run: null,
    next_run: null,
  };
  const html = renderToStaticMarkup(createElement(Retention, { retention }));

  it("does not pre-fill a period for a class that is kept indefinitely", () => {
    expect(html).toContain("Kept indefinitely");
    expect(html).not.toMatch(/name="retain_days"[^>]*value="365"/);
    expect(html).toContain('placeholder="e.g. 365"');
  });

  it("asks for a reason before releasing a hold", () => {
    const release = html.slice(html.indexOf("/api/legal-holds/lh_1/release"));
    expect(release).toMatch(/<input[^>]*required=""[^>]*name="reason"/);
  });
});
