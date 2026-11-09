import type { Metadata } from "next";
import Link from "next/link";

import { Cards } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Pick your stack",
  description:
    "Which page to follow to connect your agent to AgentFox: Python, the OpenAI Agents SDK, CrewAI, AutoGen, LangGraph, LiteLLM, MCP, Claude Code and Codex, voice and hosted platforms, TypeScript, or any language over HTTP.",
  path: "/docs/connect",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Pick your stack</h1>
      <p className="docs-lede">Find the page for how your agent is built, and follow it.</p>
      <p>
        A plain Python app needs nothing more: <code>agentfox init</code> in the{" "}
        <Link href="/docs/quickstart">Quickstart</Link> already adds the one line it needs.
      </p>

      <Cards
        items={[
          {
            href: "/docs/connect/python",
            title: "Python apps",
            text: "One line, agentfox.auto(), for OpenAI, Anthropic, LiteLLM, LangChain and CrewAI.",
          },
          {
            href: "/docs/connect/python#openai-agents",
            title: "OpenAI Agents SDK",
            text: "auto() covers its model and tool calls; govern() hands a refusal back to the model.",
          },
          {
            href: "/docs/connect/python#frameworks",
            title: "CrewAI",
            text: "auto() checks its model calls and its tools where they run.",
          },
          {
            href: "/docs/connect/python#frameworks",
            title: "AutoGen",
            text: "auto() checks it through the OpenAI or Anthropic client it calls the model with.",
          },
          {
            href: "/docs/connect/langgraph",
            title: "LangGraph",
            text: "Guard retrieval, model and tool nodes, and pause the graph for approval.",
          },
          {
            href: "/docs/connect/litellm",
            title: "LiteLLM proxy",
            text: "Add AgentFox to the proxy config. Every agent behind it is checked.",
          },
          {
            href: "/docs/connect/mcp",
            title: "MCP servers",
            text: "Scan the servers your agents load, pin their tools, and check each call.",
          },
          {
            href: "/docs/connect/coding-agents",
            title: "Claude Code and Codex",
            text: "Hooks that check what a coding agent runs and edits.",
          },
          {
            href: "/docs/connect/platforms",
            title: "Voice and hosted platforms",
            text: "Vapi, Retell, Copilot Studio and AgentCore.",
          },
          {
            href: "/docs/connect/typescript",
            title: "TypeScript",
            text: "@agentfox/sdk: check messages, answers and tool calls from your code.",
          },
          {
            href: "/docs/connect/http",
            title: "Any language (HTTP)",
            text: "Point your model calls at the AgentFox proxy, or ask the guard API.",
          },
        ]}
      />
    </article>
  );
}
