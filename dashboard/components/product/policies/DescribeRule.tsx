"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";
import { AgentScope, type ScopeAgent } from "@/components/product/policies/AgentScope";
import { businessRuleName, defaultRuleScope, suggestedLadderName, unusedSentences } from "@/lib/product/policyWords";

const OUTCOME_WORD: Record<string, string> = {
  allow: "allow",
  verify: "check first",
  redact: "mask",
  escalate: "ask a person",
  block: "block",
};

function bandsText(def: any): string[] {
  const unit = def.unit === "USD" ? "$" : "";
  const field = String(def.field || def.field_path || "amount").split(".").pop();
  const out: string[] = [];
  let lower: number | null = null;
  for (const b of def.bands || []) {
    const range =
      b.upto == null
        ? lower == null
          ? `any ${field}`
          : `above ${unit}${lower}`
        : lower == null
          ? `up to ${unit}${b.upto}`
          : `${unit}${lower}–${unit}${b.upto}`;
    out.push(`${range} → ${OUTCOME_WORD[b.outcome] || b.outcome}${b.approver_role ? ` (${b.approver_role})` : ""}`);
    lower = b.upto ?? lower;
  }
  return out;
}

const EXAMPLE =
  "Refunds up to $100 can be issued automatically. Refunds between $100 and $1000 require approval from a finance manager.";

/**
 * Write a rule the way it is written in a policy document. It compiles to an
 * executable rule (shown back in plain terms), or to a specific question when the
 * wording leaves something open. Added rules start watching.
 */
export function DescribeRule({ agent, tools = [], agents = [] }: { agent?: string; tools?: string[]; agents?: ScopeAgent[] }) {
  const router = useRouter();
  // Who the rule applies to: the agent it was opened for by default, or every agent.
  const choices = agent && !agents.some((a) => a.slug === agent) ? [{ slug: agent, name: agent }, ...agents] : agents;
  const [scope, setScope] = useState(defaultRuleScope(agent, choices));
  const [names, setNames] = useState<Record<string, string>>({});
  const [text, setText] = useState("");
  // The tool the limit is for, picked from the agent's own: no code names to remember.
  const [tool, setTool] = useState("");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [added, setAdded] = useState<string[]>([]);

  const compile = async (source: string = text) => {
    setBusy(true);
    setError("");
    try {
      setResult(await callJson("/api/business/compile", "POST", { text: source, agent: scope || agent, tool: tool || undefined }));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const add = async (rule: any) => {
    setBusy(true);
    setError("");
    try {
      // The name the person typed, else one said from the bands: never the slug.
      const name = (names[rule.key] ?? "").trim() || suggestedLadderName(rule.definition);
      await callJson("/api/business/rules", "POST", { definition: { ...rule.definition, name }, agent: scope || undefined });
      setAdded([...added, rule.key]);
      router.refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="k-form">
      <div className="k-field">
        <label htmlFor="dr-text">The rule, in a sentence or two</label>
        <div className="k-form" style={{ gap: 4 }}>
          <textarea
            id="dr-text"
            className="k-input"
            rows={4}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={EXAMPLE}
          />
          <p className="k-help">
            Write it as your policy document would: a tool, an amount and who approves above it. Preview shows the limit it
            becomes before anything is saved; a saved rule starts by watching.
          </p>
        </div>
      </div>
      {tools.length > 0 && (
        <div className="k-field">
          <label htmlFor="dr-tool">Tool it limits</label>
          <select
            id="dr-tool"
            className="k-select"
            style={{ maxWidth: 360 }}
            value={tool}
            disabled={busy}
            onChange={(e) => {
              setTool(e.target.value);
              setResult(null);
            }}
          >
            <option value="">Work it out from the sentence</option>
            {tools.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
      )}
      {choices.length > 0 && <AgentScope agents={choices} value={scope} onChange={(v) => { setScope(v); setResult(null); }} disabled={busy} id="dr-scope" />}
      <div className="k-pills" style={{ gap: 8 }}>
        <button className={result ? "k-btn" : "k-btn-primary"} disabled={busy || !text.trim()} onClick={() => compile()}>
          {busy && !result ? "Reading…" : "Preview"}
        </button>
        {!text && (
          <button className="k-btn-ghost" onClick={() => setText(EXAMPLE)}>
            Use an example
          </button>
        )}
      </div>
      {error && <div className="error" role="alert">{error}</div>}

      {result && (
        <div className="k-form">
          {result.rules?.map((r: any) => (
            <div key={r.key} className="k-preview" style={{ maxWidth: "none" }}>
              <div className="k-preview-head">
                <strong>{r.kind === "threshold_ladder" ? suggestedLadderName(r.definition) : businessRuleName({ key: r.key, name: r.definition.name, tool: r.definition.tool, kind: r.kind })}</strong>
                {r.definition.tool && !String(r.definition.name || "").includes(r.definition.tool) && r.kind !== "threshold_ladder" && (
                  <span className="k-muted k-mono"> · {r.definition.tool}</span>
                )}
              </div>
              {r.kind === "threshold_ladder" ? (
                <ul className="k-plain">
                  {bandsText(r.definition).map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              ) : (
                <span className="k-muted">{r.kind.replace(/_/g, " ")}</span>
              )}
              {r.warnings?.map((w: string) => (
                <span key={w} className="k-pill k-pill-warn" style={{ alignSelf: "flex-start", whiteSpace: "normal" }}>
                  {w}
                </span>
              ))}
              {r.assumptions?.length > 0 && (
                <span className="k-muted" style={{ fontSize: "var(--t-micro)" }}>
                  Assumed: {r.assumptions.map((a: any) => a.what).join("; ")}
                </span>
              )}
              <div>
                {added.includes(r.key) ? (
                  <span className="k-pills" style={{ gap: 8 }}>
                    <span className="k-pill k-pill-ok">Added · watching</span>
                    <Link className="k-btn" href="/app/policies?tab=libraries&open=custom">
                      Start blocking in Your rules
                    </Link>
                  </span>
                ) : r.kind === "threshold_ladder" ? (
                  <div className="k-pills" style={{ gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
                    <div className="k-field" style={{ flex: 1, minWidth: 240 }}>
                      <label htmlFor={`dr-name-${r.key}`}>Name</label>
                      <input
                        id={`dr-name-${r.key}`}
                        className="k-input"
                        style={{ minWidth: 360 }}
                        maxLength={200}
                        value={names[r.key] ?? suggestedLadderName(r.definition)}
                        onChange={(e) => setNames({ ...names, [r.key]: e.target.value })}
                      />
                    </div>
                    <button className="k-btn-primary" disabled={busy} onClick={() => add(r)}>
                      Save rule
                    </button>
                  </div>
                ) : (
                  <span className="k-muted">This kind of rule is added from its own screen.</span>
                )}
              </div>
            </div>
          ))}
          {result.review?.map((q: any, i: number) => (
            <div key={i} className="k-preview" style={{ maxWidth: "none" }}>
              <strong>{q.question}</strong>
              <span className="k-muted">“{q.source}”</span>
              {toolSubject(q.question) && tools.length > 0 ? (
                <div className="k-pills" style={{ gap: 6, flexWrap: "wrap" }}>
                  {tools.map((t) => (
                    <button
                      key={t}
                      className="k-btn k-mono"
                      disabled={busy}
                      onClick={() => {
                        const next = text.replace(new RegExp(escape(toolSubject(q.question)!), "gi"), t);
                        setText(next);
                        compile(next);
                      }}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              ) : (
                <>
                  {q.options?.length > 0 && <span className="k-muted">Options: {q.options.join(" · ")}</span>}
                  <span className="k-muted" style={{ fontSize: "var(--t-micro)" }}>Reword the sentence above to answer it, then preview again.</span>
                </>
              )}
            </div>
          ))}
          {/* A sentence that became the allow band was used, even if the compiler says it ignored it. */}
          {unusedSentences(result.ignored || [], result.rules || []).length > 0 && (
            <div className="k-muted" style={{ fontSize: "var(--t-micro)" }}>
              Not used: {unusedSentences(result.ignored || [], result.rules || []).map((x: string) => `“${x}”`).join(" ")}
            </div>
          )}
          {!result.rules?.length && !result.review?.length && (
            <div className="k-muted">No rule found in that text. Try naming an amount, a tool, or who must approve.</div>
          )}
        </div>
      )}
    </div>
  );
}

/** "Which tool handles compensation?" → "compensation": the word to replace with a tool. */
function toolSubject(question: string): string | null {
  const m = /^Which tool handles (.+?)\?$/i.exec(question || "");
  return m ? m[1] : null;
}

function escape(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
