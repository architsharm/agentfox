"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";
import { TryIt, type AgentTool } from "@/components/product/test/TryIt";

type Protection = {
  key: string;
  title: string;
  level: string;
  inherited: string | null;
  inherited_mode: string | null;
  graded: boolean;
  needs: string | null;
  needs_installed?: boolean;
  default: string;
};

export type ProtectionState = {
  agent: string;
  /** Display name; the slug when the agent has none. */
  name?: string;
  mode: string | null;
  message: string;
  levels: Record<string, number>;
  protections: Protection[];
  words: string[];
  avoid: string;
  allowed: string;
};

const STEPS = ["Protections", "Words & topics", "Message", "Review", "Test"] as const;
const GRADES = ["off", "low", "medium", "high"];
const LABEL: Record<string, string> = { off: "Off", on: "On", low: "Low", medium: "Medium", high: "High" };
const RANK: Record<string, number> = { off: 0, low: 1, on: 1, medium: 2, high: 3 };

/**
 * Protect one agent, start to finish: what to stop and how strictly, its own words
 * and topics, what its users are told, a replay of its last week, then a live test.
 * Everything new starts watching.
 */
export function ProtectWizard({
  initial,
  tools,
}: {
  initial: ProtectionState;
  tools: AgentTool[];
}) {
  const router = useRouter();
  const fresh = initial.protections.every((p) => p.level === "off");
  const [step, setStep] = useState(0);
  const [choices, setChoices] = useState<Record<string, string>>(() =>
    Object.fromEntries(initial.protections.map((p) => [p.key, fresh ? startLevel(p) : p.level])),
  );
  const [words, setWords] = useState(initial.words.join("\n"));
  const [avoid, setAvoid] = useState(initial.avoid);
  const [allowed, setAllowed] = useState(initial.allowed);
  const [message, setMessage] = useState(initial.message);
  const [preview, setPreview] = useState<any>(null);
  const [saved, setSaved] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const payload = () => ({
    protections: choices,
    message,
    words: words.split(/\n|,/).map((w) => w.trim()).filter(Boolean),
    avoid,
    allowed,
  });
  const base = `/api/agents/${encodeURIComponent(initial.agent)}/protection`;

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

  const go = (i: number) => {
    setStep(i);
    if (STEPS[i] === "Review" && !saved) run(async () => setPreview(await callJson(`${base}/preview`, "POST", payload())));
  };

  const save = () =>
    run(async () => {
      setSaved(await callJson(base, "POST", payload()));
      router.refresh();
      setStep(STEPS.indexOf("Test"));
    });

  return (
    <div className="k-form">
      <ol className="k-steps" aria-label="Steps">
        {STEPS.map((s, i) => (
          <li key={s}>
            <button
              className={i === step ? "active" : i < step ? "done" : ""}
              aria-current={i === step ? "step" : undefined}
              disabled={busy || (s === "Test" && !saved)}
              onClick={() => go(i)}
            >
              <span className="k-step-n">{i + 1}</span>
              {s}
            </button>
          </li>
        ))}
      </ol>

      {STEPS[step] === "Protections" && (
        <>
        <p className="k-muted" style={{ margin: "0 0 8px" }}>
          Low stops only clear-cut cases. High catches more, and flags more by mistake. Everything starts by watching, so
          you can see what it would stop before it stops anything.
        </p>
        <table className="k-table">
          <tbody>
            {initial.protections.map((p) => {
              const options = p.graded ? GRADES : ["off", "on"];
              const floor = p.inherited ? RANK[p.inherited] : 0;
              return (
                <tr key={p.key}>
                  <td>
                    <span className="k-name">{p.title}</span>
                    {p.inherited && (
                      <span className="sub">
                        Workspace default: {LABEL[p.inherited]}{p.inherited_mode === "enforce" ? "" : ", watching"}
                      </span>
                    )}
                    {p.needs && p.needs_installed === false && choices[p.key] !== "off" && <span className="sub">Model not installed here</span>}
                  </td>
                  <td className="tight">
                    <div className="k-seg" role="group" aria-label={p.title}>
                      {options.map((o) => (
                        <button
                          key={o}
                          className={choices[p.key] === o ? "active" : ""}
                          title={o !== "off" && RANK[o] < floor ? "Already stricter for every agent" : undefined}
                          onClick={() => setChoices({ ...choices, [p.key]: o })}
                        >
                          {LABEL[o]}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        </>
      )}

      {STEPS[step] === "Words & topics" && (
        <>
          <div className="k-field">
            <label htmlFor="pw-words">Block these words</label>
            <textarea id="pw-words" className="k-input" rows={3} value={words} onChange={(e) => setWords(e.target.value)} placeholder={"Competitor names\nInternal project names"} />
          </div>
          <div className="k-field">
            <label htmlFor="pw-avoid">Topics to avoid</label>
            <input id="pw-avoid" className="k-input" value={avoid} onChange={(e) => setAvoid(e.target.value)} placeholder="Legal advice, medical diagnosis" />
          </div>
          <div className="k-field">
            <label htmlFor="pw-allowed">Only answer about</label>
            <input id="pw-allowed" className="k-input" value={allowed} onChange={(e) => setAllowed(e.target.value)} placeholder="Orders, shipping, returns (empty: anything)" />
          </div>
        </>
      )}

      {STEPS[step] === "Message" && (
        <div className="k-field">
          <label htmlFor="pw-msg">When something is blocked, tell the user</label>
          <input id="pw-msg" className="k-input" maxLength={500} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Sorry, I can't help with that. A teammate will follow up." />
        </div>
      )}

      {STEPS[step] === "Review" && (
        <>
          {!saved && busy && !preview && <div className="k-muted">Replaying the last 7 days…</div>}
          {preview && (
            <div className="k-preview" style={{ maxWidth: "none" }}>
              <div className="k-preview-head">
                <strong>Last 7 days for {initial.name || initial.agent}</strong>
                <span className="k-muted"> · {preview.runs_replayed ?? preview.replayed} requests replayed</span>
              </div>
              <div className="k-preview-nums">
                <span>
                  <strong>{preview.runs_would_stop ?? preview.counts?.would_stop ?? 0}</strong> would have been stopped or held once enforcing
                </span>
              </div>
              {(payload().words.length > 0 || avoid.trim() || allowed.trim()) && (
                <p className="k-muted" style={{ margin: "6px 0 0" }}>
                  Blocked words and topics apply to new messages from now on; past traffic was never checked for them, so they are not in this number.
                </p>
              )}
            </div>
          )}
          <ul className="k-plain">
            {initial.protections
              .filter((p) => choices[p.key] !== "off")
              .map((p) => (
                <li key={p.key}>
                  {p.title}: {LABEL[choices[p.key]]}
                </li>
              ))}
            {payload().words.length > 0 && <li>Blocked words: {payload().words.length}</li>}
            {avoid && <li>Avoids: {avoid}</li>}
            {allowed && <li>Only: {allowed}</li>}
            {message && <li>Message: “{message}”</li>}
          </ul>
          <div className="k-pills" style={{ gap: 8 }}>
            <button className="k-btn-primary" disabled={busy} onClick={save}>
              {busy && preview ? "Saving…" : initial.mode === "enforce" ? "Save" : "Save · watching"}
            </button>
          </div>
        </>
      )}

      {STEPS[step] === "Test" && saved && (
        <>
          <div className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
            <span className="k-pill k-pill-ok">Saved · {saved.policy.mode === "enforce" ? "enforcing" : "watching"}</span>
            {saved.not_installed?.length > 0 && <span className="k-pill k-pill-warn">Model not installed: {saved.not_installed.join(", ")}</span>}
            <Link className="k-btn" href={`/app/policies/agent.${encodeURIComponent(initial.agent)}`}>
              Open policy
            </Link>
          </div>
          <TryIt agents={[{ slug: initial.agent }]} tools={tools} />
          {saved.policy.mode !== "enforce" && (
            <p className="k-muted" style={{ marginTop: 12 }}>
              These protections are watching: they record what they would stop. When that looks right,{" "}
              <Link href={`/app/start?agent=${encodeURIComponent(initial.agent)}`}>turn enforcement on</Link> from Get started.
            </p>
          )}
        </>
      )}

      {error && <div className="error">{error}</div>}

      {step < STEPS.indexOf("Review") && (
        <div className="k-pills" style={{ gap: 8 }}>
          {step > 0 && (
            <button className="k-btn-ghost" onClick={() => go(step - 1)}>
              Back
            </button>
          )}
          <button className="k-btn-primary" onClick={() => go(step + 1)}>
            Next
          </button>
        </div>
      )}
    </div>
  );
}

/** First-run choice: the protection's default, never below what every agent already gets. */
function startLevel(p: Protection): string {
  // A protection whose model is not installed here would check nothing.
  if (p.needs && p.needs_installed === false) return "off";
  if (!p.graded) return p.default === "off" && !p.inherited ? "off" : "on";
  if (p.inherited && RANK[p.inherited] > RANK[p.default]) return p.inherited;
  return p.default;
}
