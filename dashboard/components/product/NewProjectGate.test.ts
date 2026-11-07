import { describe, expect, it } from "vitest";

import { gateOpen } from "./NewProjectGate";

describe("gateOpen", () => {
  it("keeps the scan-a-repository page reachable while there is no project", () => {
    // The setup card links to /app/welcome; covering it with the card was a loop.
    expect(gateOpen("/app/welcome")).toBe(true);
    expect(gateOpen("/app/map")).toBe(false);
    expect(gateOpen("/app/projects")).toBe(false);
    expect(gateOpen("/app/projects/shop")).toBe(true);
  });
});
