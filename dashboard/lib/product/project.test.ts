import { describe, expect, it } from "vitest";
import { defaultProject, projectHref, projectInPath, projectView } from "./project";
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
    expect(projectView({ view: "controls" })).toBe("controls");
    expect(projectView({ tab: "breaker" })).toBe("controls");
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

  it("calls the project's rules Access, so Policies means one page", () => {
    const labels = projectNav("billing").flatMap((g) => g.items.map((i) => i[0]));
    expect(labels).toContain("Access");
    expect(labels).not.toContain("Policies");
  });

  it("lights Reports on its tab pages and Traces on its tab pages", () => {
    const rows = WORKSPACE_NAV.flatMap((g) => g.items);
    const reports = rows.find((r) => r[0] === "Reports")!;
    expect(reports[1]).toBe("/app/reports");
    expect(reports[2]).toEqual(expect.arrayContaining(["/app/compliance", "/app/coverage"]));
    const traces = rows.find((r) => r[0] === "Traces")!;
    expect(traces[2]).toEqual(expect.arrayContaining(["/app/tools", "/app/models", "/app/sessions", "/app/events"]));
  });

  it("leads with Agents, which stands for the project pages", () => {
    const rows = WORKSPACE_NAV.flatMap((g) => g.items);
    expect(rows[0][1]).toBe("/app/map");
    expect(rows[0][2]).toContain("/app/projects");
    expect(rows.map((r) => r[0])).toEqual([
      "Agents", "Policies", "Approvals", "Issues", "Testing", "Traces", "Reports",
      "Settings",
    ]);
  });
});

describe("default project", () => {
  const row = (project: string, status: string, last_seen_at: string | null = null) => ({ project, last_seen_at, members: [{ status }] });

  it("opens the added project with the most recent traffic, never a shadow agent", () => {
    // The API lists the most recently registered first: here a shadow agent seen once.
    const projects = [
      row("marketing-copy-bot", "shadow", "2026-11-08T11:12:58+00:00"),
      row("support-triage", "active", "2026-11-08T11:12:57+00:00"),
      row("payments-ops", "active", "2026-11-08T11:23:16+00:00"),
      row("draft-bot", "draft"),
    ];
    expect(defaultProject(projects)?.project).toBe("payments-ops");
  });

  it("falls back to the first added project, then to the first of all", () => {
    expect(defaultProject([row("a", "draft"), row("b", "active"), row("c", "active")])?.project).toBe("b");
    expect(defaultProject([row("a", "shadow"), row("b", "draft")])?.project).toBe("a");
    expect(defaultProject([])).toBeUndefined();
  });
});
