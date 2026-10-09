"use client";

import "@xyflow/react/dist/style.css";

import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { ActionPill, ModePill, Pill } from "@/components/kit";
import { IMPACT, detectorName, ruleTitle } from "@/lib/product/vocab";

export type MapRule = { id: string; description: string; effect: string; mode: string; level: string; message: string; hits: number };
type Stats = { total?: number; allowed?: number; blocked?: number; held?: number; masked?: number };
type Stage = { key: string; title: string; surfaces: string[]; detectors: string[]; rules: MapRule[]; stats: Stats };
type Tool = {
  key: string;
  name: string;
  impact: string | null;
  permission: "allowed" | "ask" | "not_granted";
  limits: Record<string, any>;
  rules: MapRule[];
  ladders: { key: string; name: string; mode: string; field: string | null }[];
  stats: Stats;
  /** Where the tool is known from: its code, a grant, calls seen. */
  sources?: ("code" | "granted" | "seen")[];
};
export type AgentMap = {
  agent: { slug: string; name: string };
  window_days: number;
  stages: Stage[];
  everywhere: MapRule[];
  tools: Tool[];
  subagents: { slug: string; calls: number }[];
};

type Selected = { kind: "stage"; stage: Stage } | { kind: "tool"; tool: Tool } | null;

const PERMISSION: Record<Tool["permission"], { label: string; tone: string }> = {
  allowed: { label: "Allowed", tone: "ok" },
  ask: { label: "Asks a person", tone: "held" },
  not_granted: { label: "Not allowed", tone: "bad" },
};

function counts(rules: MapRule[]) {
  const enforcing = rules.filter((r) => r.mode === "enforce" && r.effect !== "allow").length;
  return { enforcing, watching: rules.length - enforcing };
}

function tone(rules: MapRule[], detectors: string[] = []): "on" | "watch" | "off" {
  const c = counts(rules);
  if (c.enforcing) return "on";
  if (c.watching || detectors.length) return "watch";
  return "off";
}

const SOURCE: Record<string, string> = { code: "In code", granted: "Granted", seen: "Called" };

function sourceLabel(tl: Tool): string {
  return (tl.sources || []).map((x) => SOURCE[x]).join(" · ");
}

function stopped(s: Stats) {
  return (s.blocked || 0) + (s.held || 0) + (s.masked || 0);
}

// --- nodes -----------------------------------------------------------------------

function EndNode({ data }: NodeProps<Node<{ label: string }>>) {
  return (
    <div className="gm-node gm-end">
      <Handle type="target" position={Position.Left} />
      {data.label}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function AgentNode({ data }: NodeProps<Node<{ name: string; slug: string }>>) {
  return (
    <div className="gm-node gm-agent">
      <Handle type="target" position={Position.Left} id="in" />
      <Handle type="source" position={Position.Right} id="out" />
      <Handle type="source" position={Position.Bottom} id="down" />
      <Handle type="target" position={Position.Bottom} id="up" style={{ left: "70%" }} />
      <span className="gm-kicker">Agent</span>
      <strong>{data.name}</strong>
    </div>
  );
}

function StageNode({ data }: NodeProps<Node<{ stage: Stage; selected: boolean }>>) {
  const s = data.stage;
  const c = counts(s.rules);
  const t = tone(s.rules, s.detectors);
  return (
    <div className={`gm-node gm-stage gm-${t}${data.selected ? " gm-selected" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <Handle type="target" position={Position.Top} id="top" />
      <Handle type="source" position={Position.Right} />
      <Handle type="source" position={Position.Top} id="topout" />
      <span className="gm-kicker">{s.title}</span>
      <strong>
        {c.enforcing} enforcing{c.watching ? ` · ${c.watching} watching` : ""}
      </strong>
      <span className="gm-sub">{s.detectors.length} checks run here</span>
      {s.stats.total ? (
        <span className="gm-sub">
          {s.stats.total} seen · {stopped(s.stats)} stopped
        </span>
      ) : null}
    </div>
  );
}

function ToolNode({ data }: NodeProps<Node<{ tool: Tool; selected: boolean }>>) {
  const tl = data.tool;
  const p = PERMISSION[tl.permission];
  const rules = tl.rules.length + tl.ladders.length;
  return (
    <div className={`gm-node gm-tool gm-perm-${tl.permission}${data.selected ? " gm-selected" : ""}`}>
      <Handle type="target" position={Position.Top} />
      <Handle type="source" position={Position.Bottom} />
      <span className="gm-kicker k-mono">{tl.key}</span>
      <span className={`k-pill k-pill-${p.tone}`}>{p.label}</span>
      <span className="gm-sub">
        {IMPACT[tl.impact || ""] || "Risk not set"}
        {rules ? ` · ${rules} rule${rules === 1 ? "" : "s"}` : ""}
      </span>
      {tl.stats.total ? (
        <span className="gm-sub">
          {tl.stats.total} calls · {stopped(tl.stats)} stopped
        </span>
      ) : null}
      {tl.sources?.length ? <span className="gm-sub gm-source">{sourceLabel(tl)}</span> : null}
    </div>
  );
}

function SubagentNode({ data }: NodeProps<Node<{ slug: string; calls: number }>>) {
  return (
    <Link href={`/app/agents/${encodeURIComponent(data.slug)}?tab=map`} className="gm-node gm-sub-agent">
      <Handle type="target" position={Position.Left} />
      <span className="gm-kicker">Hands off to</span>
      <strong>{data.slug}</strong>
      <span className="gm-sub">{data.calls} times · open its map</span>
    </Link>
  );
}

const NODE_TYPES = { end: EndNode, agent: AgentNode, stage: StageNode, tool: ToolNode, subagent: SubagentNode };

// --- layout ----------------------------------------------------------------------

const COL = 250;

function layout(map: AgentMap, selected: Selected): { nodes: Node[]; edges: Edge[] } {
  const stage = (key: string) => map.stages.find((s) => s.key === key);
  const isSel = (key: string) => selected?.kind === "stage" && selected.stage.key === key;
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const edge = (id: string, source: string, target: string, extra: Partial<Edge> = {}) =>
    edges.push({ id, source, target, markerEnd: { type: MarkerType.ArrowClosed }, ...extra });

  const tools = map.tools;
  const width = 4 * COL;
  const agentX = 2 * COL;

  nodes.push({ id: "user-in", type: "end", position: { x: 0, y: 40 }, data: { label: "User" } });
  const input = stage("input");
  if (input) nodes.push({ id: "input", type: "stage", position: { x: COL - 30, y: 10 }, data: { stage: input, selected: isSel("input") } });
  nodes.push({ id: "agent", type: "agent", position: { x: agentX, y: 25 }, data: { name: map.agent.name, slug: map.agent.slug } });
  const output = stage("output");
  if (output) nodes.push({ id: "output", type: "stage", position: { x: agentX + COL + 10, y: 10 }, data: { stage: output, selected: isSel("output") } });
  nodes.push({ id: "user-out", type: "end", position: { x: agentX + 2 * COL + 20, y: 40 }, data: { label: "User" } });
  edge("e1", "user-in", input ? "input" : "agent");
  if (input) edge("e2", "input", "agent", { targetHandle: "in" });
  edge("e3", "agent", output ? "output" : "user-out", { sourceHandle: "out" });
  if (output) edge("e4", "output", "user-out");

  const context = stage("context");
  if (context) {
    nodes.push({ id: "context", type: "stage", position: { x: COL - 30, y: 190 }, data: { stage: context, selected: isSel("context") } });
    edge("ec", "context", "agent", { targetHandle: "in", style: { strokeDasharray: "4 4" } });
  }

  const call = stage("tool_call");
  const result = stage("tool_result");
  if (tools.length && call) {
    nodes.push({ id: "tool_call", type: "stage", position: { x: agentX - 20, y: 200 }, data: { stage: call, selected: isSel("tool_call") } });
    edge("et", "agent", "tool_call", { sourceHandle: "down", targetHandle: "top" });
    // Tools wrap in rows of four under the tool-call step, so a busy agent stays legible.
    const perRow = Math.min(4, tools.length);
    const rowStart = agentX + 80 - ((perRow - 1) * COL) / 2 - 100;
    tools.forEach((tl, i) => {
      const id = `tool:${tl.key}`;
      nodes.push({
        id,
        type: "tool",
        position: { x: rowStart + (i % perRow) * COL, y: 380 + Math.floor(i / perRow) * 150 },
        data: { tool: tl, selected: selected?.kind === "tool" && selected.tool.key === tl.key },
      });
      edge(`etc-${i}`, "tool_call", id, {
        animated: tl.permission !== "not_granted" && Boolean(tl.stats.total),
        style: tl.permission === "not_granted" ? { stroke: "var(--viz-blocked)", strokeDasharray: "4 4" } : undefined,
      });
      if (result) edge(`etr-${i}`, id, "tool_result");
    });
    if (result) {
      const rows = Math.ceil(tools.length / perRow);
      nodes.push({
        id: "tool_result",
        type: "stage",
        position: { x: agentX - 20, y: 380 + rows * 150 + 20 },
        data: { stage: result, selected: isSel("tool_result") },
      });
      edge("er", "tool_result", "agent", { sourceHandle: "topout", targetHandle: "up", type: "smoothstep" });
    }
  }

  map.subagents.forEach((s, i) => {
    const id = `sub:${s.slug}`;
    nodes.push({ id, type: "subagent", position: { x: Math.max(width, agentX + 2 * COL) + 40, y: 200 + i * 120 }, data: s });
    edge(`es-${i}`, "agent", id, { sourceHandle: "down", style: { strokeDasharray: "6 4" } });
  });
  return { nodes, edges };
}

// --- panel -----------------------------------------------------------------------

function RuleList({ rules }: { rules: MapRule[] }) {
  if (!rules.length) return <p className="k-muted">No rules here.</p>;
  const sorted = [...rules].sort((a, b) => Number(b.mode === "enforce") - Number(a.mode === "enforce") || b.hits - a.hits);
  return (
    <ul className="gm-rules">
      {sorted.map((r) => (
        <li key={`${r.id}:${r.mode}`}>
          <Link href={`/app/policies/rules/${encodeURIComponent(r.id)}`} className="k-name">
            {ruleTitle(r.id, r.description)}
          </Link>
          <span className="k-pills" style={{ gap: 6 }}>
            <ActionPill effect={r.effect} />
            <ModePill mode={r.mode} />
            {r.level === "agent" && <Pill tone="outline">This agent</Pill>}
            {r.hits ? <span className="k-muted">{r.hits} hits</span> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Panel({ map, selected }: { map: AgentMap; selected: Selected }) {
  if (!selected)
    return (
      <div className="gm-panel">
        <strong>Click a step or a tool</strong>
        <p className="k-muted">to see exactly which guardrails apply there.</p>
        {map.everywhere.length > 0 && (
          <>
            <h4>At every step</h4>
            <RuleList rules={map.everywhere} />
          </>
        )}
      </div>
    );
  if (selected.kind === "stage") {
    const s = selected.stage;
    return (
      <div className="gm-panel">
        <strong>{s.title}</strong>
        <p className="k-muted">
          Last {map.window_days} days: {s.stats.total || 0} checked · {s.stats.blocked || 0} blocked · {s.stats.held || 0} held · {s.stats.masked || 0} masked
        </p>
        <h4>Checks that run here</h4>
        {s.detectors.length ? (
          <div className="k-pills" style={{ gap: 6, flexWrap: "wrap" }}>
            {s.detectors.map((d) => (
              <Pill key={d} tone="outline">
                {detectorName(d)}
              </Pill>
            ))}
          </div>
        ) : (
          <p className="k-muted">None.</p>
        )}
        <h4>Rules that act on them</h4>
        <RuleList rules={s.rules} />
      </div>
    );
  }
  const tl = selected.tool;
  const limits = Object.entries(tl.limits || {});
  return (
    <div className="gm-panel">
      <strong className="k-mono">{tl.key}</strong>
      <div className="k-pills" style={{ gap: 6 }}>
        <span className={`k-pill k-pill-${PERMISSION[tl.permission].tone}`}>{PERMISSION[tl.permission].label}</span>
        <Pill tone="outline">{IMPACT[tl.impact || ""] || "Risk not set"}</Pill>
      </div>
      {tl.sources?.length ? <p className="k-muted">Known from: {sourceLabel(tl)}</p> : null}
      <p className="k-muted">
        Last {map.window_days} days: {tl.stats.total || 0} calls · {tl.stats.blocked || 0} blocked · {tl.stats.held || 0} held
      </p>
      <h4>Limits</h4>
      {limits.length ? (
        <ul className="gm-rules">
          {limits.map(([arg, spec]) => (
            <li key={arg} className="k-mono">
              {arg}: {JSON.stringify(spec)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="k-muted">No limits.</p>
      )}
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
      <h4>Rules for this tool</h4>
      <RuleList rules={tl.rules} />
      <p className="k-muted">Every tool call also passes the checks on the Tool calls step.</p>
      <Link className="k-btn" href={`/app/agents/${encodeURIComponent(map.agent.slug)}?tab=access`}>
        Change access
      </Link>
    </div>
  );
}

/**
 * One agent's guardrails, drawn where they act: on the user's message, on each tool
 * call, on what tools return, and on the reply. Green steps enforce, amber only
 * watch. Click anything to see the exact rules and checks.
 */
export function GuardrailMap({ map }: { map: AgentMap }) {
  const [selected, setSelected] = useState<Selected>(null);
  const { nodes, edges } = useMemo(() => layout(map, selected), [map, selected]);

  return (
    <div className="gm">
      <div className="gm-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          fitView
          fitViewOptions={{ padding: 0.12 }}
          minZoom={0.2}
          maxZoom={1.5}
          nodesDraggable={false}
          nodesConnectable={false}
          proOptions={{ hideAttribution: true }}
          onNodeClick={(_, node) => {
            if (node.type === "stage") setSelected({ kind: "stage", stage: (node.data as any).stage });
            else if (node.type === "tool") setSelected({ kind: "tool", tool: (node.data as any).tool });
            else setSelected(null);
          }}
          onPaneClick={() => setSelected(null)}
        >
          <Background gap={20} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
        <div className="gm-legend">
          <span>
            <i className="gm-dot gm-on" /> Enforcing
          </span>
          <span>
            <i className="gm-dot gm-watch" /> Watching only
          </span>
          <span>
            <i className="gm-dot gm-off" /> Nothing set
          </span>
        </div>
      </div>
      <Panel map={map} selected={selected} />
    </div>
  );
}
