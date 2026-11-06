"""Agents built with voice frameworks, frameworks known by constructor, and agents
configured on a hosted platform.

Three shapes the code scan used to miss: a voice agent written in code (LiveKit,
Pipecat, OpenAI Realtime), an agent of a framework the scan knew only by shape (now
reported under its own name), and an agent with no code at all, defined in the file a
platform exports (Vapi, Retell, ElevenLabs, Bland, n8n, Dify, Flowise, Langflow,
Voiceflow, Dialogflow, Copilot Studio, Agentforce, Bedrock, Lex, Genesys). The
negatives matter as much: a file that shares one key with a platform's format is not
that platform's agent.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from agentfox.capabilities.discovery.repo import scan


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip())


def _json(root: Path, rel: str, data: object) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _by_name(report):
    return {a.name: a for a in report.agents}


# --- Voice agents in code ----------------------------------------------------


def test_a_livekit_agent_class_and_its_function_tools(tmp_path):
    _write(
        tmp_path,
        "voice/agent.py",
        """
        from livekit import agents
        from livekit.agents import Agent, RunContext, function_tool

        @function_tool
        async def lookup_hours(ctx: RunContext) -> str:
            "Opening hours."
            return "9-5"

        class Receptionist(Agent):
            def __init__(self) -> None:
                super().__init__(instructions="You book appointments.", tools=[lookup_hours])

            @function_tool
            async def book_appointment(self, ctx: RunContext, date: str) -> str:
                "Book an appointment on a date."
                return "ok"

            @function_tool(name="cancel")
            async def cancel_appointment(self, ctx: RunContext, booking_id: str) -> str:
                return "ok"

            async def on_enter(self) -> None:
                pass
        """,
    )
    report = scan(tmp_path)
    agent = _by_name(report)["Receptionist"]
    assert (agent.framework, agent.confidence) == ("LiveKit Agents", "high")
    assert set(agent.tools) == {"book_appointment", "cancel", "lookup_hours"}
    assert "LiveKit Agents" in report.frameworks
    assert "LiveKit" not in report.frameworks  # the media SDK label is folded in


def test_a_plain_agent_class_elsewhere_stays_low_confidence(tmp_path):
    _write(
        tmp_path,
        "bots.py",
        """
        from someframework import BaseAgent

        class Planner(BaseAgent):
            tools = [search]
        """,
    )
    agent = _by_name(scan(tmp_path))["Planner"]
    assert agent.confidence == "low"


def test_a_pipecat_pipeline_is_an_agent_with_its_registered_functions(tmp_path):
    _write(
        tmp_path,
        "phone/bot.py",
        """
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.services.openai.llm import OpenAILLMService

        llm = OpenAILLMService(model="gpt-4o")
        llm.register_function("get_weather", fetch_weather)
        llm.register_function("transfer_call", transfer)
        pipeline = Pipeline([transport.input(), stt, llm, tts, transport.output()])
        """,
    )
    agents = scan(tmp_path).agents
    assert len(agents) == 1
    agent = agents[0]
    # `pipeline` in `bot.py` says nothing; the directory names it.
    assert (agent.name, agent.framework, agent.model) == ("phone", "Pipecat", "gpt-4o")
    assert agent.tools == ["get_weather", "transfer_call"]


def test_an_openai_realtime_agent(tmp_path):
    _write(
        tmp_path,
        "rt.py",
        """
        from agents import function_tool
        from agents.realtime import RealtimeAgent

        @function_tool
        def refund(order_id: str) -> str:
            "Refund an order."

        agent = RealtimeAgent(name="Phone Support", instructions="Help callers.", tools=[refund])
        """,
    )
    agent = _by_name(scan(tmp_path))["Phone Support"]
    assert (agent.framework, agent.tools) == ("OpenAI Realtime", ["refund"])


def test_typescript_voice_and_framework_agents(tmp_path):
    _write(
        tmp_path,
        "src/concierge.ts",
        """
        import { voice } from "@livekit/agents";
        export const concierge = new voice.Agent({
          instructions: "You are a hotel concierge.",
          tools: { bookRoom, cancelRoom },
        });
        """,
    )
    _write(
        tmp_path,
        "src/weather.ts",
        """
        import { Agent } from "@mastra/core/agent";
        export const weather = new Agent({
          name: "Weather", instructions: "x", tools: { forecast },
        });
        """,
    )
    agents = _by_name(scan(tmp_path))
    assert agents["concierge"].framework == "LiveKit Agents"
    assert agents["concierge"].tools == ["bookRoom", "cancelRoom"]
    assert (agents["Weather"].framework, agents["Weather"].confidence) == ("Mastra", "high")


# --- Frameworks known by constructor ------------------------------------------


def test_frameworks_known_by_constructor_are_named_and_high_confidence(tmp_path):
    _write(
        tmp_path,
        "app.py",
        """
        from pydantic_ai import Agent
        from smolagents import CodeAgent
        from strands import Agent as StrandsAgent

        support = Agent("openai:gpt-4o", system_prompt="Support", tools=[lookup_order])
        ops = StrandsAgent(system_prompt="Ops", tools=[restart_service])
        research = CodeAgent([web_search], model=model)
        """,
    )
    agents = _by_name(scan(tmp_path))
    assert (agents["support"].framework, agents["support"].model) == (
        "Pydantic AI",
        "openai:gpt-4o",
    )
    assert agents["ops"].framework == "Strands Agents"
    assert agents["research"].tools == ["web_search"]  # smolagents takes tools first
    assert {a.confidence for a in agents.values()} == {"high"}


def test_claude_agent_sdk_options_name_the_agent_by_its_file(tmp_path):
    _write(
        tmp_path,
        "triage.py",
        """
        from claude_agent_sdk import ClaudeAgentOptions

        options = ClaudeAgentOptions(system_prompt="Triage bugs", allowed_tools=["Read", "Bash"])
        """,
    )
    agent = scan(tmp_path).agents[0]
    assert (agent.name, agent.framework, agent.tools) == (
        "triage",
        "Claude Agent SDK",
        ["Read", "Bash"],
    )


# --- Agents configured on a hosted platform -----------------------------------


def test_voice_platform_definitions(tmp_path):
    _json(
        tmp_path,
        "vapi/receptionist.json",
        {
            "name": "Dental Receptionist",
            "firstMessage": "Hi!",
            "model": {
                "provider": "openai",
                "model": "gpt-4o",
                "tools": [{"type": "function", "function": {"name": "book_slot"}}],
            },
            "voice": {"provider": "11labs", "voiceId": "abc"},
            "transcriber": {"provider": "deepgram"},
        },
    )
    _json(
        tmp_path,
        "retell/llm.json",
        {
            "llm_name": "collections",
            "model": "gpt-4.1",
            "general_prompt": "You collect payments.",
            "general_tools": [{"type": "custom", "name": "take_payment"}],
        },
    )
    _json(
        tmp_path,
        "retell/agent.json",
        {
            "agent_name": "Collections Agent",
            "voice_id": "v",
            "response_engine": {"type": "retell-llm"},
        },
    )
    _json(
        tmp_path,
        "eleven/agent.json",
        {
            "name": "Hotel Concierge",
            "conversation_config": {
                "agent": {"prompt": {"llm": "gemini-2.0-flash", "tools": [{"name": "book_room"}]}}
            },
        },
    )
    _json(
        tmp_path,
        "bland/pathway.json",
        {
            "name": "Insurance intake",
            "nodes": [
                {"id": "1", "type": "Default", "data": {"prompt": "Greet the caller"}},
                {"id": "2", "type": "Webhook", "data": {"name": "check_policy", "prompt": "x"}},
            ],
            "edges": [{"source": "1", "target": "2"}],
        },
    )
    report = scan(tmp_path)
    agents = _by_name(report)
    assert agents["Dental Receptionist"].framework == "Vapi"
    assert (agents["Dental Receptionist"].tools, agents["Dental Receptionist"].model) == (
        ["book_slot"],
        "gpt-4o",
    )
    assert agents["collections"].tools == ["take_payment"]
    assert agents["Collections Agent"].framework == "Retell"
    assert agents["Hotel Concierge"].tools == ["book_room"]
    assert agents["Insurance intake"].tools == ["check_policy"]
    assert {"Vapi", "Retell", "ElevenLabs", "Bland"} <= set(report.frameworks)


def test_a_vapi_squad_is_a_team_of_its_assistants(tmp_path):
    assistant = {
        "model": {"provider": "openai"},
        "voice": {"provider": "vapi"},
        "firstMessage": "Hello",
    }
    _json(
        tmp_path,
        "squad.json",
        {
            "name": "Front desk",
            "members": [
                {"assistant": {**assistant, "name": "Greeter"}},
                {"assistant": {**assistant, "name": "Billing"}},
            ],
        },
    )
    report = scan(tmp_path)
    agents = _by_name(report)
    assert agents["Front desk"].kind == "team"
    assert {"Greeter", "Billing"} <= set(agents)
    assert {(e.parent, e.child, e.relation) for e in report.agent_edges} == {
        ("front-desk", "greeter", "member"),
        ("front-desk", "billing", "member"),
    }


def test_workflow_builder_exports(tmp_path):
    _json(
        tmp_path,
        "n8n/support.json",
        {
            "name": "Support bot",
            "nodes": [
                {"name": "AI Agent", "type": "@n8n/n8n-nodes-langchain.agent"},
                {
                    "name": "Chat Model",
                    "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
                    "parameters": {"model": {"value": "gpt-4o-mini"}},
                },
                {"name": "Gmail", "type": "n8n-nodes-base.gmailTool"},
                {"name": "Slack", "type": "n8n-nodes-base.slack"},
            ],
            "connections": {
                "Chat Model": {"ai_languageModel": [[{"node": "AI Agent", "index": 0}]]},
                "Gmail": {"ai_tool": [[{"node": "AI Agent", "index": 0}]]},
            },
        },
    )
    _write(
        tmp_path,
        "dify/app.yml",
        """
        app:
          name: Research Assistant
          mode: agent-chat
        kind: app
        model_config:
          model: {name: gpt-4o}
          agent_mode:
            tools:
              - {tool_name: google_search}
        """,
    )
    _json(
        tmp_path,
        "langflow/flow.json",
        {
            "name": "Lead qualifier",
            "last_tested_version": "1.1.0",
            "data": {
                "nodes": [
                    {"data": {"type": "Agent", "node": {"display_name": "Agent"}}},
                    {"data": {"type": "SearchAPITool", "node": {"display_name": "Search API"}}},
                ],
                "edges": [],
            },
        },
    )
    _json(tmp_path, "pizza.vf", {"project": {"name": "Pizza ordering"}, "version": {}})
    agents = _by_name(scan(tmp_path))
    n8n = agents["Support bot: AI Agent"]
    # Only what is wired into the agent as a tool; the Slack node is a workflow step.
    assert (n8n.tools, n8n.model) == (["Gmail"], "gpt-4o-mini")
    assert (agents["Research Assistant"].framework, agents["Research Assistant"].tools) == (
        "Dify",
        ["google_search"],
    )
    assert agents["Lead qualifier"].tools == ["Search API"]
    assert agents["Pizza ordering"].framework == "Voiceflow"


def test_contact_centre_and_enterprise_definitions(tmp_path):
    _json(
        tmp_path,
        "cx/agent.json",
        {"displayName": "Billing CX", "defaultLanguageCode": "en"},
    )
    _json(tmp_path, "cx/flows/Default Start Flow/flow.json", {})
    _json(tmp_path, "cx/webhooks/payments.json", {})
    _write(
        tmp_path, "copilot/hr/agent.mcs.yml", "kind: GptComponentMetadata\ndisplayName: HR Helper\n"
    )
    _write(tmp_path, "copilot/hr/actions/CreateTicket.mcs.yml", "kind: TaskDialog\n")
    _write(
        tmp_path,
        "genesys/bot.yaml",
        """
        botFlow:
          name: Appointment Bot
        """,
    )
    agents = _by_name(scan(tmp_path))
    assert (agents["Billing CX"].framework, agents["Billing CX"].tools) == (
        "Dialogflow CX",
        ["payments"],
    )
    assert (agents["HR Helper"].framework, agents["HR Helper"].tools) == (
        "Copilot Studio",
        ["CreateTicket"],
    )
    assert agents["Appointment Bot"].framework == "Genesys Cloud"


def test_agentforce_metadata_joins_planner_topics_and_actions(tmp_path):
    _write(
        tmp_path,
        "force-app/main/default/genAiPlanners/Service.genAiPlanner-meta.xml",
        "<GenAiPlanner><masterLabel>Service Agent</masterLabel>"
        "<genAiPlugins><genAiPluginName>Orders</genAiPluginName></genAiPlugins></GenAiPlanner>",
    )
    _write(
        tmp_path,
        "force-app/main/default/genAiPlugins/Orders.genAiPlugin-meta.xml",
        "<GenAiPlugin><genAiFunctions><functionName>Cancel_Order</functionName></genAiFunctions>"
        "<genAiFunctions><functionName>Issue_Refund</functionName></genAiFunctions></GenAiPlugin>",
    )
    _write(
        tmp_path,
        "scripts/Concierge.agent",
        """
        config:
           agent_name: "Concierge"
        topic order_help:
           actions:
              lookup_order:
                 target: "flow://Lookup_Order"
        """,
    )
    agents = _by_name(scan(tmp_path))
    assert agents["Service Agent"].framework == "Agentforce"
    assert agents["Service Agent"].tools == ["Cancel_Order", "Issue_Refund"]
    assert agents["Concierge"].tools == ["lookup_order"]


def test_aws_agents_in_cloudformation_and_terraform(tmp_path):
    _write(
        tmp_path,
        "infra/template.yaml",
        """
        Resources:
          Claims:
            Type: AWS::Bedrock::Agent
            Properties:
              AgentName: claims-agent
              FoundationModel: anthropic.claude-3-5-sonnet
              AgentResourceRoleArn: !GetAtt Role.Arn
              ActionGroups:
                - ActionGroupName: lookup_claim
          OrderBot:
            Type: AWS::Lex::Bot
            Properties:
              Name: OrderBot
          Bucket:
            Type: AWS::S3::Bucket
        """,
    )
    _write(
        tmp_path,
        "infra/main.tf",
        """
        resource "aws_bedrockagent_agent" "triage" {
          agent_name       = "triage-agent"
          foundation_model = "anthropic.claude-v2"
        }
        resource "aws_bedrockagent_agent_action_group" "refunds" {
          action_group_name = "refunds"
          agent_id          = aws_bedrockagent_agent.triage.agent_id
        }
        """,
    )
    agents = _by_name(scan(tmp_path))
    claims = agents["claims-agent"]
    assert (claims.framework, claims.tools, claims.model) == (
        "Bedrock Agents",
        ["lookup_claim"],
        "anthropic.claude-3-5-sonnet",
    )
    assert agents["OrderBot"].framework == "Amazon Lex"
    assert agents["triage-agent"].tools == ["refunds"]
    assert len(agents) == 3  # the bucket is not an agent


def test_code_that_calls_a_platform_api_names_the_stack_without_an_agent(tmp_path):
    _write(
        tmp_path,
        "calls.py",
        """
        import boto3
        import requests

        requests.post("https://api.synthflow.ai/v2/assistants", json={})
        runtime = boto3.client("bedrock-agent-runtime")
        """,
    )
    report = scan(tmp_path)
    assert {"Synthflow", "Bedrock Agents"} <= set(report.frameworks)
    assert report.agents == []


def test_files_sharing_one_key_with_a_platform_format_are_not_agents(tmp_path):
    # A voice setting, a graph of nodes and edges, a `kind: app` manifest, a template
    # with no agent resource: each shares a word with a platform's format, no more.
    _json(tmp_path, "tts.json", {"model": {"provider": "openai"}, "voice": "alto"})
    _json(tmp_path, "graph.json", {"nodes": [{"id": 1, "type": "Default"}], "edges": []})
    _write(tmp_path, "k8s.yaml", "kind: app\nmetadata:\n  name: web\n")
    _write(tmp_path, "stack.yaml", "Resources:\n  B:\n    Type: AWS::S3::Bucket\n")
    _json(tmp_path, "agent.json", {"displayName": "Not an export", "defaultLanguageCode": "en"})
    report = scan(tmp_path)
    assert report.agents == []


def test_platform_agents_get_keys_unique_among_code_agents(tmp_path):
    _write(
        tmp_path,
        "support.py",
        """
        from pydantic_ai import Agent

        support = Agent("openai:gpt-4o", name="Support", tools=[lookup])
        """,
    )
    _json(
        tmp_path,
        "voice/support.json",
        {
            "name": "Support",
            "model": {"provider": "openai"},
            "voice": {"provider": "vapi"},
            "firstMessage": "Hi",
        },
    )
    keys = [a.key for a in scan(tmp_path).agents]
    assert len(keys) == len(set(keys)) == 2


def test_platform_definitions_in_test_fixtures_are_left_out(tmp_path):
    _json(
        tmp_path,
        "tests/fixtures/assistant.json",
        {
            "name": "Fixture",
            "model": {"provider": "openai"},
            "voice": {"provider": "x"},
            "firstMessage": "Hi",
        },
    )
    assert scan(tmp_path).agents == []


def test_voice_frameworks_read_the_model_their_llm_service_is_built_with(tmp_path):
    _write(
        tmp_path,
        "lk/agent.py",
        """
        from livekit.agents import Agent, inference

        class Assistant(Agent):
            def __init__(self) -> None:
                super().__init__(instructions="Help.", llm=inference.LLM(model="gpt-4.1-mini"))
        """,
    )
    _write(
        tmp_path,
        "pc/bot.py",
        """
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.services.openai.llm import OpenAILLMService

        llm = OpenAILLMService(settings=OpenAILLMService.Settings(model="gpt-4o-mini"))
        pipeline = Pipeline([llm])
        """,
    )
    models = {a.framework: a.model for a in scan(tmp_path).agents}
    assert models == {"LiveKit Agents": "gpt-4.1-mini", "Pipecat": "gpt-4o-mini"}


def test_a_dify_workflow_agent_node_brings_its_model_and_tools(tmp_path):
    _write(
        tmp_path,
        "flow.yml",
        """
        app: {name: Trip planner, mode: advanced-chat}
        kind: app
        workflow:
          graph:
            nodes:
              - data:
                  type: agent
                  agent_parameters:
                    model: {value: {model: gpt-4o-mini}}
                    tools: {value: [{tool_name: weather}, {tool_name: flights}]}
        """,
    )
    agent = scan(tmp_path).agents[0]
    assert (agent.model, agent.tools) == ("gpt-4o-mini", ["weather", "flights"])
