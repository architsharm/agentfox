"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";

type Item = { kind: string; key: string; change: string; detail: string };
type Plan = { items: Item[]; counts: Record<string, number>; enforces: string[]; simulations?: Record<string, any> };

const CHANGE: Record<string, { label: string; tone: string }> = {
  new: { label: "New", tone: "ok" },
  changed: { label: "Changed", tone: "warn" },
  mode: { label: "Mode", tone: "warn" },
};

/**
 * Every policy, custom rule and detector switch as one YAML file: download it to keep
 * in git, or paste one back to see exactly what it would change, then apply.
 */
export function WorkspaceCode({ source }: { source: string }) {
  const router = useRouter();
  const [view, setView] = useState<"export" | "apply">("export");
  const [text, setText] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [done, setDone] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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

  const download = () => {
    const url = URL.createObjectURL(new Blob([source], { type: "text/yaml" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "agentfox.yaml" });
    a.click();
    URL.revokeObjectURL(url);
  };

  const changes = plan?.items.filter((i) => ["new", "changed", "mode"].includes(i.change)) || [];
  const leftAlone = plan?.items.filter((i) => i.change === "not_in_file").length || 0;

  return (
    <div className="k-form">
      <div className="k-seg" role="tablist" aria-label="Export or apply">
        <button role="tab" aria-selected={view === "export"} className={view === "export" ? "active" : ""} onClick={() => setView("export")}>
          Export
        </button>
        <button role="tab" aria-selected={view === "apply"} className={view === "apply" ? "active" : ""} onClick={() => setView("apply")}>
          Apply a file
        </button>
      </div>

      {view === "export" && (
        <>
          <div className="k-pills" style={{ gap: 8 }}>
            <button className="k-btn-primary" onClick={download}>
              Download agentfox.yaml
            </button>
            <button className="k-btn-ghost" onClick={() => navigator.clipboard?.writeText(source)}>
              Copy
            </button>
          </div>
          <pre className="k-code" aria-label="Workspace file">{source}</pre>
        </>
      )}

      {view === "apply" && (
        <>
          <textarea
            className="k-input k-mono"
            rows={10}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setPlan(null);
              setDone(null);
            }}
            placeholder="kind: agentfox/workspace"
            aria-label="Workspace file to apply"
          />
          <div className="k-pills" style={{ gap: 8 }}>
            <button className="k-btn-primary" disabled={busy || !text.trim()} onClick={() => run(async () => setPlan(await callJson("/api/workspace/plan", "POST", { source: text })))}>
              {busy && !plan ? "Reading…" : "Show changes"}
            </button>
          </div>
          {plan && !done && (
            <>
              {changes.length ? (
                <table className="k-table">
                  <tbody>
                    {changes.map((i) => (
                      <tr key={`${i.kind}:${i.key}`}>
                        <td className="tight">
                          <span className={`k-pill${CHANGE[i.change]?.tone ? ` k-pill-${CHANGE[i.change].tone}` : ""}`}>{CHANGE[i.change]?.label || i.change}</span>
                        </td>
                        <td>
                          <span className="k-name k-mono">{i.key}</span>
                          <span className="sub">{i.kind.replace("_", " ")}</span>
                        </td>
                        <td className="muted">{i.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : null}
              {leftAlone > 0 && <span className="k-muted">{leftAlone} not in the file, left alone</span>}
              {changes.length ? (
                <div className="k-pills" style={{ gap: 8 }}>
                  <button className="k-btn-primary" disabled={busy} onClick={() => run(async () => { setDone(await callJson("/api/workspace/apply", "POST", { source: text })); router.refresh(); })}>
                    {busy ? "Applying…" : plan.enforces.length ? `Apply · enforces ${plan.enforces.join(", ")}` : "Apply"}
                  </button>
                </div>
              ) : (
                <span className="k-pill k-pill-ok" style={{ alignSelf: "flex-start" }}>Nothing to change</span>
              )}
            </>
          )}
          {done && (
            <span className="k-pill k-pill-ok" style={{ alignSelf: "flex-start" }}>
              Applied
              {Object.keys(done.simulations || {}).length > 0 && ` · simulated ${Object.keys(done.simulations || {}).join(", ")}`}
            </span>
          )}
        </>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
