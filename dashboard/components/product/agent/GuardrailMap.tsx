"use client";

import "@xyflow/react/dist/style.css";

import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { ActionPill, ModePill, Pill } from "@/components/kit";
import {
  DRAW_EACH,
  DRAW_GROUPS,
  DRAW_OPEN,
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
  stageTone,
  toolTone,
  type AgentMap,
  type GroupBy,
  type MapRule,
  type MapTool,
  type Permission,
  type RuleSetting,
  type Stage,
  type Stats,
  type Tone,
  type ToolFilter,
  type ToolGroup,
} from "@/lib/product/guardrailMap";
import { IMPACT, detectorName, ruleTitle } from "@/lib/product/vocab";

export type { AgentMap, MapRule } from "@/lib/product/guardrailMap";

type Selected = { kind: "stage" | "tool" | "group"; key: string } | null;

const SOURCE: Record<string, string> = { code: "In code", granted: "Granted", seen: "Called" };

function sourceLabel(tl: MapTool): string {
  return (tl.sources || []).map((x) => SOURCE[x]).join(" · ");
}

function stopped(s: Stats) {
  return (s.blocked || 0) + (s.held || 0) + (s.masked || 0);
}

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
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
  const t = stageTone(s.rules, s.detectors);
  return (
    <div className={`gm-node gm-stage gm-${t}${data.selected ? " gm-selected" : ""}`} title={TONE_LABEL[t]}>
      <Handle type="target" position={Position.Left} />
      <Handle type="target" position={Position.Top} id="top" />
      <Handle type="source" position={Position.Right} />
      <Handle type="source" position={Position.Top} id="topout" />
      <span className="gm-kicker">{s.title}</span>
      <strong>
        {c.enforcing} enforcing{c.watching ? ` · ${c.watching} watching` : ""}
      </strong>
      <span className="gm-sub">{plural(s.detectors.length, "check")} run here</span>
      {s.stats.total ? (
        <span className="gm-sub">
          {s.stats.total} seen · {stopped(s.stats)} stopped
        </span>
      ) : null}
    </div>
  );
}

function ToolNode({ data }: NodeProps<Node<{ tool: MapTool; selected: boolean }>>) {
  const tl = data.tool;
  const p = PERMISSION[tl.permission];
  const rules = tl.rules.length + tl.ladders.length;
  const t = toolTone(tl);
  return (
    <div className={`gm-node gm-tool gm-${t} gm-perm-${tl.permission}${data.selected ? " gm-selected" : ""}`} title={TONE_LABEL[t]}>
      <Handle type="target" position={Position.Top} />
      <Handle type="source" position={Position.Bottom} />
      <span className="gm-kicker k-mono gm-ellipsis" title={tl.key}>{shortKey(tl.key)}</span>
      <span className={`k-pill k-pill-${p.tone}`}>{p.label}</span>
      <span className="gm-sub">
        {IMPACT[tl.impact || ""] || "Risk not set"}
        {rules ? ` · ${plural(rules, "rule")}` : ""}
      </span>
      {tl.stats.total ? (
        <span className="gm-sub">
          {tl.stats.total} calls · {stopped(tl.stats)} stopped
        </span>
      ) : null}
    </div>
  );
}

function GroupNode({ data }: NodeProps<Node<{ group: ToolGroup; total: number; open: boolean; selected: boolean }>>) {
  const g = data.group;
  const s = groupSummary(g.tools);
  return (
    <div className={`gm-node gm-group gm-${s.tone}${data.open ? " gm-open" : ""}${data.selected ? " gm-selected" : ""}`} title={TONE_LABEL[s.tone]}>
      <Handle type="target" position={Position.Top} />
      <Handle type="source" position={Position.Bottom} />
      <span className="gm-kicker gm-ellipsis">{g.label}</span>
      <strong>{plural(g.tools.length, "tool")}</strong>
      <span className="gm-perms">
        {s.allowed ? <span className="gm-perm gm-perm-ok">{s.allowed} allowed</span> : null}
        {s.ask ? <span className="gm-perm gm-perm-held">{s.ask} ask</span> : null}
        {s.denied ? <span className="gm-perm gm-perm-bad">{s.denied} not allowed</span> : null}
      </span>
      {s.calls ? (
        <span className="gm-sub">
          {s.calls} calls · {s.stopped} stopped
        </span>
      ) : null}
      <span className="gm-sub gm-hint">{data.open ? "Open" : "Click to open"}</span>
    </div>
  );
}

function MoreNode({ data }: NodeProps<Node<{ label: string }>>) {
  return (
    <div className="gm-node gm-more">
      <Handle type="target" position={Position.Top} />
      {data.label}
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

// "group" is a built-in React Flow type with its own styling, so ours is "toolgroup".
const NODE_TYPES = { end: EndNode, agent: AgentNode, stage: StageNode, tool: ToolNode, toolgroup: GroupNode, more: MoreNode, subagent: SubagentNode };

// --- layout ----------------------------------------------------------------------

const COL = 250;
const ROW = 150;
const PER_ROW = 4;
const GROUPS_PER_ROW = 5;
const GROUP_ROW = 180;

type Drawn = { tools: MapTool[]; groups: ToolGroup[] | null; open: ToolGroup | null };

/**
 * What the canvas draws for the tools: each one when there are few; otherwise one
 * node per group, with the opened group's tools under it. Everything else is in the
 * list beside the canvas.
 */
function drawn(visible: MapTool[], by: GroupBy, openKey: string | null): Drawn {
  if (visible.length <= DRAW_EACH) return { tools: visible, groups: null, open: null };
  const groups = groupTools(visible, by);
  return { tools: [], groups, open: groups.find((g) => g.key === openKey) || null };
}

function layout(map: AgentMap, d: Drawn, hidden: number, selected: Selected): { nodes: Node[]; edges: Edge[] } {
  const stage = (key: string) => map.stages.find((s) => s.key === key);
  const isSel = (kind: string, key: string) => selected?.kind === kind && selected.key === key;
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const edge = (id: string, source: string, target: string, extra: Partial<Edge> = {}) =>
    edges.push({ id, source, target, markerEnd: { type: MarkerType.ArrowClosed }, ...extra });

  const agentX = 2 * COL;
  nodes.push({ id: "user-in", type: "end", position: { x: 0, y: 40 }, data: { label: "User" } });
  const input = stage("input");
  if (input) nodes.push({ id: "stage:input", type: "stage", position: { x: COL - 30, y: 10 }, data: { stage: input, selected: isSel("stage", "input") } });
  nodes.push({ id: "agent", type: "agent", position: { x: agentX, y: 25 }, data: { name: map.agent.name, slug: map.agent.slug } });
  const output = stage("output");
  if (output) nodes.push({ id: "stage:output", type: "stage", position: { x: agentX + COL + 10, y: 10 }, data: { stage: output, selected: isSel("stage", "output") } });
  nodes.push({ id: "user-out", type: "end", position: { x: agentX + 2 * COL + 20, y: 40 }, data: { label: "User" } });
  edge("e1", "user-in", input ? "stage:input" : "agent");
  if (input) edge("e2", "stage:input", "agent", { targetHandle: "in" });
  edge("e3", "agent", output ? "stage:output" : "user-out", { sourceHandle: "out" });
  if (output) edge("e4", "stage:output", "user-out");

  const context = stage("context");
  if (context) {
    nodes.push({ id: "stage:context", type: "stage", position: { x: COL - 30, y: 190 }, data: { stage: context, selected: isSel("stage", "context") } });
    edge("ec", "stage:context", "agent", { targetHandle: "in", style: { strokeDasharray: "4 4" } });
  }

  const call = stage("tool_call");
  const result = stage("tool_result");
  // Rows centred under the tool-call step: tools four to a row, groups five.
  const grid = (n: number, top: number, i: number, per = PER_ROW, row = ROW) => {
    const perRow = Math.min(per, n);
    const start = agentX + 80 - ((perRow - 1) * COL) / 2 - 100;
    return { x: start + (i % perRow) * COL, y: top + Math.floor(i / perRow) * row };
  };
  const rows = (n: number, per = PER_ROW) => Math.ceil(n / per);
  let bottom = 380;
  const lastIds: string[] = [];

  if (call && (d.tools.length || d.groups?.length || hidden)) {
    nodes.push({ id: "stage:tool_call", type: "stage", position: { x: agentX - 20, y: 200 }, data: { stage: call, selected: isSel("stage", "tool_call") } });
    edge("et", "agent", "stage:tool_call", { sourceHandle: "down", targetHandle: "top" });

    const toolNode = (tl: MapTool, pos: { x: number; y: number }, from: string, i: string) => {
      const id = `tool:${tl.key}`;
      nodes.push({ id, type: "tool", position: pos, data: { tool: tl, selected: isSel("tool", tl.key) } });
      if (from !== "stage:tool_call") {
        // Inside an opened group the tool's own border says whether it is allowed; keep the wires quiet.
        edges.push({ id: `etc-${i}`, source: from, target: id, style: { opacity: 0.35 } });
        return id;
      }
      edge(`etc-${i}`, from, id, {
        animated: tl.permission !== "not_granted" && Boolean(tl.stats.total),
        style: tl.permission === "not_granted" ? { stroke: "var(--viz-blocked)", strokeDasharray: "4 4" } : undefined,
      });
      return id;
    };

    if (!d.groups) {
      d.tools.forEach((tl, i) => lastIds.push(toolNode(tl, grid(d.tools.length, 380, i), "stage:tool_call", String(i))));
      bottom = 380 + rows(d.tools.length) * ROW;
    } else {
      const shown = d.groups.slice(0, DRAW_GROUPS);
      const extra = d.groups.length - shown.length;
      const cells = shown.length + (extra ? 1 : 0);
      shown.forEach((g, i) => {
        const id = `group:${g.key}`;
        const open = d.open?.key === g.key;
        nodes.push({ id, type: "toolgroup", position: grid(cells, 380, i, GROUPS_PER_ROW, GROUP_ROW), data: { group: g, open, selected: isSel("group", g.key) } });
        edge(`eg-${i}`, "stage:tool_call", id, { animated: g.tools.some((t) => t.stats.total) });
        lastIds.push(id);
      });
      if (extra) {
        nodes.push({ id: "more:groups", type: "more", position: grid(cells, 380, shown.length, GROUPS_PER_ROW, GROUP_ROW), data: { label: `${plural(extra, "more group")} in the list` } });
        edge("eg-more", "stage:tool_call", "more:groups", { style: { strokeDasharray: "4 4" } });
      }
      bottom = 380 + rows(cells, GROUPS_PER_ROW) * GROUP_ROW;
      if (d.open) {
        const ts = d.open.tools.slice(0, DRAW_OPEN);
        const rest = d.open.tools.length - ts.length;
        const n = ts.length + (rest ? 1 : 0);
        const top = bottom + 30;
        const from = `group:${d.open.key}`;
        // The opened group's tools hang off it; its own node carries the edge onward.
        ts.forEach((tl, i) => toolNode(tl, grid(n, top, i), from, `o${i}`));
        if (rest) {
          nodes.push({ id: "more:tools", type: "more", position: grid(n, top, ts.length), data: { label: `${rest} more in the list` } });
          edge("eo-more", from, "more:tools", { style: { strokeDasharray: "4 4" } });
        }
        bottom = top + rows(n) * ROW;
      }
    }
    if (result) {
      nodes.push({ id: "stage:tool_result", type: "stage", position: { x: agentX - 20, y: bottom + 20 }, data: { stage: result, selected: isSel("stage", "tool_result") } });
      lastIds.forEach((id, i) => edge(`etr-${i}`, id, "stage:tool_result", { targetHandle: "top", style: { opacity: 0.5 } }));
      edge("er", "stage:tool_result", "agent", { targetHandle: "up", type: "smoothstep" });
    }
  }

  map.subagents.forEach((s, i) => {
    const id = `sub:${s.slug}`;
    nodes.push({ id, type: "subagent", position: { x: agentX + 2 * COL + 40, y: 200 + i * 120 }, data: s });
    edge(`es-${i}`, "agent", id, { sourceHandle: "down", style: { strokeDasharray: "6 4" } });
  });
  return { nodes, edges };
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

function Panel({ map, selected, groups, onSelect }: { map: AgentMap; selected: Selected; groups: ToolGroup[]; onSelect: (s: Selected) => void }) {
  const slug = map.agent.slug;
  if (selected?.kind === "stage") {
    const s = map.stages.find((x) => x.key === selected.key);
    if (s)
      return (
        <div className="gm-panel">
          <strong>{s.title}</strong>
          <StatLine days={map.window_days} s={s.stats} noun="checked" />
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
          <p>
            <Link href="/app/policies?tab=checks">Choose checks</Link>
          </p>
          <h4>Rules for this agent</h4>
          <RuleList rules={s.rules} slug={slug} />
        </div>
      );
  }
  if (selected?.kind === "group") {
    const g = groups.find((x) => x.key === selected.key);
    if (g) {
      const s = groupSummary(g.tools);
      return (
        <div className="gm-panel">
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
  if (!tl)
    return (
      <div className="gm-panel">
        <strong>Click a step or a tool</strong>
        <p className="k-muted">See and change what applies there.</p>
        {map.everywhere.length > 0 && (
          <>
            <h4>At every step</h4>
            <RuleList rules={map.everywhere} slug={slug} />
          </>
        )}
      </div>
    );
  const limits = Object.entries(tl.limits || {});
  return (
    <div className="gm-panel">
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
      <Link className="k-btn" href={`/app/agents/${encodeURIComponent(slug)}?tab=access`}>
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
  const tones: Tone[] = ["on", "watch", "off"];
  return (
    <div className="gm-legend" aria-label="Legend">
      {tones.map((t) => (
        <span key={t}>
          <i className={`gm-swatch gm-${t}`} aria-hidden /> {TONE_LABEL[t]}
        </span>
      ))}
      <span>
        <i className="gm-swatch gm-swatch-denied" aria-hidden /> Not allowed
      </span>
    </div>
  );
}

/**
 * One agent's guardrails, drawn where they act: on the user's message, on each tool
 * call, on what tools return, and on the reply. Many tools are drawn as groups, with
 * every tool in the searchable list beside the canvas. Click a step or tool to see
 * its rules and change them, or the tool's access, for this agent.
 */
export function GuardrailMap({ map }: { map: AgentMap }) {
  const [selected, setSelected] = useState<Selected>(null);
  const [query, setQuery] = useState("");
  const [by, setBy] = useState<GroupBy>("impact");
  const [filter, setFilter] = useState<ToolFilter>("all");

  const visible = useMemo(() => filterTools(map.tools, query, filter), [map.tools, query, filter]);
  const groups = useMemo(() => groupTools(visible, by), [visible, by]);
  // The group drawn open: the one chosen, or the one holding the chosen tool.
  const openKey =
    selected?.kind === "group"
      ? selected.key
      : selected?.kind === "tool"
        ? groups.find((g) => g.tools.some((t) => t.key === selected.key))?.key || null
        : null;
  const d = useMemo(() => drawn(visible, by, openKey), [visible, by, openKey]);
  const { nodes, edges } = useMemo(() => layout(map, d, map.tools.length - visible.length, selected), [map, d, visible.length, selected]);
  const many = map.tools.length > DRAW_EACH;
  // With many tools the side column holds the tool list and the details, one at a time,
  // so the canvas keeps its width.
  const [tab, setTab] = useState<"tools" | "details">(many ? "tools" : "details");

  const choose = (next: Selected) => {
    setSelected(next);
    if (next) setTab("details");
  };

  return (
    <div className="gm">
      <div className="gm-canvas">
        <Legend />
        <div className="gm-flow">
          <ReactFlow
            // Re-fit when what is drawn changes shape, not on every selection.
            key={`${by}|${openKey || ""}|${visible.length}|${d.groups ? "g" : "t"}`}
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
              const [kind, ...rest] = node.id.split(":");
              const key = rest.join(":");
              if (kind === "stage" || kind === "tool") choose({ kind, key });
              else if (kind === "group") choose(openKey === key && selected?.kind === "group" ? null : { kind: "group", key });
              else if (kind !== "more") setSelected(null);
            }}
            onPaneClick={() => setSelected(null)}
          >
            <Background gap={20} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      </div>
      <div className="gm-side">
        {many && (
          <div className="k-seg gm-side-tabs" role="tablist" aria-label="Side panel">
            <button type="button" role="tab" aria-selected={tab === "tools"} className={tab === "tools" ? "active" : ""} onClick={() => setTab("tools")}>
              Tools {map.tools.length}
            </button>
            <button type="button" role="tab" aria-selected={tab === "details"} className={tab === "details" ? "active" : ""} onClick={() => setTab("details")}>
              Details
            </button>
          </div>
        )}
        {many && tab === "tools" ? (
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
            onSelect={choose}
          />
        ) : (
          <Panel map={map} selected={selected} groups={groups} onSelect={choose} />
        )}
      </div>
    </div>
  );
}
