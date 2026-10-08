"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";
import { ACTION_CHOICES } from "@/lib/product/vocab";

type Item = {
  source: string;
  kind: "custom_rule" | "detector" | "pack" | "skipped";
  target: string;
  title: string;
  note: string;
  effect: string;
  installed?: boolean;
  already?: boolean;
};

type Plan = { items: Item[]; errors: string[]; summary: Record<string, number> };

const KIND_LABEL: Record<Item["kind"], string> = {
  custom_rule: "Your rule",
  detector: "Detector",
  pack: "Pack",
  skipped: "Not imported",
};

const n = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

const EXAMPLE = `guard = Guard().use_many(
    CompetitorCheck(["Globex", "Initech"], on_fail="exception"),
    ToxicLanguage(threshold=0.5, on_fail="exception"),
    DetectPII(["EMAIL_ADDRESS", "PHONE_NUMBER"], on_fail="fix"),
)`;

/**
 * Paste a Guardrails AI guard (Python, .rail or guard.to_dict()), see what each
 * validator becomes here, untick anything, import. Nothing is run; packs arrive
 * watching.
 */
export function ImportGuard() {
  const router = useRouter();
  const [source, setSource] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [skip, setSkip] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<any>(null);

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

  const read = () =>
    run(async () => {
      const p: Plan = await callJson("/api/import/guardrails-ai/plan", "POST", { source });
      setPlan(p);
      setSkip(p.items.map((it, i) => (it.kind === "detector" && it.installed === false ? i : -1)).filter((i) => i >= 0));
      setDone(null);
    });

  const apply = () =>
    run(async () => {
      setDone(await callJson("/api/import/guardrails-ai", "POST", { source, skip }));
      router.refresh();
    });

  if (done)
    return (
      <div className="k-form">
        <div className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
          <span className="k-pill k-pill-ok">Imported</span>
          {done.rules.length > 0 && <span className="k-pill">{n(done.rules.length, "rule")}</span>}
          {done.detectors.length > 0 && <span className="k-pill">{n(done.detectors.length, "detector")} on</span>}
          {Object.keys(done.packs).length > 0 && <span className="k-pill">{n(Object.keys(done.packs).length, "pack")} · watching</span>}
          {done.not_installed.length > 0 && <span className="k-pill k-pill-warn">{n(done.not_installed.length, "detector")} not installed</span>}
        </div>
        <div className="k-pills" style={{ gap: 8 }}>
          <a className="k-btn" href="/app/policies">
            See rules
          </a>
          <button className="k-btn-ghost" onClick={() => { setDone(null); setPlan(null); setSource(""); }}>
            Import another
          </button>
        </div>
      </div>
    );

  return (
    <div className="k-form">
      <textarea
        className="k-input k-mono"
        rows={8}
        value={source}
        onChange={(e) => { setSource(e.target.value); setPlan(null); }}
        placeholder={EXAMPLE}
        aria-label="Guardrails AI guard"
      />
      <div className="k-pills" style={{ gap: 8 }}>
        <button className="k-btn-primary" disabled={busy || !source.trim()} onClick={read}>
          {busy && !plan ? "Reading…" : "Preview import"}
        </button>
        {!source && (
          <button className="k-btn-ghost" onClick={() => setSource(EXAMPLE)}>
            Use an example
          </button>
        )}
      </div>
      {error && <div className="error">{error}</div>}
      {plan?.errors.map((e) => <div key={e} className="error">{e}</div>)}

      {plan && plan.items.length > 0 && (
        <>
          <table className="k-table">
            <tbody>
              {plan.items.map((it, i) => {
                const off = it.kind === "skipped" || (it.kind === "detector" && it.installed === false);
                return (
                  <tr key={i} className={off ? "muted" : ""}>
                    <td className="tight">
                      <input
                        type="checkbox"
                        aria-label={`Import ${it.source}`}
                        disabled={off}
                        checked={!off && !skip.includes(i)}
                        onChange={(e) => setSkip(e.target.checked ? skip.filter((x) => x !== i) : [...skip, i])}
                      />
                    </td>
                    <td>
                      <span className="k-name k-mono">{it.source}</span>
                      <span className="sub">{it.kind === "detector" && it.installed === false ? "Not installed here" : it.note}</span>
                    </td>
                    <td>{it.title || "—"}</td>
                    <td className="tight">
                      <span className={`k-pill${it.kind === "skipped" ? "" : " k-pill-ok"}`}>{KIND_LABEL[it.kind]}</span>
                    </td>
                    <td className="tight muted">{it.kind === "custom_rule" ? ACTION_CHOICES.find((a) => a.effect === it.effect)?.label || it.effect : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div>
            <button
              className="k-btn-primary"
              disabled={busy || plan.items.every((it, i) => it.kind === "skipped" || skip.includes(i))}
              onClick={apply}
            >
              {busy ? "Importing…" : "Import"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
