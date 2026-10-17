import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The form-to-body mapping, which is where a real bug lived.
 *
 * `fail_closed` is rendered as a *disabled* checkbox on a deployment that requires
 * it — and a disabled input is not submitted. So the form posted no `fail_closed`
 * key, the handler read that as `false`, and the gateway refused the write with the
 * very ceiling that disabled the control: the posture page was unsaveable on exactly
 * the deployments that care most about it. The component now carries a hidden field
 * alongside the greyed-out one.
 *
 * These tests pin the mapping rather than the component, because the mapping is the
 * part a future edit to either side can silently break: HTML checkbox semantics
 * ("absent means false") are correct here and wrong for a control that was never
 * offered.
 */

const cookiesGetMock = vi.fn();
vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ get: cookiesGetMock })),
}));

const { POST } = await import("./route");

function postForm(fields: [string, string][]) {
  const body = new URLSearchParams(fields);
  return new NextRequest("http://localhost:3000/api/judgment/posture", {
    method: "POST",
    body,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
}

function sentBody(fetchMock: ReturnType<typeof vi.fn>) {
  return JSON.parse(fetchMock.mock.calls[0][1].body as string);
}

describe("judgment posture form mapping", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    cookiesGetMock.mockReturnValue({ value: "nom_api_test" });
    fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    cookiesGetMock.mockReset();
  });

  it("carries fail_closed when the deployment requires it and the checkbox is greyed out", async () => {
    await POST(
      postForm([
        ["tiers", "local_model"],
        ["pii_egress", "redact"],
        ["backend", "local"],
        // What the component emits as a hidden field when fail_closed_required.
        ["fail_closed", "on"],
        ["reason", "local weights are installed"],
      ]),
    );
    expect(sentBody(fetchMock).fail_closed).toBe(true);
  });

  it("an absent fail_closed is a deliberate unchecking, not a missing field", async () => {
    await POST(postForm([["reason", "we accept open failure here"]]));
    expect(sentBody(fetchMock).fail_closed).toBe(false);
  });

  it("collects repeated tier checkboxes into a list", async () => {
    await POST(
      postForm([
        ["tiers", "local_model"],
        ["tiers", "local_llm"],
        ["reason", "r"],
      ]),
    );
    expect(sentBody(fetchMock).tiers).toEqual(["local_model", "local_llm"]);
  });

  it("no tiers checked posts an empty list rather than dropping the field", async () => {
    // Otherwise "turn everything off" would be indistinguishable from "change
    // nothing", and the one safe direction would be the one you could not take.
    await POST(postForm([["reason", "turning the optional tiers off"]]));
    expect(sentBody(fetchMock).tiers).toEqual([]);
  });

  it("confirm_egress is off unless the box was ticked", async () => {
    await POST(postForm([["reason", "r"]]));
    expect(sentBody(fetchMock).confirm_egress).toBe(false);

    fetchMock.mockClear();
    await POST(postForm([["reason", "r"], ["confirm_egress", "on"]]));
    expect(sentBody(fetchMock).confirm_egress).toBe(true);
  });

  it("does not forward return_to into the gateway payload", async () => {
    await POST(postForm([["reason", "r"], ["return_to", "/app/policies?tab=advanced&sec=judges"]]));
    expect(sentBody(fetchMock)).not.toHaveProperty("return_to");
  });

  it("an unauthenticated caller never reaches the gateway", async () => {
    cookiesGetMock.mockReturnValue(undefined);
    await POST(postForm([["reason", "r"]]));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
