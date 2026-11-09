/**
 * The attack panel's "Next: run your app" step must not name an `auto()` line init
 * never wrote.
 *
 * It said "Add the one line agentfox init printed (agentfox.auto("refunds-specialist"))"
 * on the Refunds specialist's panel, while init had already added
 * `agentfox.auto("acme-support")` to the app's entry file: init names the line after
 * the agent in the file that starts the app, which the panel of any other agent of the
 * project cannot know. (Found running the first wow on a real model, 2026-11-09.)
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(join(process.cwd(), "components/product/agent/AttackTests.tsx"), "utf8");

describe("AttackTests next step", () => {
  it("does not put the page's agent into the auto() line init wrote", () => {
    expect(SOURCE).not.toMatch(/agentfox\.auto\(&quot;\{pageAgent/);
    expect(SOURCE).toContain("Next: run your app");
  });
});
