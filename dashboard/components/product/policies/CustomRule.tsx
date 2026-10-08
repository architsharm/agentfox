"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";

type Kind = "terms" | "patterns" | "topic" | "allow" | "sequence";

const KINDS: { key: Kind; label: string; placeholder: string }[] = [
  { key: "terms", label: "Words", placeholder: "Globex\nInitech" },
  { key: "patterns", label: "Patterns", placeholder: "ACC-\\d{6}" },
  { key: "topic", label: "Topic to avoid", placeholder: "Medical diagnosis, symptoms, treatment" },
  { key: "allow", label: "Allowed topics", placeholder: "Orders, shipping, returns, billing" },
  { key: "sequence", label: "Sequence", placeholder: "" },
];

const CHECKS: { key: string; label: string }[] = [
  { key: "input", label: "User messages" },
  { key: "output", label: "Agent replies" },
  { key: "tool_args", label: "Tool calls" },
];

const ACTIONS: { effect: string; label: string; only?: Kind[] }[] = [
  { effect: "block", label: "Block" },
  { effect: "escalate", label: "Ask a human" },
  { effect: "redact", label: "Mask", only: ["terms", "patterns"] },
  { effect: "allow", label: "Log only" },
];

const lines = (s: string) =>
  s
    .split(/\n|,/)
    .map((x) => x.trim())
    .filter(Boolean);

const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60) || "rule";

/**
 * A rule in the customer's own terms — words, patterns, a topic, the topics an agent
 * may discuss, or a sequence of tool calls. Try it on a sample before saving. Saved
 * rules join the "Your rules" pack, in that pack's current mode.
 */
export function CustomRule({ agent }: { agent?: string }) {
  const router = useRouter();
  const [kind, setKind] = useState<Kind>("terms");
  const [name, setName] = useState("");
  const [entries, setEntries] = useState("");
  const [examples, setExamples] = useState("");
  const [checks, setChecks] = useState<string[]>(["input", "output"]);
  const [after, setAfter] = useState("");
  const [then, setThen] = useState("");
  const [unlessPath, setUnlessPath] = useState("");
  const [unlessMatches, setUnlessMatches] = useState("");
  const [effect, setEffect] = useState("block");
  const [message, setMessage] = useState("");
  const [reask, setReask] = useState(false);
  const [sample, setSample] = useState("");
  const [tried, setTried] = useState<null | { matched: boolean; matches: any[] }>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<null | { ruleId: string; mode: string }>(null);

  const isTopic = kind === "topic" || kind === "allow";
  const spec = (): Record<string, unknown> => {
    const base = { key: slug(name), name: name.trim() || "Untitled rule", agents: agent ? [agent] : [] };
    if (kind === "sequence")
      return {
        ...base,
        kind: "sequence",
        sequence: { after: after.trim(), then: then.trim(), ...(unlessPath ? { unless_path: unlessPath.trim(), unless_matches: unlessMatches.trim() } : {}) },
      };
    if (isTopic)
      return { ...base, kind: "topic", polarity: kind === "allow" ? "allow" : "deny", description: entries.trim(), examples: lines(examples), surfaces: checks };
    return { ...base, kind, entries: lines(entries), surfaces: checks };
  };

  const pickKind = (k: Kind) => {
    setKind(k);
    setTried(null);
    if (k === "allow") setChecks(["input"]);
    if (effect === "redact" && !["terms", "patterns"].includes(k)) setEffect("block");
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const tryIt = () =>
    run(async () => {
      setTried(await callJson("/api/custom-rules/try", "POST", { rule: spec(), text: sample, surface: checks[0] || "input" }));
    });

  const save = () =>
    run(async () => {
      const out = await callJson("/api/custom-rules", "POST", {
        ...spec(),
        effect,
        message: ["block", "escalate"].includes(effect) ? message.trim() : "",
        on_block: effect === "block" && reask ? "reask" : "refuse",
      });
      setSaved({ ruleId: out.rule.rule_id, mode: out.policy.mode });
      router.refresh();
    });

  if (saved)
    return (
      <div className="k-form">
        <div className="k-pills" style={{ gap: 8 }}>
          <span className="k-pill k-pill-ok">Added · {saved.mode === "enforce" ? "enforcing" : "watching"}</span>
          <Link className="k-btn" href={`/app/policies/rules/${encodeURIComponent(saved.ruleId)}`}>
            Open rule
          </Link>
          <button
            className="k-btn-ghost"
            onClick={() => {
              setSaved(null);
              setName("");
              setEntries("");
              setExamples("");
              setTried(null);
            }}
          >
            Add another
          </button>
        </div>
      </div>
    );

  const first = tried?.matches.find((m) => m.end > m.start);
  const hit = first ? sample.slice(first.start, first.end) : "";
  const ready = name.trim() && (kind === "sequence" ? after.trim() && then.trim() : entries.trim());

  return (
    <div className="k-form">
      <div className="k-seg" role="tablist" aria-label="Kind of rule">
        {KINDS.map((k) => (
          <button key={k.key} role="tab" aria-selected={kind === k.key} className={kind === k.key ? "active" : ""} onClick={() => pickKind(k.key)}>
            {k.label}
          </button>
        ))}
      </div>

      <div className="k-field">
        <label htmlFor="cr-name">Name</label>
        <input id="cr-name" className="k-input" maxLength={200} value={name} onChange={(e) => setName(e.target.value)} placeholder="Competitor mentions" />
      </div>

      {kind === "sequence" ? (
        <>
          <div className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
            <div className="k-field" style={{ flex: 1, minWidth: 180 }}>
              <label htmlFor="cr-after">After a call to</label>
              <input id="cr-after" className="k-input k-mono" value={after} onChange={(e) => setAfter(e.target.value)} placeholder="crm.*" />
            </div>
            <div className="k-field" style={{ flex: 1, minWidth: 180 }}>
              <label htmlFor="cr-then">Stop a call to</label>
              <input id="cr-then" className="k-input k-mono" value={then} onChange={(e) => setThen(e.target.value)} placeholder="email.send" />
            </div>
          </div>
          <div className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
            <div className="k-field" style={{ flex: 1, minWidth: 180 }}>
              <label htmlFor="cr-unless">Unless argument</label>
              <input id="cr-unless" className="k-input k-mono" value={unlessPath} onChange={(e) => setUnlessPath(e.target.value)} placeholder="to" />
            </div>
            <div className="k-field" style={{ flex: 1, minWidth: 180 }}>
              <label htmlFor="cr-matches">matches</label>
              <input id="cr-matches" className="k-input k-mono" value={unlessMatches} onChange={(e) => setUnlessMatches(e.target.value)} placeholder="@yourcompany\.com$" disabled={!unlessPath} />
            </div>
          </div>
        </>
      ) : (
        <>
          <div className="k-field">
            <label htmlFor="cr-entries">{isTopic ? "Topics" : kind === "patterns" ? "Patterns, one per line" : "Words, one per line"}</label>
            <textarea
              id="cr-entries"
              className={`k-input${kind === "patterns" ? " k-mono" : ""}`}
              rows={isTopic ? 2 : 4}
              value={entries}
              onChange={(e) => setEntries(e.target.value)}
              placeholder={KINDS.find((k) => k.key === kind)?.placeholder}
            />
          </div>
          {isTopic && (
            <div className="k-field">
              <label htmlFor="cr-examples">Example questions (optional)</label>
              <textarea id="cr-examples" className="k-input" rows={2} value={examples} onChange={(e) => setExamples(e.target.value)} />
            </div>
          )}
          <div className="k-field">
            <label>Check</label>
            <div className="k-seg" role="group" aria-label="Where to check">
              {CHECKS.map((c) => {
                const on = checks.includes(c.key);
                return (
                  <button key={c.key} className={on ? "active" : ""} aria-pressed={on} onClick={() => setChecks(on ? checks.filter((x) => x !== c.key) : [...checks, c.key])}>
                    {c.label}
                  </button>
                );
              })}
            </div>
          </div>
        </>
      )}

      <div className="k-field">
        <label>When it matches</label>
        <div className="k-seg" role="group" aria-label="Action">
          {ACTIONS.filter((a) => !a.only || a.only.includes(kind)).map((a) => (
            <button key={a.effect} className={effect === a.effect ? "active" : ""} onClick={() => setEffect(a.effect)}>
              {a.label}
            </button>
          ))}
        </div>
      </div>

      {["block", "escalate"].includes(effect) && kind !== "sequence" && (
        <div className="k-field">
          <label htmlFor="cr-message">Message to the user</label>
          <input id="cr-message" className="k-input" maxLength={500} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Sorry, I can't help with that." />
        </div>
      )}

      {effect === "block" && checks.includes("output") && kind !== "sequence" && (
        <label className="k-check">
          <input type="checkbox" checked={reask} onChange={(e) => setReask(e.target.checked)} /> Ask the model to fix a blocked reply
        </label>
      )}

      {kind !== "sequence" && (
        <div className="k-field">
          <label htmlFor="cr-sample">Try it</label>
          <div className="k-pills" style={{ gap: 8 }}>
            <input id="cr-sample" className="k-input" style={{ flex: 1, minWidth: 240 }} value={sample} onChange={(e) => setSample(e.target.value)} placeholder="Paste a message" />
            <button className="k-btn" disabled={busy || !ready || !sample.trim()} onClick={tryIt}>
              Try
            </button>
            {tried && (
              <span className={`k-pill ${tried.matched ? "k-pill-bad" : "k-pill-ok"}`}>
                {tried.matched ? (hit ? `Matches “${hit}”` : "Matches") : "No match"}
              </span>
            )}
          </div>
        </div>
      )}

      {error && <div className="error">{error}</div>}
      <div>
        <button className="k-btn-primary" disabled={busy || !ready} onClick={save}>
          {busy ? "Saving…" : "Add rule"}
        </button>
      </div>
    </div>
  );
}
