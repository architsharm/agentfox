/**
 * AgentFox for OpenClaw: checks every tool call an OpenClaw agent makes against
 * AgentFox before it runs. See README.md for setup and what this does and does not cover.
 */
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

import { createGuard, type AgentFoxPluginConfig } from "./guard.js";

export { createGuard } from "./guard.js";
export type { AgentFoxPluginConfig } from "./guard.js";

export default definePluginEntry({
  id: "agentfox",
  name: "AgentFox",
  description: "Check every tool call against AgentFox before it runs: block, hold for an approver, or allow.",
  register(api) {
    const guard = createGuard(api.pluginConfig as AgentFoxPluginConfig);
    // A high priority so AgentFox decides before other policy plugins rewrite anything.
    api.on("before_tool_call", (event, ctx) => guard.beforeToolCall(event, ctx), { priority: 100 });
    api.on("after_tool_call", (event, ctx) => guard.afterToolCall(event, ctx));
  },
});
