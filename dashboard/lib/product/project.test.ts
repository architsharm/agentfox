import { describe, expect, it } from "vitest";
import { projectHref, projectInPath, projectView } from "./project";
import { WORKSPACE_NAV, projectNav } from "./nav";

describe("project views", () => {
  it("opens the canvas by default and keeps old agent tabs working", () => {
    expect(projectView({})).toBe("canvas");
    expect(projectView({ view: "access" })).toBe("access");
    expect(projectView({ view: "nope" })).toBe("canvas");
    expect(projectView({ tab: "map" })).toBe("canvas");
    expect(projectView({ tab: "overview" })).toBe("canvas");
    expect(projectView({ tab: "rules" })).toBe("activity");
    expect(projectView({ tab: "quality" })).toBe("activity");
    expect(projectView({ tab: "registration" })).toBe("settings");
    // Inside Activity, `tab` picks its part and the view stays.
    expect(projectView({ view: "activity", tab: "rules" })).toBe("activity");
  });

  it("links to a view", () => {
    expect(projectHref("support bot")).toBe("/app/projects/support%20bot");
    expect(projectHref("a", "activity", { tab: "rules", range: undefined })).toBe("/app/projects/a?view=activity&tab=rules");
  });

  it("reads the project from a path", () => {
    expect(projectInPath("/app/projects/billing")).toBe("billing");
    expect(projectInPath("/app/projects/billing/protect")).toBe("billing");
    expect(projectInPath("/app/projects")).toBeNull();
    expect(projectInPath("/app/findings")).toBeNull();
  });
});

describe("sidebar scopes", () => {
  it("keeps workspace pages out of a project's sidebar", () => {
    const hrefs = projectNav("billing").flatMap((g) => g.items.map((i) => i[1]));
    expect(hrefs).toContain("/app/findings?agent=billing");
    expect(hrefs).toContain("/app/approvals?agent=billing");
    expect(hrefs.some((h) => h.startsWith("/app/policies"))).toBe(false);
  });

  it("has no map page left to link to", () => {
    const hrefs = WORKSPACE_NAV.flatMap((g) => g.items.map((i) => i[1]));
    expect(hrefs).not.toContain("/app/map");
    expect(hrefs).toContain("/app/projects");
  });
});
