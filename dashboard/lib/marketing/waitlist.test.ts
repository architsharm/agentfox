import { describe, expect, it } from "vitest";
import { waitlistResult } from "./waitlist";

describe("waitlistResult", () => {
  it("confirms a new signup in the form's own terms", () => {
    expect(waitlistResult(200, { status: "added" }).notice).toMatch(/on the list.*pricing is announced/);
  });

  it("says so when the address was already on the list", () => {
    expect(waitlistResult(200, { status: "already_on_list" }).notice).toMatch(/already on the list/);
  });

  it("never repeats the gateway's stale 'hosted AgentFox opens' promise", () => {
    expect(waitlistResult(201, { status: "added" }).notice).not.toMatch(/hosted AgentFox opens/);
  });

  it("gives fixed, plain errors", () => {
    expect(waitlistResult(422, {}).error).toMatch(/email address/);
    expect(waitlistResult(429, null).error).toMatch(/Too many/);
    expect(waitlistResult(500, undefined).error).toMatch(/Something went wrong/);
  });
});
