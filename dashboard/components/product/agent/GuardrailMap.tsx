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
  getBezierPath,
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
  DRAW_SUBAGENTS,
  GROUP_BY,
  PERMISSION,
  RULE_SETTINGS,
  TONE_LABEL,
  TOOL_FILTERS,
  counts,
  drawnSubagents,
  filterTools,
  groupSummary,
  groupTools,
  parentLabel,
  permissionCall,
  relationLabel,
  ruleChange,
  ruleSetting,
  toolTone,
  type AgentMap,
  type GroupBy,
  type MapLink,
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
// Kept deliberately quiet. Each kind of thing has one look:
//   user    one grey pill: the message leaves it, the reply comes back to it
//   agent   the largest card, rose (the brand)
//   llm     a large indigo card above the agent
//   tools   one tinted box holding a small chip per tool
//   docs    documents & memory, a small amber card
// Guardrails are not cards. Where some are set, our logo sits on the line (or on the
// tool) they guard; where none are, a faint dot. Clicking a line, its logo, or a tool
// opens what guards it in the panel beside the canvas.

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
  { key: "tool", label: "Tool", icon: Wrench },
];

/** Our mark: "guardrails are here". */
function Mark({ size = 18 }: { size?: number }) {
  return <Logo size={size} />;
}

/** Whether anything guards this step: rules that enforce or watch, or detectors. */
function guarded(s: Stage | undefined): boolean {
  if (!s) return false;
  const c = counts(s.rules);
  return Boolean(c.enforcing || c.watching || s.detectors.length);
}

/** The single user: their message leaves from the top, the reply comes back in below. */
function UserNode() {
  return (
    <div className="gm-node gm-end">
      <Handle type="source" position={Position.Right} id="out" style={{ top: "28%" }} />
      <Handle type="target" position={Position.Right} id="back" style={{ top: "74%" }} />
      <Handle type="target" position={Position.Bottom} id="parents" />
      <User size={14} aria-hidden />
      User
    </div>
  );
}

function AgentNode({ data }: NodeProps<Node<{ name: string; framework?: string | null }>>) {
  return (
    <div className="gm-node gm-agent">
      <Handle type="target" position={Position.Left} id="in" style={{ top: "28%" }} />
      <Handle type="source" position={Position.Left} id="reply" style={{ top: "74%" }} />
      <Handle type="source" position={Position.Bottom} id="calls" style={{ left: "38%" }} />
      <Handle type="target" position={Position.Bottom} id="results" style={{ left: "62%" }} />
      <Handle type="source" position={Position.Top} id="llm" />
      <Handle type="target" position={Position.Left} id="context" style={{ top: "92%" }} />
      <Handle type="source" position={Position.Right} id="subs" />
      <Kind icon={Bot} label="Agent" />
      <strong className="gm-ellipsis">{data.name}</strong>
      {data.framework && <span className="gm-sub k-mono">{data.framework}</span>}
    </div>
  );
}

/** The model the agent thinks with: big and on its own, never mistaken for a tool. */
function LlmNode({ data }: NodeProps<Node<{ models: string[] }>>) {
  return (
    <div className="gm-node gm-llm">
      <Handle type="target" position={Position.Bottom} />
      <Kind icon={Cpu} label={data.models.length > 1 ? `${data.models.length} LLMs` : "LLM"} />
      {data.models.map((m) => (
        <strong key={m} className="gm-ellipsis k-mono">{m}</strong>
      ))}
    </div>
  );
}

/** Documents & memory the agent reads. */
function DocsNode() {
  return (
    <div className="gm-node gm-docs">
      <Handle type="source" position={Position.Right} />
      <Kind icon={FileText} label="Documents & memory" />
    </div>
  );
}

/** Every tool in one tinted box; the tools sit inside it. */
function BoxNode({ data }: NodeProps<Node<{ title: string; w: number; h: number; selected: boolean }>>) {
  return (
    <div className={`gm-box${data.selected ? " gm-selected" : ""}`} style={{ width: data.w, height: data.h }}>
      <Handle type="target" position={Position.Top} id="in" style={{ left: "38%" }} />
      <Handle type="source" position={Position.Top} id="out" style={{ left: "62%" }} />
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

function linkHref(slug: string) {
  return `/app/projects/${encodeURIComponent(slug)}`;
}

/** A sub-agent this agent hands work to: from its code, from traffic, or both. */
function SubagentNode({ data }: NodeProps<Node<{ link: MapLink; framework?: string | null }>>) {
  const s = data.link;
  return (
    <Link href={linkHref(s.slug)} className={`gm-node gm-sub-agent${s.seen ? "" : " gm-unseen"}`} title={s.slug}>
      <Handle type="target" position={Position.Left} />
      <Kind icon={Bot} label={relationLabel(s.relation, data.framework)} />
      <strong className="gm-ellipsis">{s.name || s.slug}</strong>
    </Link>
  );
}

/** An agent that hands this one work, so a sub-agent's map links back up. */
function ParentNode({ data }: NodeProps<Node<{ link: MapLink }>>) {
  const s = data.link;
  return (
    <Link href={linkHref(s.slug)} className={`gm-node gm-sub-agent${s.seen ? "" : " gm-unseen"}`} title={s.slug}>
      <Kind icon={Bot} label={parentLabel(s.relation)} />
      <strong className="gm-ellipsis">{s.name || s.slug}</strong>
      <Handle type="source" position={Position.Top} />
    </Link>
  );
}

const NODE_TYPES = {
  user: UserNode,
  agent: AgentNode,
  llm: LlmNode,
  docs: DocsNode,
  box: BoxNode,
  tool: ToolNode,
  more: MoreNode,
  subagent: SubagentNode,
  parent: ParentNode,
};

// --- edges -------------------------------------------------------------------------

type GuardData = { stage?: Stage; title: string; selected?: boolean; hovered?: boolean; onPick?: () => void; onHover?: (on: boolean) => void };

/**
 * A line a guardrail step sits on. Easy to hit: a wide invisible band follows the line,
 * hovering lights the line and opens its badge into a label, and the line, the band and
 * the badge all open the same panel. Our mark when something guards it; a "+" when not.
 */
function GuardEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style, data }: EdgeProps<Edge<GuardData>>) {
  const [path, x, y] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const on = guarded(data?.stage);
  const sel = Boolean(data?.selected);
  const hot = Boolean(data?.hovered);
  const lit = sel || hot;
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
            className={`gm-mark nodrag nopan${on ? " gm-mark-on" : " gm-mark-off"}${sel ? " gm-selected" : ""}${lit ? " gm-mark-open" : ""}`}
            style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)` }}
            onClick={data.onPick}
            onMouseEnter={() => data.onHover?.(true)}
            onMouseLeave={() => data.onHover?.(false)}
            onFocus={() => data.onHover?.(true)}
            onBlur={() => data.onHover?.(false)}
            aria-label={`${data.title}: ${on ? "guardrails here" : "no guardrails yet"}. Open.`}
          >
            {on ? <Mark size={18} /> : <span className="gm-mark-plus" aria-hidden>+</span>}
            {lit && (
              <span className="gm-mark-label">
                {data.title}
                <span>{on ? " · see guardrails" : " · add guardrails"}</span>
              </span>
            )}
          </button>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const EDGE_TYPES = { guard: GuardEdge };

// --- layout ----------------------------------------------------------------------

/** Tools drawn in the box before "+N more"; expanded, up to BOX_MAX. */
const BOX_FIRST = 6;
const BOX_MAX = 24;
const TOOL_W = 240;
const TOOL_H = 38;
const GAP = 10;
const PAD = 16;
const HEAD = 48;

function layout(
  map: AgentMap,
  tools: MapTool[],
  hidden: number,
  selected: Selected,
  pick: (stage: string) => void,
): { nodes: Node[]; edges: Edge[] } {
  const stage = (key: string) => map.stages.find((s) => s.key === key);
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const arrow = { type: MarkerType.ArrowClosed, width: 14, height: 14 };
  /** A line that a guardrail step sits on. */
  const guard = (id: string, source: string, target: string, key: string, title: string, extra: Partial<Edge> = {}) =>
    edges.push({
      id: `edge:${key}`,
      source,
      target,
      type: "guard",
      markerEnd: arrow,
      data: { stage: stage(key), title, selected: selected?.kind === "stage" && selected.key === key, onPick: () => pick(key) },
      ...extra,
    });

  const AGENT_X = 360;
  const AGENT_Y = 120;

  // One user: the message goes to the agent, the reply comes back to the same user.
  nodes.push({ id: "user", type: "user", position: { x: 0, y: AGENT_Y + 18 }, data: {} });
  nodes.push({ id: "agent", type: "agent", position: { x: AGENT_X, y: AGENT_Y }, data: { name: map.agent.name, framework: map.agent.framework } });
  guard("in", "user", "agent", "input", "The user's message", { sourceHandle: "out", targetHandle: "in" });
  guard("out", "agent", "user", "output", "The agent's reply", { sourceHandle: "reply", targetHandle: "back" });

  const models = map.agent.models || [];
  if (models.length) {
    nodes.push({ id: "llm", type: "llm", position: { x: AGENT_X + 10, y: AGENT_Y - 140 }, data: { models } });
    edges.push({ id: "e-llm", source: "agent", sourceHandle: "llm", target: "llm", style: { stroke: "var(--af-link)", strokeDasharray: "5 4", strokeWidth: 1.5 } });
  }

  if (stage("context")) {
    nodes.push({ id: "docs", type: "docs", position: { x: 20, y: AGENT_Y + 190 }, data: {} });
    guard("ctx", "docs", "agent", "context", "Documents & memory", { targetHandle: "context", style: { strokeDasharray: "4 4" } });
  }

  if (tools.length || hidden) {
    const more = hidden > 0;
    const cells = tools.length + (more ? 1 : 0);
    const cols = Math.min(3, Math.max(1, cells));
    const rows = Math.ceil(cells / cols);
    const w = PAD * 2 + cols * TOOL_W + (cols - 1) * GAP;
    const h = HEAD + rows * TOOL_H + (rows - 1) * GAP + PAD;
    const x = Math.max(AGENT_X + 120 - w / 2, 240);
    const total = tools.length + hidden;
    nodes.push({ id: "box:tools", type: "box", position: { x, y: AGENT_Y + 200 }, data: { title: plural(total, "tool"), w, h, selected: selected?.kind === "tools" } });
    const at = (i: number) => ({ x: PAD + (i % cols) * (TOOL_W + GAP), y: HEAD + Math.floor(i / cols) * (TOOL_H + GAP) });
    tools.forEach((tl, i) =>
      nodes.push({ id: `tool:${tl.key}`, type: "tool", parentId: "box:tools", extent: "parent", position: at(i), data: { tool: tl, selected: selected?.kind === "tool" && selected.key === tl.key } }),
    );
    if (more) nodes.push({ id: "more:tools", type: "more", parentId: "box:tools", extent: "parent", position: at(tools.length), data: { label: `+${hidden} more` } });
    guard("calls", "agent", "box:tools", "tool_call", "Every tool call", { sourceHandle: "calls", targetHandle: "in" });
    guard("results", "box:tools", "agent", "tool_result", "Every tool result", { sourceHandle: "out", targetHandle: "results", style: { strokeDasharray: "4 4" } });
  }

  const subs = drawnSubagents(map.subagents, DRAW_SUBAGENTS);
  subs.shown.forEach((s, i) => {
    const id = `sub:${s.slug}`;
    nodes.push({ id, type: "subagent", position: { x: AGENT_X + 330, y: AGENT_Y - 40 + i * 90 }, data: { link: s, framework: map.agent.framework } });
    edges.push({ id: `es-${i}`, source: "agent", sourceHandle: "subs", target: id, style: { strokeDasharray: "6 4", opacity: s.seen ? 1 : 0.6 } });
  });
  (map.parents || []).slice(0, 3).forEach((p, i) => {
    const id = `parent:${p.slug}`;
    nodes.push({ id, type: "parent", position: { x: -40 + i * 210, y: AGENT_Y + 320 }, data: { link: p } });
    edges.push({ id: `ep-${i}`, source: id, target: "user", targetHandle: "parents", style: { strokeDasharray: "6 4", opacity: p.seen ? 1 : 0.6 } });
  });
  return { nodes, edges };
}

/** The tools the box draws: the first few, every one when expanded, and always the one selected. */
function boxTools(visible: MapTool[], expanded: boolean, selected: Selected): MapTool[] {
  const limit = visible.length <= BOX_FIRST + 1 ? visible.length : expanded ? BOX_MAX : BOX_FIRST;
  const shown = visible.slice(0, limit);
  if (selected?.kind === "tool" && !shown.some((t) => t.key === selected.key)) {
    const t = visible.find((x) => x.key === selected.key);
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
      <div>
        <strong className="gm-guide-title">{stage.title}</strong>
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
        <Mark size={16} /> Guardrails here
      </span>
      <span className="gm-legend-kind">
        <span className="gm-legend-plus" aria-hidden>+</span> None yet: click to add
      </span>
      <span className="gm-legend-hint">Click any line or tool to see and change its guardrails</span>
    </div>
  );
}

/**
 * One project's guardrails, drawn where they act: on the user's message, on each
 * tool call, on what tools return, and on the reply. The canvas shows the shape
 * first: many tools are one node until expanded, then groups, then a group's
 * tools, each with "+N more" into the inspector's list. The inspector beside it
 * shows what is selected, and the project itself (`summary`) when nothing is.
 */
export function GuardrailMap({ map, lastTest, catalog }: { map: AgentMap; lastTest?: LastTest; catalog?: Catalog }) {
  const [selected, setSelected] = useState<Selected>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const [by, setBy] = useState<GroupBy>("impact");
  const [filter, setFilter] = useState<ToolFilter>("all");

  const visible = useMemo(() => filterTools(map.tools, query, filter), [map.tools, query, filter]);
  const groups = useMemo(() => groupTools(visible, by), [visible, by]);
  const showAll = expanded;
  const drawn = useMemo(() => boxTools(visible, expanded, selected), [visible, expanded, selected]);
  const laid = useMemo(
    () => layout(map, drawn, visible.length - drawn.length, selected, (key) => setSelected({ kind: "stage", key })),
    [map, drawn, visible.length, selected],
  );
  const nodes = laid.nodes;
  // The line under the pointer (or its badge) lights up and labels itself.
  const edges = useMemo(
    () =>
      laid.edges.map((e) =>
        e.type === "guard"
          ? { ...e, data: { ...(e.data as GuardData), hovered: hovered === e.id, onHover: (on: boolean) => setHovered(on ? e.id : null) } }
          : e,
      ),
    [laid.edges, hovered],
  );
  const many = map.tools.length > BOX_FIRST + 1;

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

  return (
    <div className="gm">
      <div className="gm-canvas">
        <div className="gm-bar">
          <Legend />
          {many && (
            <div className="gm-bar-end">
              <button
                type="button"
                className="k-btn k-btn-sm"
                aria-pressed={showAll}
                onClick={() => {
                  if (showAll) {
                    setExpanded(false);
                    if (selected?.kind === "tool" || selected?.kind === "group") setSelected(null);
                  } else setExpanded(true);
                }}
              >
                {showAll ? "Show fewer tools" : `Show all ${map.tools.length} tools`}
              </button>
            </div>
          )}
        </div>
        <div className="gm-flow">
          <ReactFlow
            // Re-fit when what is drawn changes shape, not on every selection.
            key={`${visible.length}|${drawn.length}`}
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            edgeTypes={EDGE_TYPES}
            onEdgeMouseEnter={(_, edge) => edge.type === "guard" && setHovered(edge.id)}
            onEdgeMouseLeave={() => setHovered(null)}
            onEdgeClick={(_, edge) => {
              const key = edge.id.startsWith("edge:") ? (edge.data as GuardData | undefined)?.stage?.key : undefined;
              if (key) setSelected({ kind: "stage", key });
            }}
            fitView
            fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
            minZoom={0.2}
            maxZoom={1.5}
            nodesDraggable={false}
            nodesConnectable={false}
            proOptions={{ hideAttribution: true }}
            onNodeClick={(_, node) => {
              const [kind, ...rest] = node.id.split(":");
              const key = rest.join(":");
              if (kind === "stage" || kind === "tool") setSelected({ kind, key });
              else if (node.id === "box:tools") setSelected({ kind: "tools", key: "" });
              else if (node.id === "more:tools") setExpanded(true);
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
        <Panel map={map} selected={selected} groups={groups} onSelect={setSelected} lastTest={lastTest} catalog={catalog} toolList={toolList} />
      </div>
    </div>
  );
}
