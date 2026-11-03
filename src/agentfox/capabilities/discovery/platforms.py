"""Agents configured on a hosted platform, read from the files a repository keeps
for them.

The code scan (:mod:`agentfox.capabilities.discovery.agents`) finds agents a framework
builds in source. A growing share of agents is not built in source at all: a voice
agent is a Vapi assistant or a Retell agent, a support agent is an Agentforce planner
or a Copilot Studio agent, a workflow agent is an n8n or Dify app. What the
repository holds for those is the platform's own definition — an exported JSON or
YAML file, a metadata directory, an infrastructure template — and a scan that reads
only code reports such a repository as having no agents.

So this reads those definitions. Same rules as the rest of discovery: **no import, no
execution, no network**, and precision before recall. A file counts only when it has
the shape the platform writes (several of its own keys together, not one common word),
because a false agent becomes a proposed agent someone has to reject, and a platform
named on the strength of a single ``"voice"`` key is a guess.

What is recognised, per platform (:data:`RECOGNISED`):

* **Voice** — Vapi assistants and squads, Retell agents and Retell LLMs, ElevenLabs
  agents, Bland pathways; plus the API of each (and of Synthflow, Telnyx, Smallest AI
  and Agora) named as the stack when code calls it.
* **Contact centre and enterprise** — Dialogflow CX and ES agent exports, Copilot
  Studio agents (``*.mcs.yml`` and solution ``bot.xml``), Agentforce metadata
  (planners, topics, actions, Agent Script ``.agent`` files), Amazon Bedrock Agents,
  Bedrock AgentCore runtimes and Lex bots in CloudFormation or Terraform, Genesys
  Architect bot flows.
* **Workflow builders** — n8n workflows with an AI Agent node, Dify apps, Flowise
  chatflows, Langflow flows, Voiceflow projects.

Platforms whose agents live only in the vendor's console (Sierra, Kore.ai, Webex AI
Agent, Five9, NICE, Talkdesk, Parloa, PolyAI) leave nothing in a repository to read;
they are not claimed here.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: Shown by `agentfox init` under "Missing something?", beside the code frameworks.
RECOGNISED = (
    ("Vapi", "assistant / squad JSON or YAML (model, voice, transcriber), assistants.create"),
    ("Retell", "agent JSON (response_engine, voice_id), Retell LLM (general_prompt, tools)"),
    ("ElevenLabs", "agent JSON (conversation_config.agent.prompt), convai agents.create"),
    ("Bland", "pathway JSON (nodes of type Default / Webhook / Transfer Call)"),
    ("Dialogflow CX / ES", "agent export: agent.json with flows/, playbooks/ or intents/"),
    ("Copilot Studio", "*.mcs.yml agent folders, solution bots/*/bot.xml"),
    ("Agentforce", "genAiPlanner / genAiPlugin / genAiFunction / Bot metadata, .agent files"),
    ("Amazon", "Bedrock Agent, AgentCore runtime and Lex bot in CloudFormation or Terraform"),
    ("Genesys Cloud", "Architect YAML bot flows (botFlow, digitalBotFlow)"),
    ("n8n", "workflow JSON with an AI Agent node, its tools and model"),
    ("Dify", "app DSL YAML (kind: app), agent tools and workflow tool nodes"),
    ("Flowise / Langflow", "exported flow JSON with an agent node"),
    ("Voiceflow", ".vf project files"),
)

#: Files this pass reads, by suffix. JSON and YAML are already read by the repo scan
#: for secrets and MCP servers; XML, ``.tf``, ``.vf`` and ``.agent`` are read only here.
SUFFIXES = {".json", ".yaml", ".yml", ".xml", ".tf", ".vf", ".agent"}

#: A platform export larger than this is a data dump, not an agent definition.
MAX_BYTES = 3_000_000


@dataclass
class Found:
    """One agent a platform definition describes."""

    platform: str
    name: str
    file: str
    line: int = 1
    tools: list[str] = field(default_factory=list)
    model: str | None = None
    #: agent | team (a squad, a crew of agents one file defines together)
    kind: str = "agent"
    confidence: str = "high"
    evidence: str = ""
    #: True when the definition names the agent itself (not a file or folder name).
    named: bool = True
    #: For a team: the names of the agents (in the same file) it runs.
    members: list[str] = field(default_factory=list)


@dataclass
class Result:
    agents: list[Found] = field(default_factory=list)
    #: Platforms the repository uses, including ones known only from an API call.
    platforms: set[str] = field(default_factory=set)
    #: Salesforce metadata seen so far, joined into agents once every file is read:
    #: planners (label, file, topic names), topics -> action names, actions, bots.
    sf_planners: list[tuple[str, str, list[str]]] = field(default_factory=list)
    sf_plugins: dict[str, list[str]] = field(default_factory=dict)
    sf_functions: set[str] = field(default_factory=set)
    sf_bots: list[tuple[str, str]] = field(default_factory=list)


def is_candidate(path: Path) -> bool:
    return path.suffix.lower() in SUFFIXES or path.name.endswith(".mcs.yml")


def detect(paths: list[Path], root: Path) -> Result:
    """Read each candidate file (see :func:`is_candidate`) for platform definitions."""
    result = Result()
    seen_dirs: set[Path] = set()
    for path in sorted(paths):
        rel = str(path.relative_to(root))
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        suffix = path.suffix.lower()
        if path.name.endswith(".mcs.yml"):
            _copilot_folder(path, root, seen_dirs, result)
            continue
        if suffix == ".xml":
            _salesforce_or_bot_xml(path, rel, text, result)
            continue
        if suffix == ".agent":
            _agent_script(rel, text, result)
            continue
        if suffix == ".tf":
            _terraform(rel, text, result)
            continue
        data = _load(text, suffix)
        if data is None:
            continue
        if suffix == ".vf":
            _voiceflow(rel, path, data, result)
            continue
        if path.name == "agent.json" and isinstance(data, dict):
            if _dialogflow(path, rel, data, result):
                continue
        for reader in _READERS:
            if reader(rel, path, data, text, result):
                break
    _salesforce_finish(result)
    return result


def detect_code_platforms(source: str) -> set[str]:
    """Hosted agent platforms a code file talks to, from the API hosts and AWS service
    names it uses. A stack label only: calling a platform's API is not an agent
    definition, and nothing here becomes one."""
    return {label for pattern, label in _API_PATTERNS if pattern.search(source)}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


class _Loader(yaml.SafeLoader):
    """`yaml.SafeLoader` that reads CloudFormation's short-form tags (``!Ref``,
    ``!GetAtt``, ``!Sub``) as plain values instead of failing on the whole file."""


def _any_tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)  # type: ignore[arg-type]


_Loader.add_multi_constructor("!", _any_tag)


def _load(text: str, suffix: str) -> Any:
    stripped = text.lstrip()
    if not stripped:
        return None
    try:
        if suffix in (".json", ".vf") or stripped[:1] in "{[":
            return json.loads(text)
        if suffix in (".yaml", ".yml"):
            return yaml.load(text, Loader=_Loader)  # noqa: S506 - SafeLoader subclass
    except (ValueError, yaml.YAMLError):
        return None
    return None


def _line_of(text: str, needle: str) -> int:
    at = text.find(needle)
    return text.count("\n", 0, at) + 1 if at >= 0 else 1


def _names(items: Any, *keys: str) -> list[str]:
    """The first of ``keys`` each dict in ``items`` has, as a string, in order."""
    out: list[str] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        for key in keys:
            value = _dig(item, key)
            if isinstance(value, str) and value:
                out.append(value)
                break
    return list(dict.fromkeys(out))


def _dig(data: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def _stem(path: Path) -> str:
    return path.stem.split(".")[0] or path.parent.name


# ---------------------------------------------------------------------------
# Voice platforms
# ---------------------------------------------------------------------------


def _vapi_assistant(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    model, voice = data.get("model"), data.get("voice")
    return (
        isinstance(model, dict)
        and "provider" in model
        and isinstance(voice, dict)
        and ("provider" in voice or "voiceId" in voice)
        and bool({"transcriber", "firstMessage", "serverUrl", "server"} & set(data))
    )


def _vapi_tools(data: dict[str, Any]) -> list[str]:
    tools = []
    for tool in _dig(data, "model.tools") or []:
        if not isinstance(tool, dict):
            continue
        name = _dig(tool, "function.name") or tool.get("name") or tool.get("type")
        if isinstance(name, str):
            tools.append(name)
    return list(dict.fromkeys(tools))


def _read_vapi(rel: str, path: Path, data: Any, text: str, result: Result) -> bool:
    members = data.get("members") if isinstance(data, dict) else None
    if isinstance(members, list) and any(
        _vapi_assistant(m.get("assistant")) for m in members if isinstance(m, dict)
    ):
        squad = Found(
            platform="Vapi",
            name=data.get("name") or _stem(path),
            file=rel,
            kind="team",
            evidence="Vapi squad (members with assistants)",
            named=bool(data.get("name")),
        )
        result.agents.append(squad)
        for member in members:
            assistant = member.get("assistant") if isinstance(member, dict) else None
            if isinstance(assistant, dict) and _vapi_assistant(assistant):
                found = _vapi_found(rel, path, assistant, text)
                result.agents.append(found)
                squad.members.append(found.name)
        result.platforms.add("Vapi")
        return True
    if not _vapi_assistant(data):
        return False
    result.agents.append(_vapi_found(rel, path, data, text))
    result.platforms.add("Vapi")
    return True


def _vapi_found(rel: str, path: Path, data: dict[str, Any], text: str) -> Found:
    name = data.get("name")
    return Found(
        platform="Vapi",
        name=name or _stem(path),
        file=rel,
        line=_line_of(text, f'"{name}"') if name else 1,
        tools=_vapi_tools(data),
        model=_dig(data, "model.model"),
        evidence="Vapi assistant (model, voice, transcriber)",
        named=bool(name),
    )


def _read_retell(rel: str, path: Path, data: Any, text: str, result: Result) -> bool:
    if not isinstance(data, dict):
        return False
    engine = data.get("response_engine")
    if isinstance(engine, dict) and "type" in engine and "voice_id" in data:
        name = data.get("agent_name")
        result.agents.append(
            Found(
                platform="Retell",
                name=name or _stem(path),
                file=rel,
                evidence=f"Retell agent (response engine {engine.get('type')})",
                named=bool(name),
            )
        )
        result.platforms.add("Retell")
        return True
    if "general_prompt" in data and {"general_tools", "states", "begin_message"} & set(data):
        tools = _names(data.get("general_tools"), "name")
        for state in data.get("states") or []:
            if isinstance(state, dict):
                tools += _names(state.get("tools"), "name")
        result.agents.append(
            Found(
                platform="Retell",
                name=data.get("llm_name") or _stem(path),
                file=rel,
                tools=list(dict.fromkeys(tools)),
                model=data.get("model"),
                evidence="Retell LLM (general_prompt, tools)",
                named=bool(data.get("llm_name")),
            )
        )
        result.platforms.add("Retell")
        return True
    return False


def _read_elevenlabs(rel: str, path: Path, data: Any, text: str, result: Result) -> bool:
    if not isinstance(data, dict):
        return False
    prompt = _dig(data, "conversation_config.agent.prompt")
    if not isinstance(prompt, dict):
        return False
    tools = _names(prompt.get("tools"), "name")
    tools += [t for t in prompt.get("tool_ids") or [] if isinstance(t, str)]
    name = data.get("name")
    result.agents.append(
        Found(
            platform="ElevenLabs",
            name=name or _stem(path),
            file=rel,
            tools=list(dict.fromkeys(tools)),
            model=prompt.get("llm") if isinstance(prompt.get("llm"), str) else None,
            evidence="ElevenLabs agent (conversation_config.agent.prompt)",
            named=bool(name),
        )
    )
    result.platforms.add("ElevenLabs")
    return True


#: Node types a Bland pathway is made of; n8n, Flowise and Langflow nodes use none.
_BLAND_NODE_TYPES = {
    "Default",
    "Webhook",
    "End Call",
    "Transfer Call",
    "Knowledge Base",
    "Wait for Response",
    "Global",
    "Custom Tool",
    "SMS",
}


def _read_bland(rel: str, path: Path, data: Any, text: str, result: Result) -> bool:
    if not isinstance(data, dict) or not isinstance(data.get("edges"), list):
        return False
    nodes = [n for n in data.get("nodes") or [] if isinstance(n, dict)]
    typed = [n for n in nodes if n.get("type") in _BLAND_NODE_TYPES]
    if not typed or not any(
        isinstance(n.get("data"), dict) and ({"prompt", "text"} & set(n["data"])) for n in typed
    ):
        return False
    tools = [
        _dig(n, "data.name") or n.get("id")
        for n in typed
        if n.get("type") in ("Webhook", "Custom Tool", "Transfer Call", "SMS")
    ]
    result.agents.append(
        Found(
            platform="Bland",
            name=data.get("name") or _stem(path),
            file=rel,
            tools=[t for t in dict.fromkeys(tools) if isinstance(t, str)],
            evidence=f"Bland pathway ({len(typed)} nodes)",
            named=bool(data.get("name")),
        )
    )
    result.platforms.add("Bland")
    return True


# ---------------------------------------------------------------------------
# Workflow builders
# ---------------------------------------------------------------------------


def _read_n8n(rel: str, path: Path, data: Any, text: str, result: Result) -> bool:
    if not isinstance(data, dict) or not isinstance(data.get("connections"), dict):
        return False
    nodes = [n for n in data.get("nodes") or [] if isinstance(n, dict)]
    agents = [n for n in nodes if str(n.get("type", "")).endswith("langchain.agent")]
    if not agents:
        return False
    # n8n wires a tool or a model *into* an agent: the connection is keyed by the
    # tool's node name, with the agent as its target under `ai_tool`.
    feeds: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for source, outputs in data["connections"].items():
        for kind, groups in (outputs or {}).items():
            for group in groups or []:
                for link in group or []:
                    if isinstance(link, dict) and isinstance(link.get("node"), str):
                        feeds[link["node"]][kind].append(source)
    by_name = {n.get("name"): n for n in nodes}
    for agent in agents:
        name = agent.get("name") or "AI Agent"
        model = None
        for model_node in feeds[name].get("ai_languageModel", []):
            value = _dig(by_name.get(model_node, {}), "parameters.model")
            model = value.get("value") if isinstance(value, dict) else value
            if isinstance(model, str):
                break
        result.agents.append(
            Found(
                platform="n8n",
                name=f"{data.get('name')}: {name}" if data.get("name") else name,
                file=rel,
                line=_line_of(text, f'"{name}"'),
                tools=list(dict.fromkeys(feeds[name].get("ai_tool", []))),
                model=model if isinstance(model, str) else None,
                evidence="n8n workflow with an AI Agent node",
            )
        )
    result.platforms.add("n8n")
    return True


def _read_dify(rel: str, path: Path, data: Any, text: str, result: Result) -> bool:
    if not isinstance(data, dict) or data.get("kind") != "app":
        return False
    app = data.get("app")
    if not isinstance(app, dict) or "mode" not in app:
        return False
    tools = _names(_dig(data, "model_config.agent_mode.tools"), "tool_name", "tool_label")
    model = _dig(data, "model_config.model.name")
    for node in _dig(data, "workflow.graph.nodes") or []:
        info = node.get("data") if isinstance(node, dict) else None
        if not isinstance(info, dict):
            continue
        if info.get("type") == "tool":
            label = info.get("tool_name") or info.get("title")
            if isinstance(label, str):
                tools.append(label)
        elif info.get("type") == "agent":
            # An Agent node keeps its settings as `agent_parameters.<name>.value`.
            tools += _names(_dig(info, "agent_parameters.tools.value"), "tool_name", "tool_label")
            if model is None:
                model = _dig(info, "agent_parameters.model.value.model")
        elif info.get("type") == "llm" and model is None:
            model = _dig(info, "model.name")
    result.agents.append(
        Found(
            platform="Dify",
            name=app.get("name") or _stem(path),
            file=rel,
            tools=list(dict.fromkeys(tools)),
            model=model if isinstance(model, str) else None,
            confidence="high"
            if app.get("mode") in ("agent-chat", "advanced-chat", "workflow")
            else "medium",
            evidence=f"Dify app (mode {app.get('mode')})",
            named=bool(app.get("name")),
        )
    )
    result.platforms.add("Dify")
    return True


def _read_flowise(rel: str, path: Path, data: Any, text: str, result: Result) -> bool:
    if not isinstance(data, dict) or not isinstance(data.get("edges"), list):
        return False
    infos = [
        n["data"]
        for n in data.get("nodes") or []
        if isinstance(n, dict)
        and isinstance(n.get("data"), dict)
        and "category" in n["data"]
        and "baseClasses" in n["data"]
    ]
    agents = [i for i in infos if "agent" in str(i.get("category", "")).lower()]
    if not agents:
        return False
    tools = [str(i.get("label") or i.get("name")) for i in infos if i.get("category") == "Tools"]
    model = next(
        (
            _dig(i, "inputs.modelName")
            for i in infos
            if i.get("category") == "Chat Models" and isinstance(_dig(i, "inputs.modelName"), str)
        ),
        None,
    )
    result.agents.append(
        Found(
            platform="Flowise",
            name=_stem(path),
            file=rel,
            tools=list(dict.fromkeys(tools)),
            model=model,
            evidence=f"Flowise flow with {agents[0].get('label') or 'an agent'} node",
            named=False,
        )
    )
    result.platforms.add("Flowise")
    return True


def _read_langflow(rel: str, path: Path, data: Any, text: str, result: Result) -> bool:
    if not isinstance(data, dict) or "last_tested_version" not in data:
        return False
    nodes = _dig(data, "data.nodes")
    if not isinstance(nodes, list):
        return False
    agents, tools = [], []
    for node in nodes:
        info = node.get("data") if isinstance(node, dict) else None
        if not isinstance(info, dict):
            continue
        kind = str(info.get("type", ""))
        label = _dig(info, "node.display_name") or kind
        if kind == "Agent" or kind.endswith("Agent"):
            agents.append(label)
        elif kind.endswith(("Tool", "Tools")) or _dig(info, "node.tool_mode") is True:
            tools.append(str(label))
    if not agents:
        return False
    result.agents.append(
        Found(
            platform="Langflow",
            name=data.get("name") or _stem(path),
            file=rel,
            tools=list(dict.fromkeys(tools)),
            evidence="Langflow flow with an Agent component",
            named=bool(data.get("name")),
        )
    )
    result.platforms.add("Langflow")
    return True


def _voiceflow(rel: str, path: Path, data: Any, result: Result) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("project"), dict):
        return
    name = data["project"].get("name")
    result.agents.append(
        Found(
            platform="Voiceflow",
            name=name or _stem(path),
            file=rel,
            evidence="Voiceflow project file",
            named=bool(name),
        )
    )
    result.platforms.add("Voiceflow")


# ---------------------------------------------------------------------------
# Contact centre and enterprise platforms
# ---------------------------------------------------------------------------


def _dialogflow(path: Path, rel: str, data: dict[str, Any], result: Result) -> bool:
    """A Dialogflow agent export: ``agent.json`` beside the directories the export
    writes. CX has flows or playbooks; ES has intents."""
    folder = path.parent
    has = {p.name for p in folder.iterdir() if p.is_dir()} if folder.is_dir() else set()
    if "defaultLanguageCode" in data and has & {"flows", "playbooks"}:
        # Each tool and webhook is a directory (or a JSON file) named after it.
        platform = "Dialogflow CX"
        tools = sorted(
            {
                entry.stem
                for sub in ("tools", "webhooks")
                if (folder / sub).is_dir()
                for entry in (folder / sub).iterdir()
            }
        )
    elif "language" in data and "intents" in has:
        platform, tools = "Dialogflow", []
    else:
        return False
    name = data.get("displayName") or folder.name
    result.agents.append(
        Found(
            platform=platform,
            name=name,
            file=rel,
            tools=list(dict.fromkeys(tools)),
            evidence=f"{platform} agent export",
            named=bool(data.get("displayName")),
        )
    )
    result.platforms.add(platform)
    return True


def _copilot_folder(path: Path, root: Path, seen: set[Path], result: Result) -> None:
    """A Copilot Studio agent cloned by the VS Code extension: a folder of
    ``*.mcs.yml`` files, ``agent.mcs.yml`` at its top, actions under ``actions/``."""
    folder = path.parent
    while folder != root and not (folder / "agent.mcs.yml").exists():
        folder = folder.parent
    if not (folder / "agent.mcs.yml").exists() or folder in seen:
        return
    seen.add(folder)
    agent_file = folder / "agent.mcs.yml"
    name = folder.name
    try:
        data = yaml.load(agent_file.read_text(errors="ignore"), Loader=_Loader)  # noqa: S506
    except (OSError, yaml.YAMLError):
        data = None
    if isinstance(data, dict):
        for key in ("displayName", "name", "schemaName"):
            if isinstance(data.get(key), str):
                name = data[key]
                break
    actions = folder / "actions"
    tools = (
        sorted(p.name.removesuffix(".mcs.yml") for p in actions.glob("*.mcs.yml"))
        if actions.is_dir()
        else []
    )
    result.agents.append(
        Found(
            platform="Copilot Studio",
            name=name,
            file=str(agent_file.relative_to(root)),
            tools=tools,
            evidence="Copilot Studio agent folder (agent.mcs.yml)",
            named=name != folder.name,
        )
    )
    result.platforms.add("Copilot Studio")


#: Salesforce metadata, read with narrow patterns (never an XML parser: these files
#: come from repositories this scan does not trust).
_SF_KIND = re.compile(
    r"\.(genAiPlanner|genAiPlannerBundle|genAiPlugin|genAiFunction|bot)-meta\.xml$"
)
_SF_LABEL = re.compile(r"<masterLabel>([^<]{1,200})</masterLabel>")
_SF_PLUGIN_REF = re.compile(r"<genAiPluginName>([^<]{1,200})</genAiPluginName>")
_SF_FUNCTION_REF = re.compile(r"<(?:functionName|genAiFunctionName)>([^<]{1,200})</")


def _salesforce_or_bot_xml(path: Path, rel: str, text: str, result: Result) -> None:
    match = _SF_KIND.search(path.name)
    if match is None:
        if path.name == "bot.xml" and path.parent.parent.name == "bots":
            # A Power Platform solution export: bots/<schema name>/bot.xml.
            result.agents.append(
                Found(
                    platform="Copilot Studio",
                    name=path.parent.name,
                    file=rel,
                    confidence="medium",
                    evidence="Power Platform solution bot (bots/*/bot.xml)",
                    named=False,
                )
            )
            result.platforms.add("Copilot Studio")
        return
    kind = match.group(1)
    api_name = path.name.split(".")[0]
    label_match = _SF_LABEL.search(text)
    label = label_match.group(1).strip() if label_match else api_name
    if kind in ("genAiPlanner", "genAiPlannerBundle"):
        result.sf_planners.append((label, rel, _SF_PLUGIN_REF.findall(text)))
    elif kind == "genAiPlugin":
        result.sf_plugins[api_name] = _SF_FUNCTION_REF.findall(text)
    elif kind == "genAiFunction":
        result.sf_functions.add(api_name)
    elif kind == "bot":
        result.sf_bots.append((label, rel))
    result.platforms.add("Agentforce")


def _agent_script(rel: str, text: str, result: Result) -> None:
    """An Agentforce Agent Script file: ``config:`` with an ``agent_name``, and
    ``topic`` blocks whose ``actions`` the agent can call."""
    name = re.search(r"""(?m)^\s*(?:agent_name|developer_name)\s*:\s*["']?([\w .-]{1,120})""", text)
    if name is None or not re.search(r"(?m)^\s*topic\s+\w+", text):
        return
    actions = re.findall(r"(?m)^\s{4,}(\w+)\s*:\s*\n\s+target\s*:", text)
    result.agents.append(
        Found(
            platform="Agentforce",
            name=name.group(1).strip(),
            file=rel,
            line=_line_of(text, name.group(0).strip()),
            tools=list(dict.fromkeys(actions)),
            evidence="Agentforce Agent Script (.agent)",
        )
    )
    result.platforms.add("Agentforce")


def _salesforce_finish(result: Result) -> None:
    planners = result.sf_planners
    if not planners:
        # Topics and actions without a planner in the repository: the agent is the
        # Bot record when there is one, else nothing that can be named.
        planners = [(label, rel, list(result.sf_plugins)) for label, rel in result.sf_bots]
    for label, rel, plugins in planners:
        tools: list[str] = []
        for plugin in plugins or list(result.sf_plugins):
            tools += result.sf_plugins.get(plugin, [])
        if not tools and len(planners) == 1:
            # One agent and actions no topic lists: they can only be its.
            tools = sorted(result.sf_functions)
        result.agents.append(
            Found(
                platform="Agentforce",
                name=label,
                file=rel,
                tools=list(dict.fromkeys(tools)),
                evidence="Agentforce agent metadata (planner, topics, actions)",
            )
        )


#: CloudFormation resource types, and where each keeps its name, tools and model.
_CFN_AGENTS = {
    "AWS::Bedrock::Agent": ("Bedrock Agents", "AgentName", "ActionGroups", "FoundationModel"),
    "AWS::BedrockAgentCore::Runtime": ("Bedrock AgentCore", "AgentRuntimeName", None, None),
    "AWS::Lex::Bot": ("Amazon Lex", "Name", None, None),
}


def _read_cloudformation(rel: str, path: Path, data: Any, text: str, result: Result) -> bool:
    resources = data.get("Resources") if isinstance(data, dict) else None
    if not isinstance(resources, dict):
        return False
    hit = False
    for logical, resource in resources.items():
        if not isinstance(resource, dict) or resource.get("Type") not in _CFN_AGENTS:
            continue
        platform, name_key, tools_key, model_key = _CFN_AGENTS[resource["Type"]]
        props = resource.get("Properties") or {}
        name = props.get(name_key) if isinstance(props.get(name_key), str) else None
        tools = _names(props.get(tools_key), "ActionGroupName") if tools_key else []
        model = (
            props.get(model_key) if model_key and isinstance(props.get(model_key), str) else None
        )
        result.agents.append(
            Found(
                platform=platform,
                name=name or str(logical),
                file=rel,
                line=_line_of(text, str(logical)),
                tools=tools,
                model=model,
                evidence=f"CloudFormation {resource['Type']}",
                named=bool(name),
            )
        )
        result.platforms.add(platform)
        hit = True
    return hit


_TF_RESOURCE = re.compile(r'(?m)^\s*resource\s+"(aws_[a-z0-9_]+)"\s+"([\w-]+)"\s*\{')
_TF_AGENTS = {
    "aws_bedrockagent_agent": ("Bedrock Agents", "agent_name"),
    "aws_bedrockagentcore_agent_runtime": ("Bedrock AgentCore", "agent_runtime_name"),
    "aws_lexv2models_bot": ("Amazon Lex", "name"),
}


def _terraform(rel: str, text: str, result: Result) -> None:
    blocks = list(_TF_RESOURCE.finditer(text))
    groups: dict[str, list[str]] = defaultdict(list)
    for i, block in enumerate(blocks):
        body = text[block.end() : blocks[i + 1].start() if i + 1 < len(blocks) else len(text)]
        if block.group(1) == "aws_bedrockagent_agent_action_group":
            group = re.search(r'action_group_name\s*=\s*"([^"]+)"', body)
            agent = re.search(r"agent_id\s*=\s*aws_bedrockagent_agent\.([\w-]+)\.", body)
            if group:
                groups[agent.group(1) if agent else ""].append(group.group(1))
    agents = [b for b in blocks if b.group(1) in _TF_AGENTS]
    for i, block in enumerate(blocks):
        kind, logical = block.group(1), block.group(2)
        if kind not in _TF_AGENTS:
            continue
        platform, name_key = _TF_AGENTS[kind]
        body = text[block.end() : blocks[i + 1].start() if i + 1 < len(blocks) else len(text)]
        name = re.search(rf'{name_key}\s*=\s*"([^"$]+)"', body)
        model = re.search(r'foundation_model\s*=\s*"([^"$]+)"', body)
        result.agents.append(
            Found(
                platform=platform,
                name=name.group(1) if name else logical,
                file=rel,
                line=text.count("\n", 0, block.start()) + 1,
                # An action group whose agent_id is not a reference to an agent in
                # this file is the agent's only when the file defines one.
                tools=groups.get(logical, []) + (groups.get("", []) if len(agents) == 1 else []),
                model=model.group(1) if model else None,
                evidence=f"Terraform {kind}",
                named=bool(name),
            )
        )
        result.platforms.add(platform)


#: Genesys Architect flow types that are a bot (an IVR call flow routes; it does not
#: converse with a model, so it is not claimed as an agent).
_GENESYS_BOTS = ("botFlow", "digitalBotFlow")


def _read_genesys(rel: str, path: Path, data: Any, text: str, result: Result) -> bool:
    if not isinstance(data, dict):
        return False
    kind = next((k for k in _GENESYS_BOTS if isinstance(data.get(k), dict)), None)
    if kind is None or "name" not in data[kind]:
        return False
    result.agents.append(
        Found(
            platform="Genesys Cloud",
            name=str(data[kind]["name"]),
            file=rel,
            confidence="medium",
            evidence=f"Genesys Architect {kind}",
        )
    )
    result.platforms.add("Genesys Cloud")
    return True


#: Tried in order on every JSON or YAML file; the first that recognises it wins.
_READERS = (
    _read_vapi,
    _read_retell,
    _read_elevenlabs,
    _read_n8n,
    _read_dify,
    _read_langflow,
    _read_flowise,
    _read_bland,
    _read_cloudformation,
    _read_genesys,
)

#: API hosts and AWS service names that say which hosted agent platform code calls.
_API_PATTERNS = (
    (re.compile(r"api\.vapi\.ai"), "Vapi"),
    (re.compile(r"api\.retellai\.com"), "Retell"),
    (re.compile(r"api\.elevenlabs\.io/v1/convai"), "ElevenLabs"),
    (re.compile(r"api\.bland\.ai"), "Bland"),
    (re.compile(r"api\.synthflow\.ai"), "Synthflow"),
    (re.compile(r"api\.telnyx\.com/v2/ai"), "Telnyx"),
    (re.compile(r"atoms(?:-api)?\.smallest\.ai"), "Smallest AI"),
    (re.compile(r"api\.agora\.io/api/conversational-ai-agent"), "Agora"),
    (
        re.compile(r"""client\(\s*["'](?:bedrock-agent-runtime|bedrock-agent)["']"""),
        "Bedrock Agents",
    ),
    (re.compile(r"""client\(\s*["']bedrock-agentcore(?:-control)?["']"""), "Bedrock AgentCore"),
    (re.compile(r"""client\(\s*["']lexv2-(?:runtime|models)["']"""), "Amazon Lex"),
    (re.compile(r"""client\(\s*["'](?:connect|qconnect)["']"""), "Amazon Connect"),
)
