"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";

type Status = "translated" | "translated_with_note" | "untranslatable";

type Item = {
  source: string;
  status: Status;
  source_effect: string;
  effect: string;
  document: string;
  rules: string[];
  notes: string[];
  reason: string;
  condition: string;
  file: string;
  line: number | null;
  skippable: boolean;
};

type DefaultAction = { document: string; source: string; effect: string; unmatched_pass: boolean; note: string };

type LintFinding = { code: string; severity: string; rule_id: string; message: string };

export type PolicyPlan = {
  format: string;
  items: Item[];
  errors: string[];
  notes: string[];
  schema_errors: { path: string; message: string }[];
  default_action: DefaultAction[];
  unmatched_pass: boolean;
  patterns: { key: string }[];
  documents: { key: string; rules: unknown[] }[];
  summary: Record<Status, number>;
  lint: { findings: LintFinding[]; passed: boolean };
};

const STATUS: Record<Status, { label: string; pill: string }> = {
  translated: { label: "Translated", pill: "k-pill k-pill-ok" },
  translated_with_note: { label: "With a note", pill: "k-pill k-pill-info" },
  untranslatable: { label: "Not translated", pill: "k-pill k-pill-warn" },
};

const EFFECT_LABEL: Record<string, string> = { block: "Block", escalate: "Hold for a person", allow: "Record only" };

const EXAMPLE = `apiVersion: governance.toolkit/v1
name: support-agent
default_action: deny
rules:
  - name: allow-reads
    condition: "tool_name startswith 'read_'"
    action: allow
  - name: big-refunds-need-approval
    condition: "amount > 500 and tool_name == 'refund'"
    action: require_approval
  - name: owner-only
    condition: "user.id == resource.owner"
    action: deny`;

const n = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

/** Splits uploaded files into the policy itself and the Rego files it names. */
async function readUploads(list: FileList): Promise<{ source?: string; files: Record<string, string> }> {
  const files: Record<string, string> = {};
  let source: string | undefined;
  for (const file of Array.from(list)) {
    const text = await file.text();
    const path = (file as any).webkitRelativePath || file.name;
    if (path.endsWith(".rego")) files[path.split("/").slice(-1)[0]] = text;
    else if (/\.(ya?ml|json)$/.test(path) && source === undefined) source = text;
  }
  return { source, files };
}

/**
 * Paste or upload an agent-governance rule file or policy manifest (with its .rego
 * files), see what every rule becomes, untick anything, import in observe.
 */
export function ImportPolicyFormat() {
  const router = useRouter();
  const [source, setSource] = useState("");
  const [files, setFiles] = useState<Record<string, string>>({});
  const [plan, setPlan] = useState<PolicyPlan | null>(null);
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
      setPlan(await callJson("/api/import/agent-governance/plan", "POST", { source, files }));
      setSkip([]);
      setDone(null);
    });

  const apply = () =>
    run(async () => {
      setDone(await callJson("/api/import/agent-governance", "POST", { source, files, skip }));
      router.refresh();
    });

  const upload = (list: FileList | null) =>
    list &&
    run(async () => {
      const got = await readUploads(list);
      if (got.source !== undefined) setSource(got.source);
      setFiles((prev) => ({ ...prev, ...got.files }));
      setPlan(null);
    });

  const reset = () => {
    setDone(null);
    setPlan(null);
    setSource("");
    setFiles({});
  };

  if (done)
    return (
      <div className="k-form">
        <div className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
          <span className="k-pill k-pill-ok">Imported</span>
          {done.policies.map((p: any) => (
            <span key={p.key} className="k-pill">
              {p.key} · v{p.version} · {p.mode === "enforce" ? "enforcing (new version waits)" : "watching"}
            </span>
          ))}
          {done.patterns.length > 0 && <span className="k-pill">{n(done.patterns.length, "text pattern")}</span>}
          {done.untranslatable.length > 0 && <span className="k-pill k-pill-warn">{n(done.untranslatable.length, "rule")} not translated</span>}
        </div>
        <p className="muted">Imported policies watch and record. Simulate them on recorded traffic before you turn enforcement on.</p>
        <div className="k-pills" style={{ gap: 8 }}>
          <a className="k-btn" href="/app/policies">
            See policies
          </a>
          <button className="k-btn-ghost" onClick={reset}>
            Import another
          </button>
        </div>
      </div>
    );

  const fileNames = Object.keys(files);
  const translated = plan ? plan.items.filter((it) => it.status !== "untranslatable") : [];

  return (
    <div className="k-form">
      <textarea
        className="k-input k-mono"
        rows={10}
        value={source}
        onChange={(e) => {
          setSource(e.target.value);
          setPlan(null);
        }}
        placeholder={EXAMPLE}
        aria-label="Agent governance YAML or policy manifest"
      />
      <div className="k-pills" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <label className="k-btn-ghost" style={{ cursor: "pointer" }}>
          Upload files
          <input
            type="file"
            multiple
            accept=".yaml,.yml,.json,.rego"
            style={{ display: "none" }}
            aria-label="Upload a policy file and its .rego files"
            onChange={(e) => upload(e.target.files)}
          />
        </label>
        {fileNames.length > 0 && (
          <span className="muted">
            {n(fileNames.length, "Rego file")}: {fileNames.slice(0, 4).join(", ")}
            {fileNames.length > 4 ? " …" : ""}{" "}
            <button className="k-btn-ghost" onClick={() => { setFiles({}); setPlan(null); }}>
              Clear
            </button>
          </span>
        )}
      </div>
      <p className="muted" style={{ margin: 0 }}>
        Rule YAML with <code>default_action</code> and <code>rules</code>, or a policy manifest (<code>agent_control_specification_version</code>) with its .rego files. Nothing is
        run, and imported policies only watch.
      </p>
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
      {plan?.errors.map((e) => (
        <div key={e} className="error">
          {e}
        </div>
      ))}
      {plan && plan.schema_errors.length > 0 && (
        <table className="k-table" aria-label="Schema problems">
          <tbody>
            {plan.schema_errors.map((e, i) => (
              <tr key={i}>
                <td className="tight k-mono">{e.path}</td>
                <td>{e.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {plan && plan.items.length > 0 && (
        <>
          {plan.default_action.map((d) => (
            <div key={d.document} className="k-pills" style={{ gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
              <span className={d.unmatched_pass ? "k-pill k-pill-warn" : "k-pill"}>
                {d.unmatched_pass ? "Unmatched calls pass" : "Unmatched calls are blocked"}
              </span>
              <span className={d.unmatched_pass ? "" : "muted"}>{d.note}</span>
            </div>
          ))}
          <div className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
            <span className="k-pill k-pill-ok">{plan.summary.translated} translated</span>
            <span className="k-pill k-pill-info">{plan.summary.translated_with_note} with a note</span>
            <span className="k-pill k-pill-warn">{plan.summary.untranslatable} not translated</span>
            {plan.patterns.length > 0 && <span className="k-pill">{n(plan.patterns.length, "text pattern")} become custom rules</span>}
            <span className={plan.lint.passed ? "k-pill k-pill-ok" : "k-pill k-pill-bad"}>
              {plan.lint.findings.length === 0 ? "Lint clean" : n(plan.lint.findings.length, "lint finding")}
            </span>
          </div>
          <table className="k-table">
            <tbody>
              {plan.items.map((it, i) => {
                const off = it.status === "untranslatable" || !it.skippable;
                return (
                  <tr key={i} className={it.status === "untranslatable" ? "muted" : ""}>
                    <td className="tight">
                      <input
                        type="checkbox"
                        aria-label={`Import ${it.source}`}
                        disabled={off}
                        checked={it.status !== "untranslatable" && !skip.includes(i)}
                        onChange={(e) => setSkip(e.target.checked ? skip.filter((x) => x !== i) : [...skip, i])}
                      />
                    </td>
                    <td>
                      <span className="k-name k-mono">{it.source}</span>
                      <span className="sub">{it.status === "untranslatable" ? it.reason : it.notes.join(" · ") || it.condition}</span>
                    </td>
                    <td className="tight">
                      <span className={STATUS[it.status].pill}>{STATUS[it.status].label}</span>
                    </td>
                    <td className="tight muted">{it.effect ? EFFECT_LABEL[it.effect] || it.effect : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {plan.lint.findings.length > 0 && (
            <ul className="muted">
              {plan.lint.findings.map((f, i) => (
                <li key={i}>
                  <span className="k-mono">{f.rule_id}</span> — {f.message}
                </li>
              ))}
            </ul>
          )}
          {plan.notes.map((note) => (
            <p key={note} className="muted" style={{ margin: 0 }}>
              {note}
            </p>
          ))}
          <div>
            <button
              className="k-btn-primary"
              disabled={busy || translated.length === 0 || translated.every((it) => skip.includes(plan.items.indexOf(it)))}
              onClick={apply}
            >
              {busy ? "Importing…" : "Import, watching"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
