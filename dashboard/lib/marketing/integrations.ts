/**
 * The /integrations pages, one per framework, in one place. Each says what
 * AgentFox checks for that framework and how, in the words of the connect docs
 * it links to; nothing here claims more than the doc it points at. The nav, the
 * sitemap and llms.txt read this list through lib/marketing/nav.ts.
 */

export type Integration = {
  slug: string;
  /** The framework's name as its own docs write it. */
  name: string;
  /** Browser-tab title, written for the "<framework> security" query. */
  title: string;
  /** One line, for metadata and the index. */
  description: string;
  /** Under the hero. */
  lead: string;
  /** Three lines a reader can paste. */
  install: string;
  /** What is checked, and where. */
  governed: [string, string][];
  /** What `agentfox scan` reads from the code, in the scanner's own words. */
  discovered: string;
  limits: string[];
  /** Where teams use it, one line each. Optional. */
  useCases?: string[];
  /** The connect doc with the steps. */
  docs: { href: string; label: string };
};

const AUTO = `pip install agentfox && agentfox init
# at startup, before any model call:
import agentfox; agentfox.auto(agent="support-triage", intent="answer questions about orders")`;

export const INTEGRATIONS: Integration[] = [
  {
    slug: "langchain",
    name: "LangChain",
    title: "LangChain security and guardrails",
    description:
      "One line checks every LangChain chat model call and tool call: injected instructions, secrets and PII in the messages, and whether the agent may call that tool with those arguments.",
    lead:
      "Add one line at startup. Every chat model call and every tool call in the codebase is checked, with no change to the chains that make them.",
    install: AUTO,
    governed: [
      ["The messages going into a chat model", "Checked before the call, on BaseChatModel.invoke and ainvoke, buffered or streamed"],
      ["The model's reply", "Checked after; a redaction rule rewrites AIMessage.content before your code reads it"],
      ["Each tool call in AIMessage.tool_calls", "Authorised against the agent's grants, with where each argument came from; a refused call raises Blocked so nothing runs it"],
      ["Tools where they run", "BaseTool.invoke and ainvoke are checked before the body runs, and the result is checked as tool output before the model reads it"],
    ],
    discovered: "@tool, create_tool_calling_agent and initialize_agent, AgentExecutor",
    limits: [
      "LangChain.js is not patched. From TypeScript, check messages and tool calls with @agentfox/sdk.",
      "Another process, or a model called outside LangChain's chat models, is not seen by this line; the proxy covers those.",
    ],
    docs: { href: "/docs/connect/python", label: "Python apps: the one line, and where it finds the account key" },
  },
  {
    slug: "langgraph",
    name: "LangGraph",
    title: "LangGraph security and guardrails",
    description:
      "Guard the retrieval, model and tool nodes of a LangGraph graph, pause the graph when a tool call needs a person, and keep supervisor and swarm hand-offs apart from tool calls.",
    lead:
      "The one line covers the model calls. Three decorators add checks on what a node retrieves, says and does, and a grant that needs approval pauses the graph at that node.",
    install: `pip install "agentfox[langgraph]" && agentfox init
from agentfox.frameworks.langgraph import AgentFoxGuard
guard = AgentFoxGuard(agent="research-bot", intent="Answer from the knowledge base.")`,
    governed: [
      ["@guard.retrieval_node", "Retrieved text is checked for planted instructions before the model reads it"],
      ["@guard.model_node", "The messages going in and the reply coming out"],
      ["@guard.tool_node(tool=...)", "The call is authorised before the node's body runs; a grant with --requires-approval pauses the graph, and Command(resume=...) continues it once a person approves"],
      ["Supervisor and swarm hand-offs", "Recorded as a hand-off, not refused as an unknown tool; each member's calls are credited to that member"],
    ],
    discovered: "create_react_agent and create_agent, create_supervisor, create_swarm, StateGraph",
    limits: [
      "The guard keeps its trace under the __agentfox__ key of the state; declare it, or LangGraph drops it between nodes.",
      "Pausing for approval needs the graph compiled with a checkpointer.",
    ],
    docs: { href: "/docs/connect/langgraph", label: "LangGraph: wrap the nodes, declare the state key, pause for approval" },
  },
  {
    slug: "crewai",
    name: "CrewAI",
    title: "CrewAI security and guardrails",
    description:
      "One line checks a crew's model calls and its tools where they run, so the text tool calls CrewAI agents write are authorised too, and delegation between crew members is recorded as what it is.",
    lead:
      "CrewAI agents write tool calls as text, which no check on the model call can read. So the tools are checked where they run, and the model calls where they are made.",
    install: AUTO,
    governed: [
      ["Model calls", "Through the LiteLLM, OpenAI or Anthropic client the crew calls the model with: messages before, reply after"],
      ["Tools where they run", "CrewStructuredTool.invoke and BaseTool.run, sync and async, are authorised before the body runs, with the arguments' provenance taken from earlier tool results"],
      ["Tool results", "Checked as tool output before the agent reads them; text derived from a result keeps that taint"],
      ["Delegate work to coworker", "Recorded as a delegation between members, not refused as an unknown tool; calls are credited to the agent running its task"],
    ],
    discovered: "Agent(role=..., tools=[...]), Crew(agents=[...]), @CrewBase",
    limits: ["A tool your own code calls, outside the crew, is checked only if it is a CrewAI or LangChain tool."],
    docs: { href: "/docs/connect/python#frameworks", label: "Python apps: what the one line covers per framework" },
  },
  {
    slug: "openai-agents-sdk",
    name: "OpenAI Agents SDK",
    title: "OpenAI Agents SDK security and guardrails",
    description:
      "One line checks an Agents SDK app through the Responses API: each model call, each function call before the SDK runs it, and each result fed back; hand-offs and agents-as-tools are recorded as delegation.",
    lead:
      "The Agents SDK calls the model through the Responses API, which the one line patches. Nothing else is needed; a second line hands a refusal back to the model as the tool's answer, so the run carries on.",
    install: `pip install "agentfox[openai-agents]" && agentfox init
import agentfox; agentfox.auto(agent="support-bot", intent="triage support requests")
# optional: govern(fox, triage_agent) returns a refusal to the model instead of raising`,
    governed: [
      ["Model calls", "responses.create, parse and stream, sync and async: instructions and input before, the message items after"],
      ["Each function_call item", "Authorised before the SDK runs the tool; a refused call raises Blocked out of Runner.run, or with govern() goes back to the model as the tool's answer"],
      ["Each function_call_output", "Checked as tool output, and anything copied from it keeps that taint"],
      ["transfer_to_* and agent.as_tool()", "Recorded as hand-offs and delegation; after a hand-off the calls belong to the agent handed to"],
      ["Input, output and tool guardrails", "Native InputGuardrail, OutputGuardrail and ToolInputGuardrail objects backed by the AgentFox SDK, for apps that want them explicit"],
    ],
    discovered: "Agent(name=..., tools=[...], handoffs=[...]), agent.as_tool(...)",
    limits: [
      "Tools OpenAI hosts (web search, file search, code interpreter, hosted MCP) have run before the response arrives: recorded, not stopped.",
      "A request that continues a conversation held on OpenAI's servers (previous_response_id) carries only the new turn, so provenance for earlier turns is recorded as unknown.",
    ],
    docs: { href: "/docs/connect/python#openai-agents", label: "Python apps: the Agents SDK note and govern()" },
  },
  {
    slug: "autogen",
    name: "AutoGen",
    title: "AutoGen security and guardrails",
    description:
      "One line checks an AutoGen or AG2 app through the OpenAI or Anthropic client it calls the model with: messages, replies and each tool call before AutoGen runs it.",
    lead:
      "AutoGen reaches the model through a client library the one line patches. Each tool call the model asks for is authorised before AutoGen runs it, and AgentTool and TeamTool are recorded as delegation.",
    install: AUTO,
    governed: [
      ["Model calls", "Through the OpenAI or Anthropic client: messages before, reply after, buffered or streamed"],
      ["Each tool call in the reply", "Authorised against the agent's grants before AutoGen runs it; a refused call raises Blocked"],
      ["Tool results fed back", "Checked as tool output; text derived from a result keeps that taint"],
      ["AgentTool and TeamTool", "Recorded as an agent used as a tool, not refused as an unknown tool"],
    ],
    discovered: "AssistantAgent(tools=...), group chats, Swarm hand-offs (AutoGen and AG2)",
    limits: ["A tool your own code calls without the model asking is not seen; AutoGen's own tool runner is not patched."],
    docs: { href: "/docs/connect/python#frameworks", label: "Python apps: what the one line covers per framework" },
  },
  {
    slug: "llamaindex",
    name: "LlamaIndex",
    title: "LlamaIndex security and guardrails",
    description:
      "One line checks a LlamaIndex agent or query engine through the OpenAI or Anthropic client it calls the model with, retrieved context included, and each tool call before the agent runs it.",
    lead:
      "LlamaIndex reaches the model through a client library the one line patches. The prompt it builds, retrieved chunks included, is checked before the call, and each tool call is authorised before the agent runs it.",
    install: AUTO,
    governed: [
      ["The prompt the model receives", "Checked before the call, retrieved chunks included, for planted instructions, secrets and PII"],
      ["The model's reply", "Checked after; a redaction rule rewrites it before your code reads it"],
      ["Each tool call in the reply", "Authorised against the agent's grants before LlamaIndex runs it; a refused call raises Blocked"],
      ["Tool results fed back", "Checked as tool output; text derived from a result keeps that taint"],
    ],
    discovered: "LlamaIndex agent constructors given tools=[...]",
    limits: ["A tool your own code calls without the model asking is not seen; LlamaIndex's own tool runner is not patched."],
    docs: { href: "/docs/connect/python#frameworks", label: "Python apps: what the one line covers per framework" },
  },
  {
    slug: "claude-code",
    name: "Claude Code",
    title: "Claude Code security: hooks that check what it runs",
    description:
      "Hooks that check every prompt, tool call and tool result in a Claude Code session and refuse destructive or credential-reading commands before they run, with MCP tools granted like any other tool.",
    lead:
      "Three hooks and a background daemon. Every prompt, tool call and tool result is checked in milliseconds, the shell rules refuse the dangerous commands from day one, and everything else starts in Watch.",
    install: `agentfox admin hooks install --agent claude-dev --write   # writes .claude/settings.json
agentfox init                                            # turns on the coding-agent rules, in Watch
agentfox admin hooks daemon                              # keep it running; hooks ask it`,
    governed: [
      ["Shell commands", "curl … | sh, cat .env, rm -rf ~, git reset --hard, terraform apply, npm publish and turning AgentFox off are refused from the start, whatever the grants say"],
      ["Every other tool call", "Authorised against the agent's grants; built-in tools are granted at install so ordinary work is not refused"],
      ["MCP tools", "Arrive as mcp__server__tool with no grant, so they are refused until granted; grants can be proposed from a few sessions' traffic"],
      ["Prompts and tool results", "A refused prompt never reaches the model; a tool result carrying injected instructions is handed to the agent marked as data"],
    ],
    discovered: "agentfox scan machine reads Claude Code's own config for the MCP servers it loads, and agentfox scan mcp the .mcp.json and .claude/settings.json in a repository",
    limits: [
      "The hooks check against this machine's database and record there, not in your account, so the sessions do not appear in the dashboard.",
      "If the daemon is down the hook allows the call and prints a warning; check agentfox admin hooks status before relying on it.",
    ],
    docs: { href: "/docs/connect/coding-agents", label: "Claude Code and Codex: install the hooks, grant the tools, switch to Block" },
  },
  {
    slug: "codex",
    name: "Codex",
    title: "OpenAI Codex security: hooks that check what it runs",
    description:
      "Hooks that check every prompt, tool call and tool result in a Codex session and refuse destructive or credential-reading commands before they run.",
    lead:
      "The same hooks as for Claude Code, written to .codex/hooks.json. Codex cannot ask you from a hook, so a call that needs a person is refused with the reason.",
    install: `agentfox admin hooks install --harness codex --agent codex-dev --write   # add --scope user for every project
agentfox init && agentfox admin hooks daemon
# in Codex: /hooks, then trust the three AgentFox hooks`,
    governed: [
      ["Shell commands", "curl … | sh, cat .env, rm -rf ~, git reset --hard, terraform apply, npm publish and turning AgentFox off are refused from the start"],
      ["Every other tool call", "Authorised against the agent's grants, including MCP tools, which arrive with no grant"],
      ["Prompts and tool results", "A refused prompt never reaches the model; a tool result carrying injected instructions is handed to the agent marked as data"],
    ],
    discovered: "agentfox scan machine reads Codex's own config for the MCP servers it loads",
    limits: [
      "Codex skips a hook nobody trusted, and a changed hooks file needs trusting again.",
      "A call that needs a person is refused with the reason, since Codex cannot ask from a hook. Hosted tools such as web search run on OpenAI's side and are not checked.",
      "The hooks record on this machine, not in your account.",
    ],
    docs: { href: "/docs/connect/coding-agents#codex", label: "Claude Code and Codex: the Codex differences" },
  },
  {
    slug: "mcp",
    name: "MCP",
    title: "MCP security: scan, pin and govern MCP servers",
    description:
      "Scan the MCP servers your agents and AI tools load without starting them, catch a tool whose schema changed after review, and grant each agent the MCP tools it may call.",
    lead:
      "A scan on Monday says nothing about the call on Thursday. So each server is scanned without being started, each tool's definition is pinned, and at call time a changed definition, an undeclared tool or a poisoned result is caught where it happens.",
    install: `agentfox scan mcp        # the servers in this repository's config; starts none of them
agentfox scan machine    # the servers Claude Code, Cursor, VS Code, Codex and others load on this machine
agentfox permit grant <agent> mcp:github/search_issues --yes`,
    governed: [
      ["Each server's config", "What it can reach, a version that is not pinned, a token written into env, a remote server with no auth; configs of Claude Code, Claude Desktop, Cursor, Windsurf, VS Code, Cline, Gemini CLI and Codex are read"],
      ["Each tool's definition", "Snapshotted from tools/list; a later name, description, schema or impact change refuses the tool's calls with mcp.schema_drift and raises an issue, and accepting the change takes two people"],
      ["Each call", "Authorised as mcp:<server>/<tool> against the agent's grants, from Python (McpGovernor), any language (the guard API) or the Claude Code and Codex hooks"],
      ["Each result", "Checked as tool output for injected instructions; an argument later derived from it keeps that taint"],
      ["A tool nobody registered", "Becomes an observed tool and a discovery finding instead of staying invisible"],
    ],
    discovered: ".mcp.json, .cursor/mcp.json, .claude/settings.json, claude_desktop_config.json and similar, plus installed skills",
    limits: [
      "The scan reads config files and saved tools/list responses. It never starts a server, so a tool list has to be saved to a file and scanned to be pinned.",
      "Hosted MCP tools OpenAI runs inside the Responses API have run before the response arrives: recorded, not stopped.",
    ],
    useCases: [
      "Pull requests: the GitHub Marketplace Action (uses: architsharm/agentfox@main) scans each PR's MCP config for lethal trifectas and poisoned tool descriptions, offline, with no account.",
      "Laptops: agentfox scan machine lists the servers every AI tool on the machine loads, with unpinned versions and tokens written into env, before any of them is started.",
      "Assistants: the server on the official MCP Registry (io.github.architsharm/agentfox, uvx agentfox serve mcp) answers which agent holds which tools and what was held, read-only.",
    ],
    docs: { href: "/docs/connect/mcp", label: "MCP servers: scan, pin, record the tools, grant them" },
  },
];

export const integrationPath = (slug: string) => `/integrations/${slug}`;

export function findIntegration(slug: string): Integration {
  const found = INTEGRATIONS.find((i) => i.slug === slug);
  if (!found) throw new Error(`no integration page for ${slug}`);
  return found;
}
