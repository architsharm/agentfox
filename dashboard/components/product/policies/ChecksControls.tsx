"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { callJson } from "@/components/kit/Act";

type Job = { id: string; status: string; last_error?: string | null; result?: any } | null;

/**
 * Download an open-source detector's model on the gateway. The download runs as a
 * background job; while it does, the page refreshes itself to show when it is done.
 */
export function PullButton({ detectorKey, job, blocked }: { detectorKey: string; job: Job; blocked: string | null }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const running = job && (job.status === "pending" || job.status === "running");

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => router.refresh(), 3000);
    return () => clearInterval(t);
  }, [running, router]);

  if (blocked)
    return (
      <span className="k-muted" title={blocked}>
        <code className="k-mono">agentfox admin detectors pull {detectorKey}</code>
      </span>
    );
  if (running) return <span className="k-muted">Downloading…</span>;
  if (job?.status === "done")
    return <span className="k-muted" title="Restart the gateway so it loads the model.">Downloaded. Restart to load</span>;

  return (
    <span className="k-act">
      <button
        type="button"
        className="k-btn"
        disabled={busy}
        title={job?.status === "dead" ? job.last_error || undefined : undefined}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            await callJson(`/api/detectors/${encodeURIComponent(detectorKey)}/pull`, "POST");
            router.refresh();
          } catch (e: any) {
            setError(e.message || "Failed");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "…" : job?.status === "dead" ? "Retry download" : "Download"}
      </button>
      {error && (
        <span className="k-act-error" role="alert">
          {error}
        </span>
      )}
    </span>
  );
}

export type PostureDoc = { tiers: string[]; pii_egress: string; backend: string; fail_closed: boolean };

/**
 * Turn one judgment tier on or off. Sends the whole posture with that one tier
 * changed, with a reason, and, for a tier that sends text off this server, an
 * explicit confirmation.
 */
export function TierSwitch({ tier, on, sendsData, posture }: { tier: string; on: boolean; sendsData: boolean; posture: PostureDoc }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const widening = !on && sendsData;

  if (!open)
    return (
      <button type="button" className={on ? "k-btn" : "k-btn-primary"} onClick={() => setOpen(true)}>
        {on ? "Turn off" : "Turn on"}
      </button>
    );

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const tiers = on ? posture.tiers.filter((t) => t !== tier) : Array.from(new Set([...posture.tiers, tier]));
      await callJson("/api/judgment/posture", "PUT", { ...posture, tiers, reason, confirm_egress: confirm });
      setOpen(false);
      router.refresh();
    } catch (e: any) {
      setError(e.message || "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="k-form" style={{ minWidth: 240, gap: 8 }}>
      <input className="k-input" placeholder="Why (recorded in the audit log)" value={reason} onChange={(e) => setReason(e.target.value)} />
      {widening && (
        <label className="k-check">
          <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
          Send checked text to this provider
        </label>
      )}
      <div className="k-pills" style={{ gap: 6 }}>
        <button type="button" className="k-btn-primary" disabled={busy || !reason.trim() || (widening && !confirm)} onClick={save}>
          {busy ? "…" : on ? "Turn off" : "Turn on"}
        </button>
        <button type="button" className="k-btn-ghost" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {error && (
        <span className="k-act-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

/** Send one sample to a registered model and show what it would report. */
export function ModelTest({ modelKey, surface }: { modelKey: string; surface: string }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState<any>(null);
  const [error, setError] = useState("");
  if (!open)
    return (
      <button type="button" className="k-btn-ghost" onClick={() => setOpen(true)}>
        Test
      </button>
    );
  return (
    <div className="k-form" style={{ minWidth: 260, gap: 8 }}>
      <input className="k-input" placeholder="Sample text" value={text} onChange={(e) => setText(e.target.value)} />
      <div className="k-pills" style={{ gap: 6 }}>
        <button
          type="button"
          className="k-btn"
          disabled={busy || !text.trim()}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              setOut(await callJson(`/api/custom-models/${encodeURIComponent(modelKey)}/test`, "POST", { text, surface }));
            } catch (e: any) {
              setError(e.message || "Failed");
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "…" : "Send"}
        </button>
        <button type="button" className="k-btn-ghost" onClick={() => setOpen(false)}>
          Close
        </button>
      </div>
      {out &&
        (out.ok ? (
          <span className="k-muted">
            {out.detections.length
              ? `Would report ${out.detections.map((d: any) => `${d.entity_type} (${Number(d.score).toFixed(2)})`).join(", ")}`
              : `Nothing to report. Labels: ${out.labels.map((l: any) => `${l.label} ${Number(l.score).toFixed(2)}`).join(", ") || "none"}`}
          </span>
        ) : (
          <span className="k-act-error">{out.error}</span>
        ))}
      {error && <span className="k-act-error">{error}</span>}
    </div>
  );
}

const WHERE: { key: string; label: string }[] = [
  { key: "input", label: "User messages" },
  { key: "output", label: "Agent replies" },
  { key: "tool_args", label: "Tool calls" },
  { key: "tool_result", label: "Tool results" },
  { key: "retrieved", label: "Retrieved content" },
];

const PREFIX_LABEL: Record<string, string> = {
  CUSTOM: "Its own rule",
  INJECTION: "Prompt attack (INJECTION)",
  PII: "Personal data (PII)",
  SECRET: "Secret (SECRET)",
  SAFETY: "Harmful content (SAFETY)",
  TOPIC: "Off topic (TOPIC)",
  BRAND: "Brand (BRAND)",
  GROUNDING: "Wrong answer (GROUNDING)",
};

const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60) || "model";

/**
 * Register a classifier you run yourself: a fine-tuned or RL-trained model behind an
 * HTTP endpoint. It receives `{"text", "inputs", "surface"}` and answers with labels
 * and scores; labels above the threshold become detections your rules act on.
 */
export function ModelForm({ prefixes }: { prefixes: string[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [where, setWhere] = useState<string[]>(["input"]);
  const [prefix, setPrefix] = useState("CUSTOM");
  const [labels, setLabels] = useState("");
  const [threshold, setThreshold] = useState("0.5");
  const [timeout, setTimeoutMs] = useState("800");
  const [failMode, setFailMode] = useState<"open" | "closed">("open");
  const [header, setHeader] = useState("");
  const [secret, setSecret] = useState("");
  const [effect, setEffect] = useState("allow");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!open)
    return (
      <button type="button" className="k-btn" onClick={() => setOpen(true)}>
        Add a model
      </button>
    );

  const labelMap = Object.fromEntries(
    labels
      .split(/\n|,/)
      .map((l) => l.split("=").map((x) => x.trim()))
      .filter(([k]) => k)
      .map(([k, v]) => [k, v ?? k]),
  );

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await callJson("/api/custom-models", "POST", {
        key: slug(name),
        name: name.trim(),
        url: url.trim(),
        surfaces: where,
        labels: labelMap,
        entity_prefix: prefix,
        threshold: Number(threshold),
        timeout_ms: Number(timeout),
        fail_mode: failMode,
        auth_header: header.trim(),
        ...(secret ? { auth_secret: secret } : {}),
        effect,
      });
      setOpen(false);
      setName("");
      setUrl("");
      setSecret("");
      router.refresh();
    } catch (e: any) {
      setError(e.message || "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="k-form" style={{ padding: 16 }}>
      <div className="k-field">
        <label htmlFor="cm-name">Name</label>
        <input id="cm-name" className="k-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Fraud classifier" />
      </div>
      <div className="k-field">
        <label htmlFor="cm-url">Endpoint URL</label>
        <input id="cm-url" className="k-input k-mono" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://models.internal/classify" />
      </div>
      <div className="k-field">
        <label>Checks</label>
        <div className="k-pills" style={{ gap: 12, flexWrap: "wrap" }}>
          {WHERE.map((w) => (
            <label key={w.key} className="k-check">
              <input
                type="checkbox"
                checked={where.includes(w.key)}
                onChange={(e) => setWhere(e.target.checked ? [...where, w.key] : where.filter((x) => x !== w.key))}
              />
              {w.label}
            </label>
          ))}
        </div>
      </div>
      <div className="k-field">
        <label htmlFor="cm-prefix">Report as</label>
        <select id="cm-prefix" className="k-select" value={prefix} onChange={(e) => setPrefix(e.target.value)}>
          {(prefixes.length ? prefixes : ["CUSTOM"]).map((p) => (
            <option key={p} value={p}>
              {PREFIX_LABEL[p] || p}
            </option>
          ))}
        </select>
      </div>
      {prefix === "CUSTOM" && (
        <div className="k-field">
          <label htmlFor="cm-effect">When it fires</label>
          <select id="cm-effect" className="k-select" value={effect} onChange={(e) => setEffect(e.target.value)}>
            <option value="allow">Log only</option>
            <option value="escalate">Ask a human</option>
            <option value="block">Block</option>
          </select>
        </div>
      )}
      <div className="k-field">
        <label htmlFor="cm-labels">Labels</label>
        <textarea
          id="cm-labels"
          className="k-input k-mono"
          rows={3}
          value={labels}
          onChange={(e) => setLabels(e.target.value)}
          placeholder={"jailbreak = JAILBREAK\nLABEL_1 = FRAUD\n(blank: any label except benign/safe)"}
        />
      </div>
      <div className="k-field">
        <label htmlFor="cm-threshold">Threshold</label>
        <input id="cm-threshold" className="k-input" type="number" min={0} max={1} step={0.05} value={threshold} onChange={(e) => setThreshold(e.target.value)} />
      </div>
      <div className="k-field">
        <label htmlFor="cm-timeout">Timeout (ms)</label>
        <input id="cm-timeout" className="k-input" type="number" min={50} max={2000} step={50} value={timeout} onChange={(e) => setTimeoutMs(e.target.value)} />
      </div>
      <div className="k-field">
        <label>If it is down</label>
        <div className="k-seg" role="group" aria-label="If it is down">
          <button type="button" className={failMode === "open" ? "active" : ""} onClick={() => setFailMode("open")}>
            Let traffic through
          </button>
          <button type="button" className={failMode === "closed" ? "active" : ""} onClick={() => setFailMode("closed")}>
            Treat as a hit
          </button>
        </div>
      </div>
      <div className="k-field">
        <label htmlFor="cm-header">Auth header</label>
        <input id="cm-header" className="k-input k-mono" value={header} onChange={(e) => setHeader(e.target.value)} placeholder="Authorization (optional)" />
      </div>
      {header.trim() && (
        <div className="k-field">
          <label htmlFor="cm-secret">Header value</label>
          <input id="cm-secret" className="k-input" type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="Stored encrypted" />
        </div>
      )}
      <div className="k-pills" style={{ gap: 8 }}>
        <button type="button" className="k-btn-primary" disabled={busy || !name.trim() || !url.trim() || !where.length} onClick={save}>
          {busy ? "…" : "Save model"}
        </button>
        <button type="button" className="k-btn-ghost" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
