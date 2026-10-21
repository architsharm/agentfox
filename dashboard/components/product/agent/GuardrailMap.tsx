"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  getStraightPath,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import Link from "next/link";
import { Logo } from "@/components/product/Logo";
import { useRouter } from "next/navigation";
import { Bot, Cpu, FileText, Plus, Search, User, Wrench, X, type LucideIcon } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { ModePill, Pill } from "@/components/kit";
import {
  GROUP_BY,
  PERMISSION,
  STRICTNESS,
  feeds,
  settingsFor,
  strictnessOf,
  TONE_LABEL,
  TOOL_FILTERS,
  counts,
  filterTools,
  groupSummary,
  groupTools,
  permissionCall,
  ruleChange,
  ruleSetting,
  toolTone,
  type AgentMap,
  type GroupBy,
  type MapRule,
  type MapTool,
  type Permission,
  type RuleSetting,
  type Stage,
  type Stats,
  type ToolFilter,
  type ToolGroup,
} from "@/lib/product/guardrailMap";
import { IMPACT, detectorName, ruleTitle } from "@/lib/product/vocab";
import { AttackTests } from "./AttackTests";

export type { AgentMap, MapRule } from "@/lib/product/guardrailMap";

/** What the inspector shows: a step, a tool, a group of tools, or every tool. Nothing: the project. */
type Selected = { kind: "stage" | "tool" | "group" | "tools"; key: string } | null;

const SOURCE: Record<string, string> = { code: "In code", granted: "Granted", seen: "Called" };

function sourceLabel(tl: MapTool): string {
  return (tl.sources || []).map((x) => SOURCE[x]).join(" · ");
}

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

// --- nodes -----------------------------------------------------------------------
//
// Laid out like a guardrails diagram. The user is the only thing outside. Everything
// else is inside one tinted box, the project: each agent (just its loop, which is not
// guarded itself), and what each agent reaches: its LLM, its tools, its documents and
// memory. Guardrails are rails on the lines between them, each a labelled pill: our
// mark and a count where guardrails are set, a "+" where none are yet.

/** The kind badge a card starts with: an icon in its colour, and its name. */
function Kind({ icon: Icon, label }: { icon: LucideIcon; label: string }) {
  return (
    <span className="gm-kind">
      <span className="gm-kind-icon" aria-hidden>
        <Icon size={13} strokeWidth={2} />
      </span>
      {label}
    </span>
  );
}

export const NODE_KINDS: { key: string; label: string; icon: LucideIcon }[] = [
  { key: "user", label: "User", icon: User },
  { key: "agent", label: "Agent", icon: Bot },
  { key: "llm", label: "LLM", icon: Cpu },
  { key: "tool", label: "Tools", icon: Wrench },
  { key: "docs", label: "Documents & memory", icon: FileText },
];

/** Our mark: "guardrails are here". */
function Mark({ size = 18 }: { size?: number }) {
  return <Logo size={size} />;
}

/** How many guardrails act at a step: rules that enforce or watch. */
function railCount(s: Stage | undefined): number {
  if (!s) return 0;
  const c = counts(s.rules);
  return c.enforcing + c.watching;
}

/** Whether anything guards this step: rules that enforce or watch, or detectors. */
function guarded(s: Stage | undefined): boolean {
  return Boolean(s && (railCount(s) || s.detectors.length));
}

/** The user, outside the box: messages go in from here and replies come back. */
function UserNode() {
  return (
    <div className="gm-node gm-end">
      <Handle type="source" position={Position.Right} id="out" style={{ top: IN_AT }} />
      <Handle type="target" position={Position.Right} id="back" style={{ top: OUT_AT }} />
      <User size={18} aria-hidden />
      User
    </div>
  );
}

/** The project: one tinted box around every agent and everything they reach. */
function SystemNode({ data }: NodeProps<Node<{ title: string; sub: string; w: number; h: number }>>) {
  return (
    <div className="gm-system" style={{ width: data.w, height: data.h }}>
      <span className="gm-system-head">
        <strong>{data.title}</strong>
        <span>{data.sub}</span>
      </span>
    </div>
  );
}

/** An agent: the loop that decides what to do next. Guardrails sit on what it reaches, not on it. */
function AgentNode({
  data,
}: NodeProps<Node<{ name: string; framework?: string | null; active: boolean; target?: string; handsOffTo?: number }>>) {
  return (
    <div
      className={`gm-node gm-agent${data.active ? " gm-agent-active" : ""}${data.target ? " gm-agent-target" : ""}`}
      title={data.target ? `${data.target} hands off to this agent` : undefined}
    >
      <Handle type="target" position={Position.Left} id="in" style={{ top: IN_AT }} />
      <Handle type="source" position={Position.Left} id="reply" style={{ top: OUT_AT }} />
      <Handle type="source" position={Position.Top} id="ask" style={{ left: CALLS_AT }} />
      <Handle type="target" position={Position.Top} id="answer" style={{ left: RESULTS_AT }} />
      <Handle type="source" position={Position.Bottom} id="calls" style={{ left: CALLS_AT }} />
      <Handle type="target" position={Position.Bottom} id="results" style={{ left: RESULTS_AT }} />
      <Handle type="target" position={Position.Right} id="context" />
      <Kind icon={Bot} label="Agent" />
      <strong className="gm-ellipsis">{data.name}</strong>
      <span className="gm-sub">{data.framework ? `${data.framework} · ` : ""}decides what to do next</span>
      {data.handsOffTo ? (
        <span className="gm-handoff-note">
          hands off to {plural(data.handsOffTo, "agent")}
          {data.active ? " (outlined)" : " · click to show"}
        </span>
      ) : null}
    </div>
  );
}

/** The model the agent thinks with. */
function LlmNode({ data }: NodeProps<Node<{ models: string[] }>>) {
  return (
    <div className="gm-node gm-llm">
      <Handle type="target" position={Position.Bottom} id="in" style={{ left: CALLS_AT }} />
      <Handle type="source" position={Position.Bottom} id="out" style={{ left: RESULTS_AT }} />
      <Kind icon={Cpu} label={data.models.length > 1 ? `${data.models.length} LLMs` : "LLM"} />
      {data.models.length ? (
        <strong className="gm-ellipsis k-mono" title={data.models.join(", ")}>
          {data.models[0]}
          {data.models.length > 1 ? ` +${data.models.length - 1}` : ""}
        </strong>
      ) : (
        <strong className="gm-sub">model not found in code</strong>
      )}
    </div>
  );
}

/** Documents & memory the agent reads. */
function DocsNode() {
  return (
    <div className="gm-node gm-docs">
      <Handle type="source" position={Position.Left} />
      <Kind icon={FileText} label="Documents & memory" />
    </div>
  );
}

/** One agent's tools in a tinted box; the tools sit inside it. */
function BoxNode({ data }: NodeProps<Node<{ title: string; w: number; h: number; selected: boolean; callsAt: number; resultsAt: number }>>) {
  return (
    <div className={`gm-box${data.selected ? " gm-selected" : ""}`} style={{ width: data.w, height: data.h }}>
      <Handle type="target" position={Position.Top} id="in" style={{ left: data.callsAt }} />
      <Handle type="source" position={Position.Top} id="out" style={{ left: data.resultsAt }} />
      <span className="gm-box-head">
        <Kind icon={Wrench} label={data.title} />
      </span>
    </div>
  );
}

/** One tool: wrench and name; our mark if it has guardrails of its own; a tag only when it is not simply allowed. */
function ToolNode({ data }: NodeProps<Node<{ tool: MapTool; selected: boolean }>>) {
  const tl = data.tool;
  const p = PERMISSION[tl.permission];
  const own = tl.rules.length + tl.ladders.length;
  return (
    <div className={`gm-tool gm-perm-${tl.permission}${data.selected ? " gm-selected" : ""}`} title={`${tl.key} · ${p.label}${own ? ` · ${plural(own, "guardrail")} on this tool` : ""}`}>
      <Wrench size={12} aria-hidden className="gm-tool-icon" />
      <span className="k-mono gm-ellipsis gm-tool-key">{shortKey(tl.key)}</span>
      {tl.permission !== "allowed" && <span className={`gm-perm gm-perm-${p.tone}`}>{p.label}</span>}
      {own ? (
        <span className="gm-tool-mark" aria-label={plural(own, "guardrail")}>
          <Mark size={14} />
        </span>
      ) : null}
    </div>
  );
}

function MoreNode({ data }: NodeProps<Node<{ label: string }>>) {
  return (
    <div className="gm-tool gm-more" title="Show every tool">
      {data.label}
    </div>
  );
}

const NODE_TYPES = {
  user: UserNode,
  system: SystemNode,
  agent: AgentNode,
  llm: LlmNode,
  docs: DocsNode,
  box: BoxNode,
  tool: ToolNode,
  more: MoreNode,
};

// --- rails (edges) ------------------------------------------------------------------

/** Each rail's name on the map, and what it checks, for the pill and the panel. */
export const RAIL: Record<string, { name: string; what: string; between: [string, string] }> = {
  input: { name: "Input", what: "What users send, before the agent sees it.", between: ["User", "Agent"] },
  output: { name: "Output", what: "What the agent sends back to users.", between: ["Agent", "User"] },
  prompt: { name: "To the LLM", what: "Everything sent to the LLM: user message, documents, tool results.", between: ["Agent", "LLM"] },
  response: { name: "From the LLM", what: "What the LLM answers, after each call.", between: ["LLM", "Agent"] },
  completion: { name: "Done check", what: "The agent saying it's done, checked against what happened.", between: ["Agent", "User"] },
  tool_call: { name: "Tool calls", what: "Every tool the agent calls, with its arguments.", between: ["Agent", "Tools"] },
  tool_result: { name: "Tool results", what: "What tools return, before the agent reads it.", between: ["Tools", "Agent"] },
  context: { name: "Retrieval & memory", what: "Documents, memory and other agents' messages.", between: ["Documents & memory", "Agent"] },
};

type GuardData = {
  /** Where along the line the pill sits (0–1). */
  at?: number;
  /** Which side of the line the pill sits on; centred on it when unset. */
  side?: "above" | "below" | "left" | "right";
  stage?: Stage;
  title: string;
  selected?: boolean;
  hovered?: boolean;
  onPick?: () => void;
  onHover?: (on: boolean) => void;
};

/**
 * A rail: a labelled pill on the line where guardrails apply. Our mark and a count
 * when something guards it, a "+" when not. The line, a wide band around it and the
 * pill all open the same panel.
 */
function GuardEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style, data }: EdgeProps<Edge<GuardData>>) {
  // Straight, never bent: the line is the rail, read at a glance.
  void sourcePosition;
  void targetPosition;
  const [path, mx, my] = getStraightPath({ sourceX, sourceY, targetX, targetY });
  const t = data?.at;
  const x = t === undefined ? mx : sourceX + (targetX - sourceX) * t;
  const y = t === undefined ? my : sourceY + (targetY - sourceY) * t;
  const on = guarded(data?.stage);
  const n = railCount(data?.stage);
  const sel = Boolean(data?.selected);
  const lit = sel || Boolean(data?.hovered);
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        interactionWidth={44}
        style={{ ...style, ...(lit ? { stroke: "var(--af-link)", strokeWidth: sel ? 2.5 : 2 } : {}) }}
      />
      {data?.stage && (
        <EdgeLabelRenderer>
          <button
            type="button"
            className={`gm-rail nodrag nopan${on ? " gm-rail-on" : " gm-rail-off"}${sel ? " gm-selected" : ""}${lit ? " gm-rail-lit" : ""}`}
            style={{ transform: `translate(${x}px, ${y}px) ${PILL_SIDE[data.side ?? "on"]}` }}
            onClick={data.onPick}
            onMouseEnter={() => data.onHover?.(true)}
            onMouseLeave={() => data.onHover?.(false)}
            onFocus={() => data.onHover?.(true)}
            onBlur={() => data.onHover?.(false)}
            aria-label={`${data.title} rail: ${on ? `${n} guardrails` : "no guardrails yet"}. Open.`}
          >
            {on ? <Mark size={15} /> : <span className="gm-mark-plus" aria-hidden>+</span>}
            <span className="gm-rail-name">{data.title}</span>
            {on && n ? <span className="gm-rail-count">{n}</span> : null}
          </button>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

/** Moves a pill off its line to one side, so lines side by side never share space. */
const PILL_SIDE = {
  on: "translate(-50%, -50%)",
  above: "translate(-50%, calc(-100% - 6px))",
  below: "translate(-50%, 6px)",
  left: "translate(calc(-100% - 10px), -50%)",
  right: "translate(10px, -50%)",
} as const;

const EDGE_TYPES = { guard: GuardEdge };

// --- layout ----------------------------------------------------------------------

/** Tools drawn in an agent's box before "+N more"; expanded, up to BOX_MAX. */
const BOX_FIRST = 6;
const BOX_MAX = 24;
const TOOL_W = 200;
const TOOL_H = 34;
const GAP = 10;
const PAD = 16;
const HEAD = 48;

/**
 * Every line on the map is a whole number of units long (the gap between the two
 * cards it joins): the user's lines one unit, every other line between one and three.
 * Cards have fixed sizes (af-theme.css, "v4") so the lengths come out exact.
 */
const UNIT = 140;
const units = (n: number) => Math.min(3, Math.max(1, n)) * UNIT;
const LENGTH = { user: 1, llm: 1.5, tools: 1.5, context: 1.5 } as const;

const USER_W = 96;
const AGENT_W = 180;
const AGENT_H = 100;
const LLM_W = 180;
const LLM_H = 60;
const DOCS_W = 160;
const DOCS_H = 44;
/** Where the lines meet the cards, so facing handles line up and the lines run straight. */
const IN_AT = "30%";
const OUT_AT = "70%";
const CALLS_AT = "32%";
const RESULTS_AT = "68%";
/** Room between one agent's area and the next, and around the inside of the project box. */
const CELL_GAP = 90;
const INSET = 28;
const TOP = 44;

/** Node and edge ids carry the agent: `<slug>|<what>`. */
const nid = (slug: string, what: string) => `${slug}|${what}`;

/**
 * The agents users talk to directly. One agent: it. Several: the one that hands work
 * to the most others (a triage agent), or every one if none hands off.
 */
function entryAgents(maps: AgentMap[]): string[] {
  if (maps.length <= 1) return maps.map((m) => m.agent.slug);
  const inProject = new Set(maps.map((m) => m.agent.slug));
  const out = (m: AgentMap) => m.subagents.filter((s) => inProject.has(s.slug) && s.slug !== m.agent.slug).length;
  const most = Math.max(...maps.map(out));
  return most > 0 ? maps.filter((m) => out(m) === most).map((m) => m.agent.slug) : maps.map((m) => m.agent.slug);
}

/**
 * One agent's area, top to bottom: its LLM; the agent, with documents & memory to its
 * right; its tools in a box. The user stands one unit to the left of the entry agent,
 * outside the project box.
 *
 *            [LLM]
 *              |
 *   User ── [Agent] ── [Documents & memory]
 *              |
 *          [ tools ]
 */
function layout(
  maps: AgentMap[],
  drawnFor: (m: AgentMap) => { tools: MapTool[]; hidden: number },
  active: string,
  selected: Selected,
  pick: (slug: string, stage: string) => void,
  project: string,
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const arrow = { type: MarkerType.ArrowClosed, width: 14, height: 14 };
  const entryList = entryAgents(maps);
  const entries = new Set(entryList);
  const isSel = (slug: string, kind: string, key: string) => slug === active && selected?.kind === kind && selected.key === key;
  const inProject = new Set(maps.map((m) => m.agent.slug));
  const activeMap = maps.find((m) => m.agent.slug === active);
  const targets = new Set((activeMap?.subagents ?? []).map((s) => s.slug).filter((s) => s !== active && inProject.has(s)));

  // Entry agents first. When every agent is an entry, stack them in one column so the
  // user reaches each without crossing another; otherwise a grid, four to a row.
  const ordered = [...maps].sort((a, b) => Number(entries.has(b.agent.slug)) - Number(entries.has(a.agent.slug)));
  const many = maps.length > 1;
  const COLS = !many || entries.size > 1 ? 1 : Math.min(4, maps.length);
  const toolCols = many ? 1 : 2;
  const boxW = (cells: number) => {
    const cols = Math.min(toolCols, Math.max(1, cells));
    return PAD * 2 + cols * TOOL_W + (cols - 1) * GAP;
  };
  const cellW = Math.max(AGENT_W + units(LENGTH.context) + DOCS_W, boxW(toolCols) - 10) + CELL_GAP;

  // The agent's position inside its area, and the box below it.
  const agentDy = LLM_H + units(LENGTH.llm);
  const boxDy = agentDy + AGENT_H + units(LENGTH.tools);
  const rowH: number[] = [];
  const drawn = ordered.map((m) => drawnFor(m));
  ordered.forEach((_, idx) => {
    const row = Math.floor(idx / COLS);
    const { tools, hidden } = drawn[idx];
    const cells = tools.length + (hidden ? 1 : 0);
    const rowsN = cells ? Math.ceil(cells / Math.min(toolCols, cells)) : 0;
    const boxH = cells ? HEAD + rowsN * TOOL_H + (rowsN - 1) * GAP + PAD : 0;
    rowH[row] = Math.max(rowH[row] ?? 0, boxDy + boxH + CELL_GAP);
  });
  const rowTop = (r: number) => TOP + rowH.slice(0, r).reduce((a, b) => a + b, 0);

  // The box's left edge sits just inside the agents' column, so the user's lines cross
  // it close to the agent and their pills stay outside.
  const left = 0;
  const sysX = left - INSET;
  let right = left + AGENT_W;
  let bottom = 0;
  const agentAt: Record<string, { x: number; y: number }> = {};

  ordered.forEach((map, idx) => {
    const slug = map.agent.slug;
    const col = idx % COLS;
    const row = Math.floor(idx / COLS);
    const x = left + col * cellW;
    const top = rowTop(row);
    const ay = top + agentDy;
    agentAt[slug] = { x, y: ay };
    const stage = (key: string) => map.stages.find((s) => s.key === key);
    const rail = (key: string, source: string, target: string, extra: Partial<Edge>, place: Partial<GuardData> = {}) =>
      edges.push({
        id: nid(slug, `edge:${key}`),
        source,
        target,
        type: "guard",
        markerEnd: arrow,
        data: { stage: stage(key), title: RAIL[key]?.name ?? key, selected: isSel(slug, "stage", key), onPick: () => pick(slug, key), ...place },
        ...extra,
      });

    const agentId = nid(slug, "agent");
    const handsOffTo = map.subagents.filter((s) => s.slug !== slug && inProject.has(s.slug)).length;
    nodes.push({
      id: agentId,
      type: "agent",
      position: { x, y: ay },
      data: {
        name: map.agent.name,
        framework: map.agent.framework,
        active: slug === active && many,
        target: targets.has(slug) ? activeMap?.agent.name : undefined,
        handsOffTo,
      },
    });

    // Its LLM, straight above.
    nodes.push({ id: nid(slug, "llm"), type: "llm", position: { x: x + (AGENT_W - LLM_W) / 2, y: top }, data: { models: map.agent.models || [] } });
    // Up on the left, what goes to it; down on the right, what it answers.
    rail("prompt", agentId, nid(slug, "llm"), { sourceHandle: "ask", targetHandle: "in", style: { stroke: "var(--af-link)" } }, { side: "left" });
    rail("response", nid(slug, "llm"), agentId, { sourceHandle: "out", targetHandle: "answer", style: { stroke: "var(--af-link)", strokeDasharray: "5 4" } }, { side: "right" });

    // Documents & memory, to its right, level with it.
    if (stage("context")) {
      const dx = x + AGENT_W + units(LENGTH.context);
      nodes.push({ id: nid(slug, "docs"), type: "docs", position: { x: dx, y: ay + (AGENT_H - DOCS_H) / 2 }, data: {} });
      rail("context", nid(slug, "docs"), agentId, { targetHandle: "context", style: { strokeDasharray: "4 4" } }, { side: "above" });
      right = Math.max(right, dx + DOCS_W);
    }

    // Its tools, in a box straight below. Calls go down on the left, results come back
    // up on the right; each pill sits on the outer side of its own line.
    const { tools, hidden } = drawn[idx];
    const cells = tools.length + (hidden ? 1 : 0);
    if (cells) {
      const cols = Math.min(toolCols, cells);
      const rowsN = Math.ceil(cells / cols);
      const w = boxW(cells);
      const h = HEAD + rowsN * TOOL_H + (rowsN - 1) * GAP + PAD;
      const bx = x - 10;
      const by = top + boxDy;
      const boxId = nid(slug, "box");
      const callsAt = x + (AGENT_W * parseFloat(CALLS_AT)) / 100 - bx;
      const resultsAt = x + (AGENT_W * parseFloat(RESULTS_AT)) / 100 - bx;
      nodes.push({ id: boxId, type: "box", position: { x: bx, y: by }, data: { title: plural(map.tools.length, "tool"), w, h, selected: slug === active && selected?.kind === "tools", callsAt, resultsAt } });
      const at = (i: number) => ({ x: PAD + (i % cols) * (TOOL_W + GAP), y: HEAD + Math.floor(i / cols) * (TOOL_H + GAP) });
      tools.forEach((tl, i) =>
        nodes.push({ id: nid(slug, `tool:${tl.key}`), type: "tool", parentId: boxId, extent: "parent", position: at(i), data: { tool: tl, selected: isSel(slug, "tool", tl.key) } }),
      );
      if (hidden) nodes.push({ id: nid(slug, "more"), type: "more", parentId: boxId, extent: "parent", position: at(tools.length), data: { label: `+${hidden} more` } });
      rail("tool_call", agentId, boxId, { sourceHandle: "calls", targetHandle: "in" }, { side: "left" });
      rail("tool_result", boxId, agentId, { sourceHandle: "out", targetHandle: "results", style: { strokeDasharray: "4 4" } }, { side: "right" });
      right = Math.max(right, bx + w);
      bottom = Math.max(bottom, by + h);
    }
    bottom = Math.max(bottom, ay + AGENT_H);
  });

  // The project box, drawn underneath everything.
  nodes.unshift({
    id: "system",
    type: "system",
    position: { x: sysX, y: 0 },
    data: {
      title: project,
      sub: many ? `${maps.length} agents · everything inside is yours` : "your agent and everything it reaches",
      w: right + INSET - sysX,
      h: bottom + INSET,
    },
    style: { zIndex: -1 },
    selectable: false,
    draggable: false,
  } as Node);

  // The user, outside the box, one unit from the entry agent: level with it, so the
  // Input and Output lines run straight across. With several entry agents (stacked),
  // the user stands level with the middle of them.
  const ys = entryList.map((s) => agentAt[s]?.y).filter((v): v is number => v !== undefined);
  const userY = ys.length ? (Math.min(...ys) + Math.max(...ys)) / 2 : agentDy + TOP;
  nodes.push({ id: "user", type: "user", position: { x: left - units(LENGTH.user) - USER_W, y: userY }, data: {} });
  for (const slug of entryList) {
    const agentId = nid(slug, "agent");
    const map = maps.find((m) => m.agent.slug === slug)!;
    const stage = (key: string) => map.stages.find((s) => s.key === key);
    const common = { type: "guard", markerEnd: arrow } as const;
    // Pills near the user end, so they sit outside the project box: Input above its line, Output below.
    edges.push({
      ...common,
      id: nid(slug, "edge:input"),
      source: "user",
      sourceHandle: "out",
      target: agentId,
      targetHandle: "in",
      data: { stage: stage("input"), title: RAIL.input.name, selected: isSel(slug, "stage", "input"), onPick: () => pick(slug, "input"), at: 0.38, side: "above" },
    });
    edges.push({
      ...common,
      id: nid(slug, "edge:output"),
      source: agentId,
      sourceHandle: "reply",
      target: "user",
      targetHandle: "back",
      data: { stage: stage("output"), title: RAIL.output.name, selected: isSel(slug, "stage", "output"), onPick: () => pick(slug, "output"), at: 0.62, side: "below" },
    });
  }
  return { nodes, edges };
}

/** The tools an agent's box draws: the first few, all when expanded, and always the one selected. */
function boxTools(visible: MapTool[], expanded: boolean, selectedKey: string | null): MapTool[] {
  const limit = visible.length <= BOX_FIRST + 1 ? visible.length : expanded ? BOX_MAX : BOX_FIRST;
  const shown = visible.slice(0, limit);
  if (selectedKey && !shown.some((t) => t.key === selectedKey)) {
    const t = visible.find((x) => x.key === selectedKey);
    if (t) shown[shown.length - 1] = t;
  }
  return shown;
}

// --- changes -----------------------------------------------------------------------

async function send(url: string, method: string, body?: unknown): Promise<{ ok: boolean; data: any }> {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, data };
}

function errorOf(data: any, fallback: string): string {
  const d = data?.detail;
  if (typeof d === "string") return d;
  if (d && typeof d.message === "string") return d.message;
  return fallback;
}

/** Block / ask / watch / off for one rule, for this agent only. */
function RuleControl({ rule, slug }: { rule: MapRule; slug: string }) {
  const options = settingsFor(rule);
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ error: boolean; text: string } | null>(null);
  const current = ruleSetting(rule);
  if (!rule.policy) return null;

  const set = async (to: RuleSetting) => {
    if (to === current) return;
    setBusy(true);
    setNote(null);
    const r = await send(`/api/policies/${encodeURIComponent(rule.policy!)}/rules/${encodeURIComponent(rule.id)}/scope`, "POST", ruleChange(slug, to));
    setBusy(false);
    if (!r.ok) return setNote({ error: true, text: errorOf(r.data, "Could not change this rule.") });
    const watching = (r.data.agents || []).some((a: any) => a.mode !== "enforce");
    setNote({ error: false, text: watching ? "Saved for this agent. Watching first." : "Saved for this agent." });
    router.refresh();
  };
  const reset = async () => {
    setBusy(true);
    setNote(null);
    const r = await send(`/api/agents/${encodeURIComponent(slug)}/rules/${encodeURIComponent(rule.id)}`, "DELETE");
    setBusy(false);
    if (!r.ok) return setNote({ error: true, text: errorOf(r.data, "Could not reset this rule.") });
    router.refresh();
  };

  return (
    <div className="gm-control">
      <div className="k-seg" role="group" aria-label={`What ${ruleTitle(rule.id, rule.description)} does for this agent`}>
        {options.map((o) => (
          <button key={o.key} type="button" title={o.title} disabled={busy} className={current === o.key ? "active" : ""} aria-pressed={current === o.key} onClick={() => set(o.key)}>
            {o.label}
          </button>
        ))}
      </div>
      {/* Only a copy of a workspace rule can go back to it; a rule only this agent has would be deleted. */}
      {rule.own && rule.workspace && (
        <button type="button" className="gm-link" disabled={busy} onClick={reset} title={`Back to the workspace rule: ${rule.workspace.enabled ? rule.workspace.effect : "off"}`}>
          Reset
        </button>
      )}
      {note && (
        <span className={note.error ? "k-act-error" : "gm-saved"} role={note.error ? "alert" : "status"}>
          {note.text}
        </span>
      )}
    </div>
  );
}

/** Allow / ask a person / not allowed for one tool, through the agent's access grants. */
function PermissionControl({ tool, slug }: { tool: MapTool; slug: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pattern = tool.grant && tool.grant.key !== tool.key ? tool.grant.key : null;

  const set = async (to: Permission) => {
    if (to === tool.permission) return;
    const call = permissionCall(slug, tool, to);
    if (!call) return;
    setBusy(true);
    setError("");
    const r = await send(call.url, call.method, call.body);
    setBusy(false);
    if (!r.ok) return setError(errorOf(r.data, "Could not change access."));
    router.refresh();
  };

  return (
    <div className="gm-control">
      <div className="k-seg" role="group" aria-label="Access">
        {(Object.keys(PERMISSION) as Permission[]).map((p) => {
          const blocked = p === "not_granted" && pattern !== null;
          return (
            <button
              key={p}
              type="button"
              disabled={busy || blocked}
              title={blocked ? `Allowed by ${pattern}. Change that grant on Access.` : undefined}
              className={tool.permission === p ? "active" : ""}
              aria-pressed={tool.permission === p}
              onClick={() => set(p)}
            >
              {PERMISSION[p].short}
            </button>
          );
        })}
      </div>
      {pattern && <span className="gm-sub">Through {pattern}</span>}
      {error && (
        <span className="k-act-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

// --- a line, selected: what can guard it ------------------------------------------

/** The checks the workspace has and the judge chain, read by the page (GET /api/detectors, /api/judgment/posture). */
export type Catalog = {
  detectors: { key: string; label: string; source: string; surfaces: string[]; available: boolean; finds?: string }[];
  tiers: { tier: string; enabled: boolean; sends_data: boolean; blocked_reason: string }[];
  bands: Record<string, [number, number] | null>;
};

const TIER: Record<string, { name: string; note: string }> = {
  jev: { name: "Jev", note: "hosted judge model" },
  local_llm: { name: "Your LLM", note: "self-hosted, nothing leaves" },
  llm: { name: "Hosted LLM", note: "e.g. OpenAI, Anthropic" },
};
/** The order judges are asked in, for the open-ended questions these checks ask. */
const CHAIN = ["jev", "local_llm", "llm"];

/** Names the catalogue leaves blank. */
const MODULE_NAME: Record<string, string> = {
  "custom.validators": "Your validator rules",
  "injection.judgment": "Prompt injection (judge)",
  "validator.prompt_injection_llm": "Prompt injection (validator judge)",
};
const moduleName = (d: { key: string; label: string }) => MODULE_NAME[d.key] || d.label || detectorName(d.key);
/** What kind of check each source is, in a word. */
const KIND: Record<string, string> = { builtin: "Regex", open_source: "ML", yours: "Custom", llm_judge: "LLM" };

/**
 * The checks on a line: their names, and "+ Add check" to pick more from the library.
 * A check runs for the whole agent, on every line it can read.
 */
function Checks({ items, stage, slug }: { items: Catalog["detectors"]; stage: Stage; slug: string }) {
  const router = useRouter();
  const [adding, setAdding] = useState(false);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const on = items.filter((d) => stage.detectors.includes(d.key));
  const rest = items.filter((d) => !stage.detectors.includes(d.key));
  const shown = rest.filter((d) => `${moduleName(d)} ${KIND[d.source] ?? ""}`.toLowerCase().includes(q.trim().toLowerCase()));

  const set = async (key: string, enabled: boolean) => {
    setBusy(key);
    setError("");
    const r = await send(`/api/features/checks/${encodeURIComponent(key)}`, "POST", { enabled, agent: slug, reason: "Set from the map" });
    setBusy(null);
    if (!r.ok) return setError(errorOf(r.data, "Could not change this check."));
    setAdding(false);
    router.refresh();
  };

  return (
    <div className="gm-checks">
      {on.length ? (
        <ul>
          {on.map((d) => (
            <li key={d.key}>
              <span className="gm-check-name">{moduleName(d)}</span>
              <span className="gm-check-kind">{KIND[d.source] ?? ""}</span>
              <button type="button" className="gm-check-remove" disabled={busy === d.key} onClick={() => set(d.key, false)} aria-label={`Remove ${moduleName(d)}`} title="Remove">
                <X size={12} aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="gm-sub">No checks on this line yet.</p>
      )}
      <div className="gm-checks-add">
        <button type="button" className="gm-add" onClick={() => setAdding((v) => !v)}>
          <Plus size={13} aria-hidden /> Add check
        </button>
        {adding ? (
          <div className="at-lib" role="dialog" aria-label="Add a check">
            <label className="at-lib-search">
              <Search size={13} aria-hidden />
              <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search checks" />
            </label>
            {shown.length ? (
              <ul>
                {shown.map((d) => (
                  <li key={d.key}>
                    {d.available ? (
                      <button type="button" disabled={busy === d.key} onClick={() => set(d.key, true)}>
                        <span>
                          <strong>{moduleName(d)}</strong>
                        </span>
                        <span className="at-lib-n">{KIND[d.source] ?? ""}</span>
                      </button>
                    ) : (
                      <Link href="/app/policies?tab=checks" className="gm-lib-install">
                        <span>
                          <strong>{moduleName(d)}</strong>
                        </span>
                        <span className="at-lib-n">Install</span>
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="gm-sub">{rest.length ? "Nothing matches." : "Every check for this line is on."}</p>
            )}
          </div>
        ) : null}
      </div>
      {error && <span className="k-act-error" role="alert">{error}</span>}
    </div>
  );
}

/** The checks that feed one content rule, as chips; "+" adds another that finds the same thing. */
function RuleChecks({ rule, stage, catalog, slug }: { rule: MapRule; stage: Stage; catalog: Catalog["detectors"]; slug: string }) {
  const router = useRouter();
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fit = catalog.filter((d) => feeds(d, rule) && d.surfaces.some((x) => stage.surfaces.includes(x)));
  const on = fit.filter((d) => stage.detectors.includes(d.key));
  const rest = fit.filter((d) => !stage.detectors.includes(d.key));

  const set = async (key: string, enabled: boolean) => {
    setBusy(true);
    setError("");
    const r = await send(`/api/features/checks/${encodeURIComponent(key)}`, "POST", { enabled, agent: slug, reason: "Set from the map" });
    setBusy(false);
    if (!r.ok) return setError(errorOf(r.data, "Could not change this check."));
    setAdding(false);
    router.refresh();
  };

  return (
    <div className="gm-rule-checks">
      <span className="gm-rule-label">Checked by</span>
      {on.length ? (
        on.map((d) => (
          <span key={d.key} className={`gm-chip gm-chip-${d.source}`} title={`${moduleName(d)}: on for this agent, on every line it reads`}>
            <b>{KIND[d.source] ?? ""}</b> {moduleName(d)}
            <button type="button" disabled={busy} onClick={() => set(d.key, false)} aria-label={`Turn off ${moduleName(d)}`}>
              <X size={11} aria-hidden />
            </button>
          </span>
        ))
      ) : (
        <span className="gm-chip gm-chip-none">No check on: this rule can&apos;t fire</span>
      )}
      {rest.length ? (
        <span className="gm-rule-add">
          <button type="button" className="gm-chip gm-chip-add" onClick={() => setAdding((v) => !v)} aria-label="Add a check to this rule">
            <Plus size={11} aria-hidden /> add
          </button>
          {adding ? (
            <div className="at-lib" role="dialog" aria-label="Add a check">
              <ul>
                {rest.map((d) => (
                  <li key={d.key}>
                    {d.available ? (
                      <button type="button" disabled={busy} onClick={() => set(d.key, true)}>
                        <span>
                          <strong>{moduleName(d)}</strong>
                        </span>
                        <span className="at-lib-n">{KIND[d.source] ?? ""}</span>
                      </button>
                    ) : (
                      <Link href="/app/policies?tab=checks" className="gm-lib-install">
                        <span>
                          <strong>{moduleName(d)}</strong>
                        </span>
                        <span className="at-lib-n">Install</span>
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </span>
      ) : null}
      {error && <span className="k-act-error" role="alert">{error}</span>}
    </div>
  );
}

/** Low / Medium / High: how sure a check must be before the rule acts, for this agent. */
function StrictnessControl({ rule, slug }: { rule: MapRule; slug: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const current = strictnessOf(rule.minScore);
  if (!rule.policy) return null;
  const set = async (score: number, key: string) => {
    if (key === current) return;
    setBusy(true);
    setError("");
    const r = await send(`/api/policies/${encodeURIComponent(rule.policy!)}/rules/${encodeURIComponent(rule.id)}/scope`, "POST", { agents: [slug], min_score: score });
    setBusy(false);
    if (!r.ok) return setError(errorOf(r.data, "Could not change how strict this rule is."));
    router.refresh();
  };
  return (
    <div className="gm-strict">
      <span className="gm-rule-label">Strictness</span>
      <div className="k-seg" role="group" aria-label="How strict this rule is">
        {STRICTNESS.map((o) => (
          <button key={o.key} type="button" title={o.title} disabled={busy} className={current === o.key ? "active" : ""} aria-pressed={current === o.key} onClick={() => set(o.score, o.key)}>
            {o.label}
          </button>
        ))}
      </div>
      {error && <span className="k-act-error" role="alert">{error}</span>}
    </div>
  );
}

/** One rule: its name, what feeds it (checks, or what it looks at), and what it does. */
function RuleRow({ rule, stage, catalog, slug }: { rule: MapRule; stage: Stage; catalog: Catalog["detectors"]; slug: string }) {
  const watching = rule.mode === "observe" && rule.enabled !== false && rule.effect !== "allow";
  return (
    <li>
      <div className="gm-rule-top">
        <Link href={`/app/policies/rules/${encodeURIComponent(rule.id)}?tab=tune&agent=${encodeURIComponent(slug)}`} className="gm-rule-name">
          {ruleTitle(rule.id, rule.description)}
        </Link>
        {watching ? (
          <span className="gm-rule-tag" title="Its pack is in watch mode: it records what it would do and stops nothing">
            watching only
          </span>
        ) : null}
      </div>
      {rule.kind === "content" ? (
        <>
          <RuleChecks rule={rule} stage={stage} catalog={catalog} slug={slug} />
          <StrictnessControl rule={rule} slug={slug} />
        </>
      ) : rule.about ? (
        <div className="gm-rule-checks">
          <span className="gm-rule-label">Looks at</span>
          <span className="gm-rule-about">{rule.about}</span>
        </div>
      ) : null}
      <div className="gm-strict">
        <span className="gm-rule-label">Action</span>
        <RuleControl rule={rule} slug={slug} />
      </div>
    </li>
  );
}

function StagePanel({ stage, map, catalog, back }: { stage: Stage; map: AgentMap; catalog?: Catalog; back: ReactNode }) {
  const slug = map.agent.slug;
  const here = (catalog?.detectors || []).filter((d) => d.surfaces.some((s) => stage.surfaces.includes(s)));
  const judges = here.filter((d) => d.source === "llm_judge");
  // Checks switched on here that feed none of the rules here: they find things and nothing happens.
  const unused = here.filter((d) => stage.detectors.includes(d.key) && !stage.rules.some((r) => feeds(d, r)));
  const tiers = Object.fromEntries((catalog?.tiers || []).map((t) => [t.tier, t]));
  const anyJudge = CHAIN.some((t) => tiers[t]?.enabled);
  const rail = RAIL[stage.key];

  return (
    <div className="gm-panel gm-stage-panel">
      {back}
      <div className="gm-rail-head">
        <strong className="gm-guide-title">{rail?.name ?? stage.title}</strong>
        {rail && <p className="gm-rail-what">{rail.what}</p>}
      </div>

      <section className="gm-det">
        <h3>Rules</h3>
        {stage.rules.length ? (
          <ul className="gm-rule-rows">
            {sortRules(stage.rules).map((r) => (
              <RuleRow key={r.id} rule={r} stage={stage} catalog={here} slug={slug} />
            ))}
          </ul>
        ) : (
          <p className="gm-sub">No rules on this line yet.</p>
        )}
        <Link className="gm-add" href={`/app/policies/new?agent=${encodeURIComponent(slug)}`}>
          <Plus size={13} aria-hidden /> Add rule
        </Link>
        {unused.length ? (
          <p className="gm-unused">
            On but no rule uses: {unused.map((d) => moduleName(d)).join(", ")}. They only record.
          </p>
        ) : null}
      </section>

      <details className="gm-nondet">
        <summary>
          LLM judges <span className="gm-sub">{anyJudge ? "on" : "off"}</span>
        </summary>
        <ol className="gm-chain">
          {CHAIN.map((t, i) => {
            const st = tiers[t];
            return (
              <li key={t} className={st?.enabled ? "on" : ""}>
                <span className="gm-chain-step">{i + 1}</span>
                <span className="gm-chain-body">
                  <b>{TIER[t].name}</b>
                  <span className="gm-sub">{st?.enabled ? TIER[t].note : "off"}</span>
                </span>
              </li>
            );
          })}
        </ol>
        {anyJudge && judges.length ? <Checks items={judges} stage={stage} slug={slug} /> : null}
        <Link className="gm-link-strong" href="/app/policies?tab=checks">
          Set up the judges →
        </Link>
      </details>
    </div>
  );
}

// --- guide (nothing selected) -----------------------------------------------------

function Guide({ project }: { project: string }) {
  return (
    <div className="gm-panel gm-guide">
      <AttackTests project={project} />

      <section className="gm-more-agents">
        <h4>Add more agents</h4>
        <p>
          Run <code>agentfox init</code> in the repository where the agent lives.
        </p>
        <details className="gm-help">
          <summary>Can&apos;t see your agent?</summary>
          <ol>
            <li>init reads Python code: LangChain&apos;s <code>create_agent</code>, the OpenAI Agents SDK, or a plain tool-calling loop.</li>
            <li>When it finishes, it lists what it recognised and what it may have missed.</li>
            <li>Already running elsewhere? Route its calls through AgentFox and it shows up the first time it runs.</li>
          </ol>
        </details>
      </section>

      <details className="gm-help gm-howto">
        <summary>How to read this map</summary>
        <ul>
          <li>
            <b>User</b> sits outside. Everything inside the box is yours: your agents and what they reach.
          </li>
          <li>
            An <b>agent</b> is the loop that decides what to do next. Guardrails don&apos;t sit on it; they sit on what goes in and
            out of it.
          </li>
          <li>
            <b>Rails</b> are the labelled pills on the lines. <Mark size={13} /> means guardrails are set there; <b>+</b> means
            none yet. Click one to set it up.
          </li>
        </ul>
      </details>
    </div>
  );
}

/** Rules that stop traffic first; content rules before the others. */
function sortRules(rules: MapRule[]): MapRule[] {
  const kind = (r: MapRule) => (r.kind === "content" ? 0 : r.kind === "action" ? 1 : 2);
  return [...rules].sort((a, b) => counts([b]).enforcing - counts([a]).enforcing || kind(a) - kind(b) || b.hits - a.hits);
}

function RuleList({ rules, slug }: { rules: MapRule[]; slug: string }) {
  if (!rules.length) return <p className="gm-sub">No policies on this line yet.</p>;
  const sorted = [...rules].sort((a, b) => counts([b]).enforcing - counts([a]).enforcing || b.hits - a.hits);
  return (
    <ul className="gm-rules gm-rules-clean">
      {sorted.map((r) => (
        <li key={r.id}>
          <Link href={`/app/policies/rules/${encodeURIComponent(r.id)}?tab=tune&agent=${encodeURIComponent(slug)}`} className="gm-rule-name" title={r.own ? "Set for this agent" : "From the workspace"}>
            {ruleTitle(r.id, r.description)}
          </Link>
          <RuleControl rule={r} slug={slug} />
        </li>
      ))}
    </ul>
  );
}

function StatLine({ days, s, noun }: { days: number; s: Stats; noun: string }) {
  return (
    <p className="k-muted">
      Last {days} days: {s.total || 0} {noun} · {s.blocked || 0} blocked · {s.held || 0} held
      {s.masked ? ` · ${s.masked} masked` : ""}
    </p>
  );
}

function Panel({
  map,
  selected,
  groups,
  onSelect,
  project,
  catalog,
  toolList,
}: {
  map: AgentMap;
  selected: Selected;
  groups: ToolGroup[];
  onSelect: (s: Selected) => void;
  project: string;
  catalog?: Catalog;
  toolList: ReactNode;
}) {
  const slug = map.agent.slug;
  // Figma's rule: with nothing selected, the inspector is about the whole file.
  const back = (
    <button type="button" className="gm-back" onClick={() => onSelect(null)}>
      ← {map.agent.name || slug}
    </button>
  );
  if (selected?.kind === "tools")
    return (
      <div className="gm-panel gm-panel-list">
        {back}
        {toolList}
      </div>
    );
  if (selected?.kind === "stage") {
    const s = map.stages.find((x) => x.key === selected.key);
    if (s) return <StagePanel stage={s} map={map} catalog={catalog} back={back} />;
  }
  if (selected?.kind === "group") {
    const g = groups.find((x) => x.key === selected.key);
    if (g) {
      const s = groupSummary(g.tools);
      return (
        <div className="gm-panel">
          {back}
          <strong>{g.label}</strong>
          <p className="k-muted">
            {plural(g.tools.length, "tool")} · {s.allowed} allowed · {s.ask} ask · {s.denied} not allowed
          </p>
          <ul className="gm-tool-list">
            {g.tools.map((t) => (
              <li key={t.key}>
                <ToolRow tool={t} active={false} onClick={() => onSelect({ kind: "tool", key: t.key })} />
              </li>
            ))}
          </ul>
        </div>
      );
    }
  }
  const tl = selected?.kind === "tool" ? map.tools.find((t) => t.key === selected.key) : null;
  if (!tl) return <Guide project={project} />;
  const limits = Object.entries(tl.limits || {});
  return (
    <div className="gm-panel">
      {back}
      <strong className="k-mono gm-break">{tl.key}</strong>
      <div className="k-pills" style={{ gap: 6 }}>
        <Pill tone="outline">{IMPACT[tl.impact || ""] || "Risk not set"}</Pill>
        {tl.sources?.length ? <span className="k-muted">{sourceLabel(tl)}</span> : null}
      </div>
      <StatLine days={map.window_days} s={tl.stats} noun="calls" />
      <h4>Access</h4>
      <PermissionControl tool={tl} slug={slug} />
      <h4>Rules for this tool</h4>
      <RuleList rules={tl.rules} slug={slug} />
      {tl.ladders.length > 0 && (
        <>
          <h4>Approval limits</h4>
          <ul className="gm-rules">
            {tl.ladders.map((l) => (
              <li key={l.key}>
                {l.name} <ModePill mode={l.mode} />
              </li>
            ))}
          </ul>
        </>
      )}
      {limits.length > 0 && (
        <>
          <h4>Limits</h4>
          <ul className="gm-rules">
            {limits.map(([arg, spec]) => (
              <li key={arg} className="k-mono">
                {arg}: {JSON.stringify(spec)}
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="k-muted">Every call also passes the Tool calls step.</p>
      <Link className="k-btn" href={`/app/projects/${encodeURIComponent(slug)}?view=access`}>
        Limits and access
      </Link>
    </div>
  );
}

// --- tool list ---------------------------------------------------------------------

/** `mcp__github__create_issue` reads as `github/create_issue`. */
function shortKey(key: string): string {
  return key.replace(/^mcp__/, "").replace(/__/g, "/");
}

function ToolRow({ tool, active, onClick }: { tool: MapTool; active: boolean; onClick: () => void }) {
  const t = toolTone(tool);
  return (
    <button type="button" className={`gm-row${active ? " active" : ""}`} onClick={onClick} title={`${tool.key} · ${PERMISSION[tool.permission].label} · ${TONE_LABEL[t]}`}>
      <i className={`gm-swatch gm-${t}`} aria-hidden />
      <span className="k-mono gm-ellipsis">{shortKey(tool.key)}</span>
      {tool.permission !== "allowed" && <span className={`gm-perm gm-perm-${PERMISSION[tool.permission].tone}`}>{tool.permission === "ask" ? "Ask" : "Not allowed"}</span>}
    </button>
  );
}

function ToolList({
  total,
  groups,
  query,
  setQuery,
  by,
  setBy,
  filter,
  setFilter,
  selected,
  onSelect,
}: {
  total: number;
  groups: ToolGroup[];
  query: string;
  setQuery: (q: string) => void;
  by: GroupBy;
  setBy: (b: GroupBy) => void;
  filter: ToolFilter;
  setFilter: (f: ToolFilter) => void;
  selected: Selected;
  onSelect: (s: Selected) => void;
}) {
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const shown = groups.reduce((n, g) => n + g.tools.length, 0);
  return (
    <aside className="gm-list" aria-label="Tools">
      <div className="gm-list-head">
        <input className="k-input" type="search" placeholder="Search tools" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search tools" />
        <div className="gm-list-filters">
          <select className="k-select k-select-sm" value={by} onChange={(e) => setBy(e.target.value as GroupBy)} aria-label="Group by">
            {GROUP_BY.map((g) => (
              <option key={g.key} value={g.key}>
                By {g.label.toLowerCase()}
              </option>
            ))}
          </select>
          <select className="k-select k-select-sm" value={filter} onChange={(e) => setFilter(e.target.value as ToolFilter)} aria-label="Show">
            {TOOL_FILTERS.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
              </option>
            ))}
          </select>
        </div>
        {shown !== total && <span className="gm-sub">{shown} of {total} shown</span>}
      </div>
      <div className="gm-list-body">
        {!groups.length && <p className="k-muted">No tools match.</p>}
        {groups.map((g) => {
          const isClosed = closed[g.key] ?? false;
          const s = groupSummary(g.tools);
          return (
            <section key={g.key} className="gm-list-group">
              <div className={`gm-group-head${selected?.kind === "group" && selected.key === g.key ? " active" : ""}`}>
                <button type="button" className="gm-caret" aria-expanded={!isClosed} aria-label={isClosed ? `Show ${g.label}` : `Hide ${g.label}`} onClick={() => setClosed({ ...closed, [g.key]: !isClosed })}>
                  {isClosed ? "▸" : "▾"}
                </button>
                <button type="button" className="gm-group-name" onClick={() => onSelect({ kind: "group", key: g.key })}>
                  <i className={`gm-swatch gm-${s.tone}`} aria-hidden />
                  <span className="gm-ellipsis">{g.label}</span>
                  <span className="k-muted">{g.tools.length}</span>
                </button>
              </div>
              {!isClosed && (
                <ul className="gm-tool-list">
                  {g.tools.map((t) => (
                    <li key={t.key}>
                      <ToolRow tool={t} active={selected?.kind === "tool" && selected.key === t.key} onClick={() => onSelect({ kind: "tool", key: t.key })} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </div>
    </aside>
  );
}

// --- the map -----------------------------------------------------------------------

function Legend() {
  return (
    <div className="gm-legend" aria-label="Legend">
      {NODE_KINDS.map((k) => (
        <span key={k.key} className={`gm-legend-kind gm-lk-${k.key}`}>
          <span className="gm-kind-icon" aria-hidden>
            <k.icon size={12} strokeWidth={2} />
          </span>
          {k.label}
        </span>
      ))}
      <span className="gm-legend-sep" aria-hidden />
      <span className="gm-legend-kind">
        <Mark size={16} /> Rail with guardrails
      </span>
      <span className="gm-legend-kind">
        <span className="gm-legend-plus" aria-hidden>+</span> Rail, none yet
      </span>
      <span className="gm-legend-hint">Rails are where guardrails apply: click one, or a tool</span>
    </div>
  );
}

/**
 * One project's guardrails, drawn where they act. The user outside; inside the
 * project's box, each agent with its LLM, tools and documents; rails on the lines
 * between them. Clicking a rail, a tool or an agent makes that agent the one the
 * panel is about; with nothing selected the panel is that agent's set-up guide.
 */
export function GuardrailMap({
  maps,
  focus,
  project,
  catalog,
}: {
  maps: AgentMap[];
  focus: string;
  project: string;
  catalog?: Catalog;
}) {
  const [active, setActive] = useState(focus);
  const [selected, setSelected] = useState<Selected>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [by, setBy] = useState<GroupBy>("impact");
  const [filter, setFilter] = useState<ToolFilter>("all");

  const map = maps.find((m) => m.agent.slug === active) ?? maps[0];
  const visible = useMemo(() => filterTools(map.tools, query, filter), [map.tools, query, filter]);
  const groups = useMemo(() => groupTools(visible, by), [visible, by]);

  const choose = (slug: string, next: Selected) => {
    setActive(slug);
    setSelected(next);
  };
  const laid = useMemo(() => {
    const drawnFor = (m: AgentMap) => {
      const mine = m.agent.slug === active;
      const list = mine ? visible : m.tools;
      const sel = mine && selected?.kind === "tool" ? selected.key : null;
      const tools = boxTools(list, expanded.has(m.agent.slug), sel);
      return { tools, hidden: list.length - tools.length };
    };
    return layout(maps, drawnFor, active, selected, (slug, key) => choose(slug, { kind: "stage", key }), project);
  }, [maps, visible, expanded, active, selected, project]);
  // The rail under the pointer (or its pill) lights up.
  const edges = useMemo(
    () =>
      laid.edges.map((e) =>
        e.type === "guard"
          ? { ...e, data: { ...(e.data as GuardData), hovered: hovered === e.id, onHover: (on: boolean) => setHovered(on ? e.id : null) } }
          : e,
      ),
    [laid.edges, hovered],
  );

  const toolList = (
    <ToolList
      total={map.tools.length}
      groups={groups}
      query={query}
      setQuery={setQuery}
      by={by}
      setBy={setBy}
      filter={filter}
      setFilter={setFilter}
      selected={selected}
      onSelect={setSelected}
    />
  );
  const agentSwitch =
    maps.length > 1 ? (
      <div className="gm-agents" role="tablist" aria-label="Agents in this project">
        {maps.map((m) => (
          <button
            key={m.agent.slug}
            type="button"
            role="tab"
            aria-selected={m.agent.slug === active}
            className={m.agent.slug === active ? "on" : undefined}
            onClick={() => choose(m.agent.slug, null)}
          >
            <Bot size={12} aria-hidden /> {m.agent.name}
          </button>
        ))}
      </div>
    ) : null;

  return (
    <div className="gm">
      <div className="gm-canvas">
        <div className="gm-bar">
          <Legend />
        </div>
        <div className="gm-flow">
          <ReactFlow
            // Re-fit when what is drawn changes shape, not on every selection.
            // With several agents, open on the active one; picking another moves there.
            key={`${maps.length}|${[...expanded].join(",")}|${visible.length}|${maps.length > 1 ? active : ""}`}
            nodes={laid.nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            edgeTypes={EDGE_TYPES}
            onEdgeMouseEnter={(_, edge) => edge.type === "guard" && setHovered(edge.id)}
            onEdgeMouseLeave={() => setHovered(null)}
            onEdgeClick={(_, edge) => {
              if (edge.type !== "guard") return;
              const [slug, what] = edge.id.split("|");
              const key = (edge.data as GuardData | undefined)?.stage?.key;
              if (key && what?.startsWith("edge:")) choose(slug, { kind: "stage", key });
            }}
            fitView
            fitViewOptions={
              maps.length > 1
                ? { padding: 0.25, maxZoom: 1, nodes: laid.nodes.filter((n) => (n.id.startsWith(`${active}|`) || (n.id === "user" && laid.edges.some((e) => e.source === "user" && e.target === `${active}|agent`))) && !n.parentId).map((n) => ({ id: n.id })) }
                : { padding: 0.12, maxZoom: 1 }
            }
            minZoom={0.15}
            maxZoom={1.5}
            nodesDraggable={false}
            nodesConnectable={false}
            proOptions={{ hideAttribution: true }}
            onNodeClick={(_, node) => {
              const [slug, what = ""] = node.id.split("|");
              if (what.startsWith("tool:")) choose(slug, { kind: "tool", key: what.slice(5) });
              else if (what === "box") choose(slug, { kind: "tools", key: "" });
              else if (what === "more") setExpanded(new Set([...expanded, slug]));
              else if (what === "agent") choose(slug, null);
              else setSelected(null);
            }}
            onPaneClick={() => setSelected(null)}
          >
            <Background gap={20} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      </div>
      <div className="gm-side">
        {agentSwitch}
        <Panel map={map} selected={selected} groups={groups} onSelect={setSelected} project={project} catalog={catalog} toolList={toolList} />
      </div>
    </div>
  );
}
