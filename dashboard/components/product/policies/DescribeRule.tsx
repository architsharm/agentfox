"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";

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
export function DescribeRule({ agent }: { agent?: string }) {
  const router = useRouter();
  const [text, setText] = useState("");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [added, setAdded] = useState<string[]>([]);

  const compile = async () => {
    setBusy(true);
    setError("");
    try {
      setResult(await callJson("/api/business/compile", "POST", { text }));
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
      await callJson("/api/business/rules", "POST", { definition: rule.definition, agent });
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
      <textarea
        className="k-input"
        rows={4}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={EXAMPLE}
        aria-label="Describe the rule"
      />
      <div className="k-pills" style={{ gap: 8 }}>
        <button className="k-btn-primary" disabled={busy || !text.trim()} onClick={compile}>
          {busy && !result ? "Reading…" : "Create rule"}
        </button>
        {!text && (
          <button className="k-btn-ghost" onClick={() => setText(EXAMPLE)}>
            Use an example
          </button>
        )}
      </div>
      {error && <div className="error">{error}</div>}

      {result && (
        <div className="k-form">
          {result.rules?.map((r: any) => (
            <div key={r.key} className="k-preview" style={{ maxWidth: "none" }}>
              <div className="k-preview-head">
                <strong>{r.definition.name || r.definition.tool || r.key}</strong>
                {r.definition.tool && <span className="k-muted k-mono"> · {r.definition.tool}</span>}
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
              {r.assumptions?.length > 0 && (
                <span className="k-muted" style={{ fontSize: "var(--t-micro)" }}>
                  Assumed: {r.assumptions.map((a: any) => a.what).join("; ")}
                </span>
              )}
              <div>
                {added.includes(r.key) ? (
                  <span className="k-pill k-pill-ok">Added · watching</span>
                ) : r.kind === "threshold_ladder" ? (
                  <button className="k-btn-primary" disabled={busy} onClick={() => add(r)}>
                    Add rule
                  </button>
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
              {q.options?.length > 0 && <span className="k-muted">Options: {q.options.join(" · ")}</span>}
              <span className="k-muted" style={{ fontSize: "var(--t-micro)" }}>Reword the sentence above to answer it, then create again.</span>
            </div>
          ))}
          {result.ignored?.length > 0 && (
            <div className="k-muted" style={{ fontSize: "var(--t-micro)" }}>
              Not used: {result.ignored.map((x: string) => `“${x}”`).join(" ")}
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
