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
import { Bot, Cpu, FileText, User, Wrench, type LucideIcon } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { ActionPill, ModePill, Pill } from "@/components/kit";
import {
  GROUP_BY,
  PERMISSION,
  RULE_SETTINGS,
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
      <Handle type="source" position={Position.Right} id="out" style={{ top: "30%" }} />
      <Handle type="target" position={Position.Right} id="back" style={{ top: "72%" }} />
      <User size={14} aria-hidden />
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
function AgentNode({ data }: NodeProps<Node<{ name: string; framework?: string | null; active: boolean; handsOffTo?: number }>>) {
  return (
    <div className={`gm-node gm-agent${data.active ? " gm-agent-active" : ""}`}>
      <Handle type="target" position={Position.Left} id="in" style={{ top: "32%" }} />
      <Handle type="source" position={Position.Left} id="reply" style={{ top: "70%" }} />
      <Handle type="source" position={Position.Top} id="llm" />
      <Handle type="source" position={Position.Bottom} id="calls" style={{ left: "40%" }} />
      <Handle type="target" position={Position.Bottom} id="results" style={{ left: "62%" }} />
      <Handle type="target" position={Position.Top} id="context" style={{ left: "6%" }} />
      <Handle type="source" position={Position.Top} id="handoff" style={{ left: "88%" }} />
      <Handle type="target" position={Position.Top} id="handin" style={{ left: "12%" }} />
      <Kind icon={Bot} label="Agent" />
      <strong className="gm-ellipsis">{data.name}</strong>
      <span className="gm-sub">{data.framework ? `${data.framework} · ` : ""}decides what to do next</span>
      {data.handsOffTo ? (
        <span className="gm-handoff-note">
          hands off to {plural(data.handsOffTo, "agent")}
          {data.active ? "" : " · click to show"}
        </span>
      ) : null}
    </div>
  );
}

/** The model the agent thinks with. */
function LlmNode({ data }: NodeProps<Node<{ models: string[] }>>) {
  return (
    <div className="gm-node gm-llm">
      <Handle type="target" position={Position.Bottom} />
      <Kind icon={Cpu} label={data.models.length > 1 ? `${data.models.length} LLMs` : "LLM"} />
      {data.models.length ? (
        data.models.map((m) => (
          <strong key={m} className="gm-ellipsis k-mono">
            {m}
          </strong>
        ))
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
      <Handle type="source" position={Position.Bottom} style={{ left: "80%" }} />
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
export const RAIL: Record<string, { name: string; what: (agent: string) => string; between: [string, string] }> = {
  input: { name: "Input", what: (a) => `What users send to ${a}, checked before ${a} sees it.`, between: ["User", "Agent"] },
  output: { name: "Output", what: (a) => `What ${a} sends back, checked before the user sees it.`, between: ["Agent", "User"] },
  completion: { name: "LLM calls", what: (a) => `What ${a} sends to its LLM and what the LLM answers.`, between: ["Agent", "LLM"] },
  tool_call: { name: "Tool calls", what: (a) => `Every call ${a} makes to a tool: which tool, with what arguments.`, between: ["Agent", "Tools"] },
  tool_result: { name: "Tool results", what: (a) => `What tools return to ${a}, before it reads it.`, between: ["Tools", "Agent"] },
  context: {
    name: "Retrieval & memory",
    what: (a) => `Documents, memory and other agents' messages, before ${a} reads them.`,
    between: ["Documents & memory", "Agent"],
  },
};

type GuardData = {
  /** Where along the line the pill sits (0–1); two rails side by side are set apart. */
  at?: number;
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
            style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)` }}
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
/** The user sits well outside the box, so the Input and Output rails are outside it too. */
const USER_X = -420;
const SYS_X = 230;
const AGENT_X = 600;
const AGENT_W = 180;
const LLM_W = 180;
/** Rows inside one agent's band, far apart so every line is long enough to read and
 * click: its LLM, then the agent, then tools and documents. */
const LLM_Y = 60;
const AGENT_Y = 280;
const BELOW_Y = 520;

/** Node and edge ids carry the agent: `<slug>|<what>`. */
const nid = (slug: string, what: string) => `${slug}|${what}`;

/**
 * The agents users talk to directly. One agent: it. Several: the ones that hand work
 * to two or more others (a triage agent), or every one if none does.
 */
function entryAgents(maps: AgentMap[]): string[] {
  if (maps.length <= 1) return maps.map((m) => m.agent.slug);
  const inProject = new Set(maps.map((m) => m.agent.slug));
  const out = (m: AgentMap) => m.subagents.filter((s) => inProject.has(s.slug)).length;
  const most = Math.max(...maps.map(out));
  // The agent that hands work to the most others is where users come in (a triage
  // agent). With no hand-offs at all, every agent talks to users.
  return most > 0 ? maps.filter((m) => out(m) === most).map((m) => m.agent.slug) : maps.map((m) => m.agent.slug);
}

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
  const entries = new Set(entryAgents(maps));
  const isSel = (slug: string, kind: string, key: string) => slug === active && selected?.kind === kind && selected.key === key;

  // Entry agents first, so the user's lines run straight to them.
  const ordered = [...maps].sort((a, b) => Number(entries.has(b.agent.slug)) - Number(entries.has(a.agent.slug)));
  const many = maps.length > 1;
  // One agent: a single column with room to spare. Several: a grid, four to a row,
  // each agent with its LLM above and its tools (one per line) below.
  const COLS = many ? Math.min(4, maps.length) : 1;
  const COL_W = 470;
  const toolCols = many ? 1 : 2;
  let right = AGENT_X + 300;
  let bottom = 0;
  const rowHeights: number[] = [];
  const rowTop = (r: number) => 70 + rowHeights.slice(0, r).reduce((a, b) => a + b, 0);
  const placed: { slug: string; x: number; y: number }[] = [];

  ordered.forEach((map, idx) => {
    const slug = map.agent.slug;
    const col = idx % COLS;
    const row = Math.floor(idx / COLS);
    if (rowHeights[row] === undefined) rowHeights[row] = 0;
    const y = rowTop(row);
    const ax = AGENT_X + col * COL_W;
    const stage = (key: string) => map.stages.find((s) => s.key === key);
    const rail = (key: string, source: string, target: string, extra: Partial<Edge> = {}) =>
      edges.push({
        id: nid(slug, `edge:${key}`),
        source,
        target,
        type: "guard",
        markerEnd: arrow,
        data: { stage: stage(key), title: RAIL[key]?.name ?? key, selected: isSel(slug, "stage", key), onPick: () => pick(slug, key) },
        ...extra,
      });
    const agentId = nid(slug, "agent");
    const handsOffTo = map.subagents.filter((s) => s.slug !== slug && maps.some((m) => m.agent.slug === s.slug)).length;
    nodes.push({ id: agentId, type: "agent", position: { x: ax, y: y + AGENT_Y }, data: { name: map.agent.name, framework: map.agent.framework, active: slug === active && many, handsOffTo } });
    placed.push({ slug, x: ax, y: y + AGENT_Y });

    // The LLM, straight above it.
    nodes.push({ id: nid(slug, "llm"), type: "llm", position: { x: ax + (AGENT_W - LLM_W) / 2, y: y + LLM_Y }, data: { models: map.agent.models || [] } });
    rail("completion", agentId, nid(slug, "llm"), { sourceHandle: "llm", style: { stroke: "var(--af-link)", strokeDasharray: "5 4" } });

    // Its tools, in a box straight below it.
    const { tools, hidden } = drawnFor(map);
    let boxH = 0;
    if (tools.length || hidden) {
      const cells = tools.length + (hidden ? 1 : 0);
      const cols = Math.min(toolCols, Math.max(1, cells));
      const rowsN = Math.ceil(cells / cols);
      const w = PAD * 2 + cols * TOOL_W + (cols - 1) * GAP;
      boxH = HEAD + rowsN * TOOL_H + (rowsN - 1) * GAP + PAD;
      const boxId = nid(slug, "box");
      const bx = many ? ax + 20 : Math.max(ax + AGENT_W / 2 - w / 2, SYS_X + 260);
      right = Math.max(right, bx + w + 40);
      // Its top handles sit straight below the agent's, so both lines run straight down.
      const callsAt = ax + AGENT_W * 0.4 - bx;
      const resultsAt = ax + AGENT_W * 0.6 - bx;
      nodes.push({ id: boxId, type: "box", position: { x: bx, y: y + BELOW_Y }, data: { title: plural(map.tools.length, "tool"), w, h: boxH, selected: slug === active && selected?.kind === "tools", callsAt, resultsAt } });
      const at = (i: number) => ({ x: PAD + (i % cols) * (TOOL_W + GAP), y: HEAD + Math.floor(i / cols) * (TOOL_H + GAP) });
      tools.forEach((tl, i) =>
        nodes.push({ id: nid(slug, `tool:${tl.key}`), type: "tool", parentId: boxId, extent: "parent", position: at(i), data: { tool: tl, selected: isSel(slug, "tool", tl.key) } }),
      );
      if (hidden) nodes.push({ id: nid(slug, "more"), type: "more", parentId: boxId, extent: "parent", position: at(tools.length), data: { label: `+${hidden} more` } });
      rail("tool_call", agentId, boxId, { sourceHandle: "calls", targetHandle: "in" });
      rail("tool_result", boxId, agentId, { sourceHandle: "out", targetHandle: "results", style: { strokeDasharray: "4 4" } });
      // The two pills sit at different heights so they never overlap.
      edges[edges.length - 2].data = { ...(edges[edges.length - 2].data as GuardData), at: 0.35 };
      edges[edges.length - 1].data = { ...(edges[edges.length - 1].data as GuardData), at: 0.35 };
    }

    // Documents & memory: up to the left of the agent, level with its LLM, one
    // straight line down into the agent's top-left.
    if (stage("context")) {
      nodes.push({ id: nid(slug, "docs"), type: "docs", position: { x: Math.max(ax - 230, SYS_X + 24), y: y + LLM_Y + 36 }, data: {} });
      rail("context", nid(slug, "docs"), agentId, { targetHandle: "context", style: { strokeDasharray: "4 4" } });
    }

    // Users talk to the entry agents: Input in, Output back.
    if (entries.has(slug)) {
      rail("input", "user", agentId, { sourceHandle: "out", targetHandle: "in" });
      rail("output", agentId, "user", { sourceHandle: "reply", targetHandle: "back" });
    }

    const height = BELOW_Y + boxH + 60;
    rowHeights[row] = Math.max(rowHeights[row], height);
    right = Math.max(right, ax + COL_W - 60);
    bottom = Math.max(bottom, rowTop(row) + rowHeights[row]);
  });
  const rows = placed.map((p) => ({ slug: p.slug, top: p.y - AGENT_Y, height: 0 }));
  const y = bottom;

  // Hand-offs between agents in this project: dashed, agent to agent.
  const inProject = new Set(maps.map((m) => m.agent.slug));
  // Only the active agent's hand-offs are drawn: every agent's at once is a tangle.
  for (const map of maps.filter((m) => m.agent.slug === active)) {
    for (const s of map.subagents) {
      if (!inProject.has(s.slug) || s.slug === map.agent.slug) continue;
      edges.push({
        id: `handoff|${map.agent.slug}|${s.slug}`,
        source: nid(map.agent.slug, "agent"),
        sourceHandle: "handoff",
        target: nid(s.slug, "agent"),
        targetHandle: "handin",
        type: "straight",
        style: { stroke: "var(--af-brand)", strokeDasharray: "6 4", opacity: 0.45, strokeWidth: 1.5 },
        markerEnd: arrow,
      });
    }
  }

  // The project box first (it is drawn underneath), then the user, outside it.
  const total = y - 20;
  nodes.unshift({
    id: "system",
    type: "system",
    position: { x: SYS_X, y: 10 },
    data: { title: project, sub: maps.length > 1 ? `${maps.length} agents · everything inside is yours` : "your agent and everything it reaches" },
    style: { zIndex: -1 },
    selectable: false,
    draggable: false,
  } as Node);
  (nodes[0].data as any).w = right - SYS_X;
  (nodes[0].data as any).h = total;
  const firstEntry = rows.find((r) => entries.has(r.slug)) ?? rows[0];
  nodes.push({ id: "user", type: "user", position: { x: USER_X, y: (firstEntry?.top ?? 0) + AGENT_Y + 6 }, data: {} });
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
        {RULE_SETTINGS.map((o) => (
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
  detectors: { key: string; label: string; source: string; surfaces: string[]; available: boolean }[];
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

/** Output is judged as meaning (semantic); everything else as an open pattern. */
function bandFor(stage: Stage, catalog?: Catalog): [number, number] {
  const kind = stage.key === "output" ? "semantic" : "pattern_open";
  return catalog?.bands[kind] || (kind === "semantic" ? [0.3, 0.7] : [0.2, 0.8]);
}

function CheckToggle({ dkey, on, available, slug }: { dkey: string; on: boolean; available: boolean; slug: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!available)
    return (
      <Link className="gm-check-install" href="/app/policies?tab=checks" title="Install it on the Checks page">
        Not installed
      </Link>
    );
  const flip = async () => {
    setBusy(true);
    setError("");
    const r = await send(`/api/features/checks/${encodeURIComponent(dkey)}`, "POST", { enabled: !on, agent: slug, reason: "Set from the map" });
    setBusy(false);
    if (!r.ok) return setError(errorOf(r.data, "Could not change this check."));
    router.refresh();
  };
  return (
    <>
      <button type="button" role="switch" aria-checked={on} disabled={busy} className={`gm-switch${on ? " on" : ""}`} onClick={flip}>
        <span />
      </button>
      {error && <span className="k-act-error" role="alert">{error}</span>}
    </>
  );
}

/** Names the catalogue leaves blank. */
const MODULE_NAME: Record<string, string> = {
  "custom.validators": "Your validator rules",
  "injection.judgment": "Prompt injection (judge)",
  "validator.prompt_injection_llm": "Prompt injection (validator judge)",
};
const moduleName = (d: { key: string; label: string }) => MODULE_NAME[d.key] || d.label || detectorName(d.key);

function ModuleRow({ d, stage, slug }: { d: Catalog["detectors"][number]; stage: Stage; slug: string }) {
  return (
    <li>
      <span className="gm-module-name">
        {moduleName(d)}
        <span className="k-mono gm-sub">{d.key}</span>
      </span>
      <CheckToggle dkey={d.key} on={stage.detectors.includes(d.key)} available={d.available} slug={slug} />
    </li>
  );
}

/** Installed checks with their switch; the ones not installed folded away. */
function ModuleList({ items, stage, slug, empty }: { items: Catalog["detectors"]; stage: Stage; slug: string; empty: string }) {
  if (!items.length) return <p className="gm-sub">{empty}</p>;
  const ready = items.filter((d) => d.available);
  const rest = items.filter((d) => !d.available);
  return (
    <>
      {ready.length > 0 && (
        <ul className="gm-modules">
          {ready.map((d) => (
            <ModuleRow key={d.key} d={d} stage={stage} slug={slug} />
          ))}
        </ul>
      )}
      {rest.length > 0 && (
        <details className="gm-more-modules">
          <summary>
            {ready.length ? `${rest.length} more you can install` : `${rest.length} available to install`}
          </summary>
          <ul className="gm-modules">
            {rest.map((d) => (
              <ModuleRow key={d.key} d={d} stage={stage} slug={slug} />
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

function StagePanel({ stage, map, catalog, back }: { stage: Stage; map: AgentMap; catalog?: Catalog; back: ReactNode }) {
  const slug = map.agent.slug;
  const here = (catalog?.detectors || []).filter((d) => d.surfaces.some((s) => stage.surfaces.includes(s)));
  const by = (source: string) => here.filter((d) => d.source === source);
  const judges = by("llm_judge");
  const tiers = Object.fromEntries((catalog?.tiers || []).map((t) => [t.tier, t]));
  const anyJudge = CHAIN.some((t) => tiers[t]?.enabled);
  const [lo, hi] = bandFor(stage, catalog);
  const pct = (x: number) => `${Math.round(Math.max(0, x) * 100)}%`;

  return (
    <div className="gm-panel gm-stage-panel">
      {back}
      <div className="gm-rail-head">
        <span className="gm-guide-kicker">Rail</span>
        <strong className="gm-guide-title">{RAIL[stage.key]?.name ?? stage.title}</strong>
        {RAIL[stage.key] && (
          <>
            <span className="gm-rail-between">
              {RAIL[stage.key].between[0]} <span aria-hidden>→</span> {RAIL[stage.key].between[1]}
              <span className="gm-sub"> · {map.agent.name}</span>
            </span>
            <p className="gm-rail-what">{RAIL[stage.key].what(map.agent.name || map.agent.slug)}</p>
          </>
        )}
        <StatLine days={map.window_days} s={stage.stats} noun="checked" />
      </div>

      <section className="gm-layer">
        <header>
          <span className="gm-layer-tag det">Deterministic</span>
          <span className="gm-sub">Same input, same answer. Runs on every call, in milliseconds.</span>
        </header>

        <h4>Policies</h4>
        <p className="gm-sub">What happens when a check below finds something: block, ask a person, or only watch.</p>
        <RuleList rules={stage.rules} slug={slug} />

        <h4>Pattern checks · regex</h4>
        <ModuleList items={by("builtin")} stage={stage} slug={slug} empty="None for this step." />

        <h4>Classifier models · ML</h4>
        <ModuleList items={by("open_source")} stage={stage} slug={slug} empty="None for this step." />

        {by("yours").length > 0 && (
          <>
            <h4>Your own checks</h4>
            <ModuleList items={by("yours")} stage={stage} slug={slug} empty="" />
          </>
        )}
      </section>

      <section className="gm-layer">
        <header>
          <span className="gm-layer-tag llm">Non-deterministic · LLM fallback chain</span>
          <span className="gm-sub">An LLM reads what the patterns can&apos;t: intent, meaning, disguised attacks.</span>
        </header>

        <ol className="gm-chain">
          {CHAIN.map((t, i) => {
            const st = tiers[t];
            return (
              <li key={t} className={st?.enabled ? "on" : ""}>
                <span className="gm-chain-step">{i + 1}</span>
                <span className="gm-chain-body">
                  <b>{TIER[t].name}</b>
                  <span className="gm-sub">{st?.enabled ? TIER[t].note : st?.blocked_reason ? "off · " + shortReason(st.blocked_reason) : "off"}</span>
                </span>
              </li>
            );
          })}
        </ol>
        <p className="gm-sub">
          When a judge is switched on it runs alongside the checks above. Judges are asked in order: an answer below {pct(lo)} or
          above {pct(hi)} settles it; anything in between passes to the next judge. The highest score wins and goes through the
          same policies.
          {stage.key !== "output" ? "" : " Here the question is about meaning, so the band is wider."}
        </p>

        <h4>Judge checks here</h4>
        {anyJudge ? (
          <ModuleList items={judges} stage={stage} slug={slug} empty="No judge checks for this step." />
        ) : (
          <p className="gm-sub">
            No judge is switched on, so {judges.length ? `these ${judges.length} checks` : "judge checks"} can&apos;t run yet
            {judges.length ? `: ${[...new Set(judges.map(moduleName))].join(", ")}` : ""}.
          </p>
        )}
        <Link className="gm-link-strong" href="/app/policies?tab=checks">
          Set up the chain →
        </Link>
      </section>
    </div>
  );
}

/** The first clause of a backend reason, for a one-line status. */
function shortReason(reason: string): string {
  if (reason.includes("egress")) return "sending data out is switched off on this deployment";
  return reason.split(/[;(]/)[0].trim();
}

// --- guide (nothing selected) -----------------------------------------------------

/** The last attack-test run the panel reports, read by the page. */
export type LastTest = { name: string; at: string; run: number; blocked: number; href: string } | null;

const POINTS = ["input", "context", "tool_call", "tool_result", "output"];
const RISKY = new Set(["irreversible", "high_impact"]);

/** A place on the map counts as secured when something there enforces; watching is half-way. */
function coverage(map: AgentMap) {
  const stages = map.stages.filter((s) => POINTS.includes(s.key));
  const stageState = stages.map((s) => {
    const c = counts(s.rules);
    return c.enforcing ? "on" : c.watching || s.detectors.length ? "watch" : "off";
  });
  const toolState = map.tools.map((t) =>
    t.permission !== "allowed" || t.ladders.length || counts(t.rules).enforcing ? "on" : counts(t.rules).watching ? "watch" : "off",
  );
  const all = [...stageState, ...toolState];
  const on = all.filter((x) => x === "on").length;
  const watch = all.filter((x) => x === "watch").length;
  return { total: all.length, on, watch, pct: all.length ? Math.round((on / all.length) * 100) : 0 };
}

type Suggestion = { text: string; action: string; pick: Selected };

/** Where adding a guardrail matters most, most urgent first. */
function suggestions(map: AgentMap): Suggestion[] {
  const out: Suggestion[] = [];
  for (const t of map.tools) {
    if (RISKY.has(t.impact || "") && t.permission === "allowed" && !counts(t.rules).enforcing)
      out.push({ text: `${shortKey(t.key)} can do real damage and runs with no check.`, action: "Require approval", pick: { kind: "tool", key: t.key } });
  }
  for (const s of map.stages.filter((x) => POINTS.includes(x.key))) {
    const c = counts(s.rules);
    if (!c.enforcing && !c.watching && !s.detectors.length)
      out.push({ text: `Nothing guards ${s.title.toLowerCase()} yet.`, action: "Add guardrails", pick: { kind: "stage", key: s.key } });
    else if (!c.enforcing)
      out.push({ text: `${s.title} only watches: nothing is stopped there.`, action: "Start enforcing", pick: { kind: "stage", key: s.key } });
  }
  return out.slice(0, 4);
}

function Guide({ map, lastTest, onSelect }: { map: AgentMap; lastTest?: LastTest; onSelect: (s: Selected) => void }) {
  const c = coverage(map);
  const tips = suggestions(map);
  return (
    <div className="gm-panel gm-guide">
      <div>
        <span className="gm-guide-kicker">Set up guardrails</span>
        <strong className="gm-guide-title">{map.agent.name || map.agent.slug}</strong>
      </div>

      <section className="gm-score" aria-label="How much of this agent is secured">
        <div className="gm-score-head">
          <b>{c.pct}%</b>
          <span>secured</span>
        </div>
        <div className="gm-score-bar" aria-hidden>
          <i className="on" style={{ width: `${c.total ? (c.on / c.total) * 100 : 0}%` }} />
          <i className="watch" style={{ width: `${c.total ? (c.watch / c.total) * 100 : 0}%` }} />
        </div>
        <p className="gm-sub">
          {c.on} of {c.total} places on the map enforce a guardrail{c.watch ? ` · ${c.watch} only watch` : ""}.
        </p>
      </section>

      <section>
        <h4>Last test run</h4>
        {lastTest ? (
          <div className="gm-test">
            <span className={`gm-test-result${lastTest.blocked < lastTest.run ? " bad" : ""}`}>
              {lastTest.blocked} of {lastTest.run} attacks blocked
            </span>
            <span className="gm-sub">
              {lastTest.name} · {new Date(lastTest.at).toLocaleDateString([], { month: "short", day: "numeric" })}
            </span>
            <Link className="gm-link-strong" href={lastTest.href}>Run tests again →</Link>
          </div>
        ) : (
          <p className="gm-sub">
            No tests yet. <Link className="gm-link-strong" href="/app/test">Run the attack suite →</Link>
          </p>
        )}
      </section>

      <section>
        <h4>Suggestions</h4>
        {tips.length ? (
          <ul className="gm-tips">
            {tips.map((t) => (
              <li key={t.text}>
                <span>{t.text}</span>
                <button type="button" className="gm-link-strong" onClick={() => onSelect(t.pick)}>
                  {t.action} →
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="gm-sub">Every place on the map has a guardrail. Run the tests to check they hold.</p>
        )}
        <p className="gm-sub">Or click any line or tool on the map to see what you can add there.</p>
      </section>

      <section className="gm-howto">
        <h4>How to read this map</h4>
        <ul>
          <li>
            <b>User</b> sits outside. Everything inside the box is yours: your agents and what they reach.
          </li>
          <li>
            An <b>agent</b> is the loop that decides what to do next. Guardrails don&apos;t sit on it; they sit on what goes in and
            out of it.
          </li>
          <li>
            <b>Rails</b> are the labelled pills on the lines: Input, Output, LLM calls, Tool calls, Tool results, Retrieval &amp;
            memory. <Mark size={13} /> means guardrails are set there; <b>+</b> means none yet. Click one to set it up.
          </li>
        </ul>
      </section>

      <details className="gm-help">
        <summary>Can&apos;t see your agent here?</summary>
        <ol>
          <li>
            Run <code>agentfox init</code> in the repository where the agent lives. It reads the code, finds every agent and
            tool, and adds them here.
          </li>
          <li>Make sure the agent is built in code it can read, e.g. LangChain&apos;s <code>create_agent</code> with its tools.</li>
          <li>Already running elsewhere? Route its calls through AgentFox and it shows up the first time it runs.</li>
        </ol>
        <Link className="gm-link-strong" href="/app/onboarding">Open setup →</Link>
      </details>
    </div>
  );
}

// --- panel -----------------------------------------------------------------------

function RuleList({ rules, slug }: { rules: MapRule[]; slug: string }) {
  if (!rules.length) return <p className="k-muted">No rules here.</p>;
  const sorted = [...rules].sort((a, b) => counts([b]).enforcing - counts([a]).enforcing || b.hits - a.hits);
  return (
    <ul className="gm-rules">
      {sorted.map((r) => (
        <li key={r.id}>
          <div className="gm-rule-head">
            <Link href={`/app/policies/rules/${encodeURIComponent(r.id)}`} className="k-name">
              {ruleTitle(r.id, r.description)}
            </Link>
            <Link className="gm-link" href={`/app/policies/rules/${encodeURIComponent(r.id)}?tab=tune&agent=${encodeURIComponent(slug)}`} title="More options">
              More
            </Link>
          </div>
          <span className="k-pills" style={{ gap: 6 }}>
            {ruleSetting(r) === null && <ActionPill effect={r.effect} />}
            {r.enabled !== false && <ModePill mode={r.effect === "allow" ? "observe" : r.mode} />}
            {r.own && <Pill tone="outline">This agent</Pill>}
            {r.hits ? <span className="k-muted">{r.hits} hits</span> : null}
          </span>
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
  lastTest,
  catalog,
  toolList,
}: {
  map: AgentMap;
  selected: Selected;
  groups: ToolGroup[];
  onSelect: (s: Selected) => void;
  lastTest?: LastTest;
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
  if (!tl) return <Guide map={map} lastTest={lastTest} onSelect={onSelect} />;
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
  lastTest,
  catalog,
}: {
  maps: AgentMap[];
  focus: string;
  project: string;
  lastTest?: LastTest;
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
                ? { padding: 0.25, maxZoom: 1, nodes: laid.nodes.filter((n) => n.id.startsWith(`${active}|`) && !n.parentId).map((n) => ({ id: n.id })) }
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
        <Panel map={map} selected={selected} groups={groups} onSelect={setSelected} lastTest={lastTest} catalog={catalog} toolList={toolList} />
      </div>
    </div>
  );
}
