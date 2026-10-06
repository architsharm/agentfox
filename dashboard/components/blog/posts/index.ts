/**
 * Every post's body, keyed by its slug. `Record<Slug, …>` is the check: a slug
 * registered in lib/blog.ts with no body here, or a body here for a slug that is
 * not registered, is a type error rather than a 404 found in production.
 */

import type { ComponentType } from "react";

import type { TocItem } from "@/components/blog/article";
import type { FaqItem } from "@/components/blog/blocks";
import type { Slug } from "@/lib/blog";

import * as auditTrail from "./ai-agent-audit-trail";
import * as hooks from "./claude-code-hooks-security";
import * as redTeaming from "./continuous-red-teaming-ai-agents";
import * as hidden from "./hidden-indirect-prompt-injection";
import * as mcp from "./mcp-rug-pull-tool-poisoning";
import * as containment from "./prompt-injection-containment-not-detection";

export type PostBody = { Body: ComponentType; toc: TocItem[]; faq: FaqItem[] };

export const POST_BODIES: Record<Slug, PostBody> = {
  "mcp-rug-pull-tool-poisoning": mcp,
  "prompt-injection-containment-not-detection": containment,
  "claude-code-hooks-security": hooks,
  "continuous-red-teaming-ai-agents": redTeaming,
  "hidden-indirect-prompt-injection": hidden,
  "ai-agent-audit-trail": auditTrail,
};
