/**
 * What the setup banner says (components/product/SetupBanner.tsx), decided from the
 * workspace checklist (`/api/onboarding`) or one project's (`/api/agents/{slug}/setup`).
 * Pure, so the order of the steps is tested rather than eyeballed.
 */
import { projectHref } from "@/lib/product/project";

export type Onboarding = {
  completed: number;
  total: number;
  connected: boolean;
  next: { id: string; title: string } | null;
  counts: { agents: number; traces: number };
};

export type ProjectSetup = {
  agent: string;
  name: string;
  id: string;
  status: string;
  traces: number;
  tools: number;
  granted: number;
  watching: { key: string; label: string }[];
  next: "add" | "traffic" | "tools" | "enforce" | null;
};

export type BannerKind = "connect" | "first-request" | "next-step" | "add" | "traffic" | "tools" | "enforce";

export type Banner = {
  kind: BannerKind;
  tone: "start" | "wait" | "act";
  title: string;
  body: string;
  snippet?: string;
  actions: { label: string; href: string }[];
};

/** The request that turns a project's "no traffic yet" into its first run. */
export function firstRequestSnippet(slug: string): string {
  return [
    "curl -X POST \"$AGENTFOX_URL/v1/guard/input\" \\",
    '  -H "Authorization: Bearer $AGENTFOX_API_KEY" \\',
    '  -H "Content-Type: application/json" \\',
    `  -d '{"agent": "${slug}", "content": "Hello"}'`,
  ].join("\n");
}

export function bannerFor(project: ProjectSetup | null, workspace: Onboarding | null): Banner | null {
  if (project) {
    const name = project.name;
    switch (project.next) {
      case "add":
        return {
          kind: "add",
          tone: "start",
          title: `${name} was found by a scan`,
          body: "Add it as a project to record its traffic and protect it.",
          actions: [{ label: "All proposed", href: "/app/projects?tab=proposed" }],
        };
      case "traffic":
        return {
          kind: "traffic",
          tone: "wait",
          title: `No traffic from ${name} yet`,
          body: "Send its requests through AgentFox with an API key. Here is a test request:",
          snippet: firstRequestSnippet(project.agent),
          actions: [
            { label: "Get an API key", href: "/app/start?tab=tokens" },
            { label: "Integration guide", href: "/app/start" },
          ],
        };
      case "tools":
        return {
          kind: "tools",
          tone: "act",
          title: `${name} may not use any of its ${project.tools} tool${project.tools === 1 ? "" : "s"} yet`,
          body: "A tool that is not allowed is refused. Allow the ones it should use.",
          actions: [{ label: "Choose its tools", href: projectHref(project.agent, "access") }],
        };
      case "enforce":
        return {
          kind: "enforce",
          tone: "act",
          title: `${name} is only watching`,
          body: "Its guardrails record what they would stop, without stopping it. Turn blocking on when that looks right.",
          actions: [],
        };
      default:
        return null;
    }
  }
  if (!workspace) return null;
  if (!workspace.counts.agents)
    return {
      kind: "connect",
      tone: "start",
      title: "Connect your first agent",
      body: "Scan a repo to find the agents in it, or connect one by hand. Each agent becomes a project. From a terminal: agentfox up",
      actions: [
        { label: "Scan a repo", href: "/app/start?tab=connect" },
        { label: "Connect by hand", href: "/app/start" },
      ],
    };
  if (!workspace.connected)
    return {
      kind: "first-request",
      tone: "wait",
      title: "Nothing received yet",
      body: "Run your agent with an API key, or send a test request from Get started.",
      actions: [{ label: "Get started", href: "/app/start" }],
    };
  if (workspace.next)
    return {
      kind: "next-step",
      tone: "act",
      title: `Setup ${workspace.completed} of ${workspace.total}`,
      body: `Next: ${workspace.next.title}`,
      actions: [{ label: "Continue", href: "/app/start" }],
    };
  return null;
}

export function dismissKey(scope: string | null, kind: BannerKind): string {
  return `agentfox_banner:${scope || "*"}:${kind}`;
}
