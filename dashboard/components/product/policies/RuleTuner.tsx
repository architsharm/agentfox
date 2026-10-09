"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";
import type { RulePack } from "@/lib/product/rules";
import { ACTION_CHOICES, SENSITIVITY, sensitivityOf } from "@/lib/product/vocab";

type Change = { effect?: string; enabled?: boolean; message?: string; on_block?: string; min_score?: number; overridable?: boolean };

/** One agent's own copy of this rule, when it has one. */
type OwnCopy = { effect: string; enabled: boolean; min_score: number | null; message: string; on_block: string };

/** Every agent, sub-agents nested under the agent that hands off to them. */
export type RuleScope = {
  overridable: boolean;
  protected: boolean;
  can_allow_loosening: boolean;
  agents: { slug: string; name: string; depth: number; parent: string | null; own: OwnCopy | null }[];
};

type Sim = {
  replayed: number;
  counts: { newly_blocked: number; newly_allowed: number; newly_escalated: number };
};

type Preview = {
  pack: string;
  label: string;
  change: Change;
  /** "every": a saved version of the pack to make live. "some": agent layers to write. */
  scope: "every" | "some";
  version?: number;
  mode: string | null;
  agents?: { agent: string; mode: string }[];
  tests?: null | { passed: number; failed: number; results: { id: string; sample: string; fires: boolean; passed: boolean }[] };
  simulation: Sim | null;
};

type Blocked = { message: string; canAllow: boolean };

/** Like callJson, but keeps a structured 409 detail instead of flattening it. */
async function post(url: string, body: unknown): Promise<{ ok: boolean; status: number; data: any }> {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

/**
 * Change what one rule does: pick an action or switch it off, see what that would
 * have done to the last week of traffic, then apply. Nothing changes in force until
 * Apply.
 *
 * Applies to every agent (a new version of the rule's pack) or only some agents
 * (a copy in each chosen agent's own layer). For some agents, tighter is always
 * allowed; looser only where the workspace rule allows agents to loosen it.
 * `exact`: the rule matches exact words or patterns, so sensitivity means nothing.
 * `agent`: start on "Only some agents" with this agent chosen.
 */
export function RuleTuner({
  ruleId,
  packs,
  exact = false,
  scopes = {},
  agent,
}: {
  ruleId: string;
  packs: RulePack[];
  exact?: boolean;
  scopes?: Record<string, RuleScope>;
  agent?: string;
}) {
  const router = useRouter();
  // Agent layers (`agent.<slug>`) are what "Only some agents" writes; the workspace
  // packs are where the rule lives for everyone.
  const workspace = packs.filter((p) => !p.key.startsWith("agent."));
  const [pack, setPack] = useState((workspace[0] || packs[0])?.key || "");
  const base = packs.find((p) => p.key === pack) || packs[0];
  const tree = scopes[pack] || scopes[workspace[0]?.key || ""];
  const [some, setSome] = useState(Boolean(agent && tree));
  const [chosen, setChosen] = useState<string[]>(agent ? [agent] : []);
  const [withSubs, setWithSubs] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [blocked, setBlocked] = useState<Blocked | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState(base?.message || "");

  if (!base) return <div className="k-empty">This rule is not in any installed pack.</div>;

  // With one agent chosen, show what that agent has now.
  const own = some && chosen.length === 1 ? tree?.agents.find((a) => a.slug === chosen[0])?.own : null;
  const current = own
    ? { ...base, effect: own.effect, enabled: own.enabled, minScore: own.min_score, message: own.message, onBlock: own.on_block }
    : base;
  const packChoices = some ? workspace : packs;

  const reset = () => {
    setPreview(null);
    setBlocked(null);
    setError("");
  };

  const propose = async (change: Change, label: string, every = !some) => {
    setBusy(true);
    reset();
    try {
      if (!every) {
        if (!chosen.length) throw new Error("Choose at least one agent.");
        const r = await post(`/api/policies/${encodeURIComponent(pack)}/rules/${encodeURIComponent(ruleId)}/scope`, {
          ...change,
          agents: chosen,
          include_delegates: withSubs,
          preview: true,
        });
        if (r.status === 409 && typeof r.data.detail === "object") {
          setBlocked({ message: r.data.detail.message, canAllow: Boolean(r.data.detail.can_allow_loosening) });
          return;
        }
        if (!r.ok) throw new Error(typeof r.data.detail === "string" ? r.data.detail : "Could not check this change.");
        setPreview({ pack, label, change, scope: "some", mode: null, agents: r.data.agents, simulation: r.data.simulation });
        return;
      }
      const out = await callJson(`/api/policies/${encodeURIComponent(base.key)}/rules/${encodeURIComponent(ruleId)}`, "POST", change);
      setPreview({ pack: base.key, label, change, scope: "every", version: out.version, mode: out.mode, simulation: out.simulation, tests: out.tests });
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      if (preview.scope === "some") {
        const r = await post(`/api/policies/${encodeURIComponent(preview.pack)}/rules/${encodeURIComponent(ruleId)}/scope`, {
          ...preview.change,
          agents: chosen,
          include_delegates: withSubs,
        });
        if (!r.ok) throw new Error(typeof r.data.detail === "string" ? r.data.detail : r.data.detail?.message || "Could not apply.");
      } else {
        await callJson(`/api/policies/${encodeURIComponent(preview.pack)}/mode`, "POST", { mode: preview.mode || "observe", version: preview.version });
      }
      setPreview(null);
      router.refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const toggle = (slug: string) => {
    reset();
    setChosen((c) => (c.includes(slug) ? c.filter((s) => s !== slug) : [...c, slug]));
  };

  const s = preview?.simulation;
  const watching = preview?.scope === "some" ? (preview.agents || []).filter((a) => a.mode !== "enforce").length : 0;
  return (
    <div className="k-form">
      {tree && workspace.length > 0 && (
        <div className="k-field">
          <label>Applies to</label>
          <div className="k-seg" role="group" aria-label="Applies to">
            <button disabled={busy} className={!some ? "active" : ""} onClick={() => { reset(); setSome(false); }}>
              Every agent
            </button>
            <button
              disabled={busy}
              className={some ? "active" : ""}
              onClick={() => {
                reset();
                setSome(true);
                if (!workspace.some((p) => p.key === pack)) setPack(workspace[0].key);
              }}
            >
              Only some agents
            </button>
          </div>
        </div>
      )}

      {some && tree && (
        <div className="k-field">
          <label>Agents</label>
          <div className="k-form" style={{ gap: 4, maxHeight: 240, overflowY: "auto" }}>
            {tree.agents.map((a) => (
              <label key={a.slug} className="k-check" style={{ paddingLeft: a.depth * 18 }}>
                <input type="checkbox" checked={chosen.includes(a.slug)} disabled={busy} onChange={() => toggle(a.slug)} />
                <span>{a.depth > 0 ? "↳ " : ""}{a.name}</span>
                {a.own && <span className="k-pill k-pill-outline">Changed</span>}
              </label>
            ))}
            {!tree.agents.length && <span className="k-muted">No agents yet.</span>}
          </div>
          {tree.agents.some((a) => a.depth > 0) && (
            <label className="k-check">
              <input type="checkbox" checked={withSubs} disabled={busy} onChange={(e) => { reset(); setWithSubs(e.target.checked); }} />
              Include the agents they hand off to
            </label>
          )}
          {!tree.overridable && <span className="k-muted">Agents can make this rule stricter, not looser.</span>}
        </div>
      )}

      {packChoices.length > 1 && (
        <div className="k-field">
          <label>Pack</label>
          <select
            className="k-select"
            value={pack}
            onChange={(e) => {
              reset();
              setPack(e.target.value);
              setMessage(packs.find((p) => p.key === e.target.value)?.message || "");
            }}
            style={{ width: 260 }}
          >
            {packChoices.map((p) => (
              <option key={p.key} value={p.key}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="k-field">
        <label>When it fires</label>
        <div className="k-seg" role="group" aria-label="Action">
          {ACTION_CHOICES.map((a) => {
            const active = current.enabled && (current.effect === a.effect || (a.effect === "redact" && ["mask", "tokenize"].includes(current.effect)));
            return (
              <button key={a.effect} disabled={busy} className={active ? "active" : ""} onClick={() => !active && propose({ effect: a.effect, enabled: true }, a.label)}>
                {a.label}
              </button>
            );
          })}
        </div>
      </div>
      <div className="k-field">
        <label>Rule</label>
        <div className="k-seg" role="group" aria-label="On or off">
          <button disabled={busy} className={current.enabled ? "active" : ""} onClick={() => !current.enabled && propose({ enabled: true }, "On")}>
            On
          </button>
          <button disabled={busy} className={!current.enabled ? "active" : ""} onClick={() => current.enabled && propose({ enabled: false }, "Off")}>
            Off
          </button>
        </div>
      </div>

      {current.minScore !== null && !exact && (
        <div className="k-field">
          <label>Sensitivity</label>
          <div className="k-seg" role="group" aria-label="Sensitivity">
            {SENSITIVITY.map((lvl) => {
              const active = sensitivityOf(current.minScore) === lvl.key;
              return (
                <button key={lvl.key} disabled={busy} className={active ? "active" : ""} onClick={() => !active && propose({ min_score: lvl.minScore }, `${lvl.label} sensitivity`)}>
                  {lvl.label}
                </button>
              );
            })}
          </div>
        </div>
      )}
      {current.effect === "block" && (
        <div className="k-field">
          <label>On a blocked answer</label>
          <div className="k-seg" role="group" aria-label="On a blocked answer">
            <button disabled={busy} className={current.onBlock !== "reask" ? "active" : ""} onClick={() => current.onBlock === "reask" && propose({ on_block: "refuse" }, "Refuse")}>
              Refuse
            </button>
            <button disabled={busy} className={current.onBlock === "reask" ? "active" : ""} onClick={() => current.onBlock !== "reask" && propose({ on_block: "reask" }, "Ask the model to fix it")}>
              Ask the model to fix it
            </button>
          </div>
        </div>
      )}
      {["block", "escalate"].includes(current.effect) && (
        <div className="k-field">
          <label>Message to the user</label>
          <div className="k-pills" style={{ gap: 8 }}>
            <input
              className="k-input"
              style={{ flex: 1, minWidth: 240 }}
              maxLength={500}
              placeholder="Sorry, I can't help with that."
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
            <button className="k-btn" disabled={busy || message === current.message} onClick={() => propose({ message }, "New message")}>
              Save
            </button>
          </div>
        </div>
      )}

      {busy && !preview && <div className="k-muted">Checking against the last 7 days…</div>}
      {error && <div className="error">{error}</div>}

      {blocked && (
        <div className="k-preview">
          <strong>Not allowed for some agents</strong>
          <span className="k-muted">{blocked.message}</span>
          {blocked.canAllow && (
            <div className="k-pills" style={{ gap: 8 }}>
              <button
                className="k-btn"
                disabled={busy}
                onClick={() => {
                  setSome(false);
                  propose({ overridable: true }, "Let agents loosen this rule", true);
                }}
              >
                Let agents loosen this rule
              </button>
            </div>
          )}
        </div>
      )}

      {preview && (
        <div className="k-preview">
          <div className="k-preview-head">
            <strong>{preview.label}</strong>
            {preview.scope === "some" && <span className="k-muted"> · for {(preview.agents || []).map((a) => a.agent).join(", ")}</span>}
            <span className="k-muted"> · replayed {s?.replayed ?? 0} requests from the last 7 days</span>
          </div>
          <div className="k-preview-nums">
            <span><strong>{s?.counts.newly_blocked ?? 0}</strong> newly blocked</span>
            <span><strong>{s?.counts.newly_escalated ?? 0}</strong> newly held</span>
            <span><strong>{s?.counts.newly_allowed ?? 0}</strong> newly allowed</span>
          </div>
          {preview.tests && preview.tests.passed + preview.tests.failed > 0 && (
            <div className="k-form" style={{ gap: 4 }}>
              <span className={`k-pill ${preview.tests.failed ? "k-pill-bad" : "k-pill-ok"}`} style={{ alignSelf: "flex-start" }}>
                Tests: {preview.tests.passed} of {preview.tests.passed + preview.tests.failed} pass
              </span>
              {preview.tests.results
                .filter((t) => !t.passed)
                .map((t) => (
                  <span key={t.id} className="k-muted">
                    {t.fires ? "No longer catches" : "Now catches"} “{t.sample}”
                  </span>
                ))}
            </div>
          )}
          {preview.scope === "every" && base.mode !== "enforce" && <div className="k-muted">This pack is watching, so nothing will be blocked yet.</div>}
          {watching > 0 && <div className="k-muted">Rules of their own are watching for {watching === 1 ? "this agent" : `${watching} of these agents`}, so nothing new will be blocked yet.</div>}
          <div className="k-pills" style={{ gap: 8 }}>
            <button className="k-btn-primary" disabled={busy} onClick={apply}>
              Apply
            </button>
            <button className="k-btn-ghost" disabled={busy} onClick={() => setPreview(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
