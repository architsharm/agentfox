"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";

const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60) || "access-check";

const list = (s: string) =>
  s
    .split(/[\n,]/)
    .map((x) => x.trim())
    .filter(Boolean);

/** Ask an access check about one example call: who, which tool. */
export function AccessCheckTest({ checkKey, tool }: { checkKey: string; tool: string }) {
  const [open, setOpen] = useState(false);
  const [subject, setSubject] = useState("");
  const [groups, setGroups] = useState("");
  const [toolKey, setToolKey] = useState(tool.includes("*") ? "" : tool);
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
      <input className="k-input" placeholder="End user (subject)" value={subject} onChange={(e) => setSubject(e.target.value)} />
      <input className="k-input" placeholder="Groups (optional, comma separated)" value={groups} onChange={(e) => setGroups(e.target.value)} />
      <input className="k-input k-mono" placeholder="Tool, e.g. refunds.issue" value={toolKey} onChange={(e) => setToolKey(e.target.value)} />
      <div className="k-pills" style={{ gap: 6 }}>
        <button
          type="button"
          className="k-btn"
          disabled={busy || !subject.trim() || !toolKey.trim()}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              setOut(
                await callJson(`/api/authorizers/${encodeURIComponent(checkKey)}/test`, "POST", {
                  subject: subject.trim(),
                  groups: list(groups),
                  tool: toolKey.trim(),
                }),
              );
            } catch (e: any) {
              setError(e.message || "Failed");
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "…" : "Ask"}
        </button>
        <button type="button" className="k-btn-ghost" onClick={() => setOpen(false)}>
          Close
        </button>
      </div>
      {out &&
        (out.ok ? (
          <span className={out.allowed ? "k-muted" : "k-act-error"}>
            {out.allowed ? "Allowed" : "Denied"}
            {out.reason ? `: ${out.reason}` : ""}
          </span>
        ) : (
          <span className="k-act-error">
            Could not reach it: {out.error}. {out.fail_mode === "closed" ? "Calls would be refused." : "Calls would go through."}
          </span>
        ))}
      {error && <span className="k-act-error">{error}</span>}
    </div>
  );
}

/**
 * Register the service that decides what each end user may do: your RBAC API, an
 * OPA or Cedar server. Matching tool calls are posted to it, with the end user,
 * before they run.
 */
export function AccessCheckForm() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [tools, setTools] = useState("*");
  const [agents, setAgents] = useState("");
  const [onDeny, setOnDeny] = useState<"block" | "escalate">("block");
  const [failMode, setFailMode] = useState<"closed" | "open">("closed");
  const [requirePrincipal, setRequirePrincipal] = useState(false);
  const [cache, setCache] = useState("60");
  const [timeout, setTimeoutMs] = useState("800");
  const [header, setHeader] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!open)
    return (
      <button type="button" className="k-btn" onClick={() => setOpen(true)}>
        Add an access check
      </button>
    );

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await callJson("/api/authorizers", "POST", {
        key: slug(name),
        name: name.trim(),
        url: url.trim(),
        tools: list(tools).length ? list(tools) : ["*"],
        agents: list(agents),
        on_deny: onDeny,
        fail_mode: failMode,
        require_principal: requirePrincipal,
        cache_seconds: Number(cache),
        timeout_ms: Number(timeout),
        auth_header: header.trim(),
        ...(secret ? { auth_secret: secret } : {}),
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
        <label htmlFor="ac-name">Name</label>
        <input id="ac-name" className="k-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Corporate RBAC" />
      </div>
      <div className="k-field">
        <label htmlFor="ac-url">Endpoint URL</label>
        <input id="ac-url" className="k-input k-mono" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://rbac.internal/v1/data/agents/allow" />
      </div>
      <div className="k-field">
        <label htmlFor="ac-tools">Tools it decides</label>
        <input id="ac-tools" className="k-input k-mono" value={tools} onChange={(e) => setTools(e.target.value)} placeholder="refunds.*, crm.update" />
      </div>
      <div className="k-field">
        <label htmlFor="ac-agents">Agents</label>
        <input id="ac-agents" className="k-input k-mono" value={agents} onChange={(e) => setAgents(e.target.value)} placeholder="All agents (or list slugs)" />
      </div>
      <div className="k-field">
        <label>When it says no</label>
        <div className="k-seg" role="group" aria-label="When it says no">
          <button type="button" className={onDeny === "block" ? "active" : ""} onClick={() => setOnDeny("block")}>
            Block the call
          </button>
          <button type="button" className={onDeny === "escalate" ? "active" : ""} onClick={() => setOnDeny("escalate")}>
            Ask a person
          </button>
        </div>
      </div>
      <div className="k-field">
        <label>If it is down</label>
        <div className="k-seg" role="group" aria-label="If it is down">
          <button type="button" className={failMode === "closed" ? "active" : ""} onClick={() => setFailMode("closed")}>
            Refuse the call
          </button>
          <button type="button" className={failMode === "open" ? "active" : ""} onClick={() => setFailMode("open")}>
            Let it through
          </button>
        </div>
      </div>
      <div className="k-field">
        <label htmlFor="ac-req">No end user named</label>
        <label className="k-check">
          <input id="ac-req" type="checkbox" checked={requirePrincipal} onChange={(e) => setRequirePrincipal(e.target.checked)} />
          Refuse the call (otherwise it is not asked)
        </label>
      </div>
      <div className="k-field">
        <label htmlFor="ac-cache">Remember answers (s)</label>
        <input id="ac-cache" className="k-input" type="number" min={0} max={3600} value={cache} onChange={(e) => setCache(e.target.value)} style={{ width: 120 }} />
      </div>
      <div className="k-field">
        <label htmlFor="ac-timeout">Timeout (ms)</label>
        <input id="ac-timeout" className="k-input" type="number" min={50} max={3000} step={50} value={timeout} onChange={(e) => setTimeoutMs(e.target.value)} style={{ width: 120 }} />
      </div>
      <div className="k-field">
        <label htmlFor="ac-header">Auth header</label>
        <input id="ac-header" className="k-input k-mono" value={header} onChange={(e) => setHeader(e.target.value)} placeholder="Authorization (optional)" />
      </div>
      {header.trim() && (
        <div className="k-field">
          <label htmlFor="ac-secret">Header value</label>
          <input id="ac-secret" className="k-input" type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="Stored encrypted" />
        </div>
      )}
      <div className="k-pills" style={{ gap: 8 }}>
        <button type="button" className="k-btn-primary" disabled={busy || !name.trim() || !url.trim()} onClick={save}>
          {busy ? "…" : "Save access check"}
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
