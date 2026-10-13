"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";

/** Connect, test or disconnect this workspace's Slack channel for alerts. */
export function SlackForm({ configured, minSeverity }: { configured: boolean; minSeverity?: string | null }) {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [severity, setSeverity] = useState(minSeverity || "medium");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const run = async (fn: () => Promise<any>, ok: string) => {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await fn();
      setMsg(ok);
      router.refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="k-form">
      <div className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
        <input
          className="k-input"
          style={{ minWidth: 340 }}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={configured ? "Connected · paste a new webhook to replace" : "https://hooks.slack.com/services/…"}
          aria-label="Slack webhook URL"
        />
        <select className="k-select" value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label="Minimum severity">
          <option value="low">Low and above</option>
          <option value="medium">Medium and above</option>
          <option value="high">High and above</option>
          <option value="critical">Critical only</option>
        </select>
        <button className="k-btn-primary" disabled={busy || !url.trim()} onClick={() => run(() => callJson("/api/alerts/slack", "POST", { url, min_severity: severity }), "Saved")}>
          Save
        </button>
        {configured && (
          <>
            <button className="k-btn" disabled={busy} onClick={() => run(() => callJson("/api/alerts/slack/test", "POST"), "Test sent")}>
              Send test
            </button>
            <button className="k-btn-ghost" disabled={busy} onClick={() => window.confirm("Stop sending alerts to Slack?") && run(() => callJson("/api/alerts/slack", "DELETE"), "Disconnected")}>
              Disconnect
            </button>
          </>
        )}
      </div>
      {msg && <span className="k-muted">{msg}</span>}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
