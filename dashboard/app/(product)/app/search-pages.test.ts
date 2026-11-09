/**
 * Cmd-K finds every Settings tab by name. Members and Retention were Settings tabs
 * that typing their name in Cmd-K answered "No matches." for: the palette's page list
 * (NAV_SEARCH_ONLY in layout.tsx) is kept by hand, so it is checked against the tabs.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";
import { SETTINGS_TABS } from "@/components/product/AreaTabs";

const layout = readFileSync(join(process.cwd(), "app/(product)/app/layout.tsx"), "utf8");

describe("Cmd-K page list", () => {
  it.each(SETTINGS_TABS.map((t) => [t.label, t.href]))("lists the Settings tab %s", (label, tabHref) => {
    expect(layout).toContain(`href: "${tabHref}"`);
    expect(layout).toContain(`label: "${label}`);
  });
});
