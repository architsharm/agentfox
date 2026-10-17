import { describe, expect, it } from "vitest";
import { changedCount, checkGroups, levelsFor, lockedReason, type CheckFeature, type Features, type ProtectionFeature } from "./features";

const p = (extra: Partial<ProtectionFeature> = {}): ProtectionFeature => ({
  key: "harmful",
  title: "Harmful content",
  graded: true,
  pack: "baseline",
  installed: true,
  available: true,
  workspace: "medium",
  workspace_mode: "watching",
  open_to_projects: false,
  protected: false,
  project: null,
  project_mode: null,
  effective: "medium",
  needs: null,
  ...extra,
});

const c = (key: string, extra: Partial<CheckFeature> = {}): CheckFeature => ({
  key,
  label: null,
  group: "content",
  group_title: "Harmful content",
  source: "builtin",
  where: ["input"],
  installed: true,
  always_on: false,
  workspace: true,
  project: null,
  effective: true,
  ...extra,
});

describe("features", () => {
  it("offers levels only to graded protections", () => {
    expect(levelsFor(p())).toEqual(["off", "low", "medium", "high"]);
    expect(levelsFor(p({ graded: false, workspace: "on" }))).toEqual(["off", "on"]);
  });

  it("lets a project be stricter, and lower only where the workspace allows", () => {
    expect(lockedReason(p(), "high")).toBeNull();
    expect(lockedReason(p(), "medium")).toBeNull();
    expect(lockedReason(p(), "off")).toMatch(/does not let projects/);
    expect(lockedReason(p({ open_to_projects: true }), "off")).toBeNull();
    expect(lockedReason(p({ open_to_projects: true, protected: true }), "low")).toMatch(/cannot be lowered/);
  });

  it("counts what a project changed", () => {
    const f: Features = { agent: "a", levels: [], protections: [p(), p({ key: "x", project: "high" })], checks: [c("a"), c("b", { project: false })] };
    expect(changedCount(f)).toBe(2);
  });

  it("groups checks with installed ones first", () => {
    const groups = checkGroups([c("z"), c("a", { installed: false }), c("m", { group: "data", group_title: "Data" })]);
    expect(groups.map((g) => g.key)).toEqual(["content", "data"]);
    expect(groups[0].checks.map((x) => x.key)).toEqual(["z", "a"]);
  });
});
