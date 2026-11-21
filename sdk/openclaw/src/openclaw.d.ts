/**
 * The slice of OpenClaw's plugin SDK this plugin uses, so it typechecks without the
 * whole of OpenClaw installed. At runtime OpenClaw provides the real module (a peer
 * dependency). Shapes follow OpenClaw's docs/plugins/hooks/tool-policy.md.
 */
declare module "openclaw/plugin-sdk/plugin-entry" {
  import type { BeforeToolCallResult, ToolContext, ToolEvent } from "./guard.js";

  interface HookOptions {
    priority?: number;
    matcher?: string[];
    timeoutMs?: number;
  }

  interface PluginApi {
    pluginConfig: unknown;
    on(
      hook: "before_tool_call",
      handler: (event: ToolEvent, ctx: ToolContext) => Promise<BeforeToolCallResult | undefined> | BeforeToolCallResult | undefined,
      options?: HookOptions,
    ): void;
    on(hook: "after_tool_call", handler: (event: ToolEvent, ctx: ToolContext) => void, options?: HookOptions): void;
  }

  export function definePluginEntry(entry: {
    id: string;
    name: string;
    description: string;
    register(api: PluginApi): void;
  }): unknown;
}
