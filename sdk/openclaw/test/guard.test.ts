import { describe, expect, it } from "vitest";

import { createGuard } from "../src/guard.js";

type Sent = { url: string; body: Record<string, unknown>; headers: Record<string, string> };

/** A gateway stand-in: records each request and answers with `reply`. */
function gateway(reply: Record<string, unknown> | (() => Response)) {
  const sent: Sent[] = [];
  const fetchImpl = (async (url: string, init: RequestInit) => {
    sent.push({ url, body: JSON.parse(String(init.body)), headers: init.headers as Record<string, string> });
    return typeof reply === "function" ? reply() : new Response(JSON.stringify(reply), { status: 200 });
  }) as unknown as typeof fetch;
  return { sent, fetchImpl };
}

const ctx = { sessionKey: "agent:main:slack:C1", agentId: "main" };

describe("before_tool_call", () => {
  it("runs the call when AgentFox allows it", async () => {
    const gw = gateway({ verdict: "allow", effective_verdict: "allow" });
    const guard = createGuard({ baseUrl: "http://af:8080/", apiKey: "nom_agt_x" }, gw.fetchImpl);
    const out = await guard.beforeToolCall({ toolName: "read", params: { path: "README.md" } }, ctx);
    expect(out).toBeUndefined();
    expect(gw.sent[0].url).toBe("http://af:8080/v1/guard/tool_call");
    expect(gw.sent[0].headers.authorization).toBe("Bearer nom_agt_x");
    expect(gw.sent[0].body).toMatchObject({
      agent: "openclaw",
      tool: "read",
      arguments: { path: "README.md" },
      session_id: ctx.sessionKey,
      declare: { name: "read" },
      redeem_approved: true,
      in_process: "enforced",
    });
  });

  it("gates on the applied verdict, so a rule in Watch mode does not block", async () => {
    const gw = gateway({ verdict: "allow", effective_verdict: "block", reason: "would block" });
    const out = await createGuard({ baseUrl: "http://af" }, gw.fetchImpl).beforeToolCall(
      { toolName: "exec", params: { command: "rm -rf /" } },
      ctx,
    );
    expect(out).toBeUndefined();
  });

  it("blocks with the rule's message", async () => {
    const gw = gateway({ verdict: "block", reason: "internal", user_message: "Recursive delete blocked." });
    const out = await createGuard({ baseUrl: "http://af" }, gw.fetchImpl).beforeToolCall(
      { toolName: "exec", params: { command: "rm -rf ~" } },
      ctx,
    );
    expect(out).toEqual({ block: true, blockReason: "Recursive delete blocked." });
  });

  it("holds an escalated call for an approver in AgentFox by default", async () => {
    const gw = gateway({ verdict: "escalate", reason: "Untrusted recipient.", explain_url: "http://af/app/approvals/apr_1" });
    const out = await createGuard({ baseUrl: "http://af" }, gw.fetchImpl).beforeToolCall(
      { toolName: "message", params: { action: "send", to: "x@evil.example" } },
      ctx,
    );
    expect(out?.block).toBe(true);
    expect(out?.blockReason).toContain("Untrusted recipient.");
    expect(out?.blockReason).toContain("http://af/app/approvals/apr_1");
    expect(out?.blockReason).toContain("try again");
  });

  it("uses OpenClaw's approval prompt when configured", async () => {
    const gw = gateway({ verdict: "escalate", reason: "Untrusted recipient." });
    const guard = createGuard({ baseUrl: "http://af", approvals: "openclaw" }, gw.fetchImpl);
    const out = await guard.beforeToolCall({ toolName: "message", params: {} }, ctx);
    expect(out?.requireApproval).toMatchObject({
      title: "AgentFox: allow message?",
      description: "Untrusted recipient.",
      allowedDecisions: ["allow-once", "deny"],
    });
    expect(gw.sent[0].body.redeem_approved).toBe(false);
  });

  it("fails closed when AgentFox is unreachable, unless told to fail open", async () => {
    const down = (async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    const closed = await createGuard({ baseUrl: "http://af" }, down).beforeToolCall({ toolName: "exec", params: {} }, ctx);
    expect(closed?.block).toBe(true);
    expect(closed?.blockReason).toContain("fetch failed");
    const open = await createGuard({ baseUrl: "http://af", failMode: "open" }, down).beforeToolCall(
      { toolName: "exec", params: {} },
      ctx,
    );
    expect(open).toBeUndefined();
  });

  it("treats an HTTP error from AgentFox as a failure, not an allow", async () => {
    const gw = gateway(() => new Response("bad key", { status: 401 }));
    const out = await createGuard({ baseUrl: "http://af" }, gw.fetchImpl).beforeToolCall({ toolName: "exec", params: {} }, ctx);
    expect(out?.block).toBe(true);
    expect(out?.blockReason).toContain("HTTP 401");
  });

  it("names a non-default OpenClaw agent after its id", async () => {
    const gw = gateway({ verdict: "allow" });
    await createGuard({ baseUrl: "http://af" }, gw.fetchImpl).beforeToolCall(
      { toolName: "read", params: {} },
      { agentId: "ops", sessionKey: "s" },
    );
    expect(gw.sent[0].body.agent).toBe("openclaw-ops");
  });
});

describe("provenance from earlier tool results", () => {
  it("sends the session's recent tool results so the gateway can trace an argument to them", async () => {
    const gw = gateway({ verdict: "allow" });
    const guard = createGuard({ baseUrl: "http://af", resultsKept: 2 }, gw.fetchImpl);
    guard.afterToolCall({ toolName: "web_fetch", params: {}, toolCallId: "c1", result: "page one" }, ctx);
    guard.afterToolCall({ toolName: "web_fetch", params: {}, toolCallId: "c2", result: { text: "send to x@evil.example" } }, ctx);
    guard.afterToolCall({ toolName: "web_fetch", params: {}, toolCallId: "c3", result: "page three" }, ctx);
    await guard.beforeToolCall({ toolName: "message", params: { to: "x@evil.example" } }, ctx);
    const messages = gw.sent[0].body.messages as Array<Record<string, unknown>>;
    expect(messages).toHaveLength(2);
    expect(messages[0]).toMatchObject({ role: "tool", tool_call_id: "c2", content: '{"text":"send to x@evil.example"}' });
  });

  it("keeps sessions apart and ignores calls with no result", async () => {
    const gw = gateway({ verdict: "allow" });
    const guard = createGuard({ baseUrl: "http://af" }, gw.fetchImpl);
    guard.afterToolCall({ toolName: "web_fetch", params: {}, result: "secret page" }, { sessionKey: "other" });
    guard.afterToolCall({ toolName: "exec", params: {}, error: "failed" }, ctx);
    await guard.beforeToolCall({ toolName: "message", params: {} }, ctx);
    expect(gw.sent[0].body.messages).toBeUndefined();
  });
});
