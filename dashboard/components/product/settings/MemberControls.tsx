"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Pill } from "@/components/kit";
import { CodeSnippet } from "@/components/product/start/CodeSnippet";

async function send(url: string, method: string, body: unknown): Promise<any> {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const out = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof out?.detail === "string" ? out.detail : "Couldn't save that. Try again.");
  return out;
}

/** The add-a-teammate form; shows their sign-in key once it is made. */
export function MemberAdd({ roles }: { roles: string[] }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("developer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [made, setMade] = useState<{ email: string; key: string; days: number } | null>(null);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const out = await send("/api/members", "POST", { email, role });
      setMade({ email: out.member.email, key: out.signInKey, days: out.expiresInDays });
      setEmail("");
      router.refresh();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <form className="gs-row" onSubmit={add}>
        <input className="k-input" type="email" required placeholder="teammate@company.com" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email" />
        <select className="k-select" value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role">
          {roles.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <button type="submit" className="k-btn-primary" disabled={busy}>
          {busy ? "Adding…" : "Add"}
        </button>
      </form>
      {error && (
        <p className="k-error" role="alert">
          {error}
        </p>
      )}
      {made && (
        <div style={{ marginTop: 12 }}>
          <p>
            <b>{made.email} is added.</b> Send them this sign-in key; it&apos;s shown only now and works for {made.days} days. They paste it on the sign-in
            page.
          </p>
          <CodeSnippet code={made.key} />
        </div>
      )}
    </>
  );
}

/** One teammate, for an owner or admin: change the role, deactivate or reactivate (asked in place). */
export function MemberRow({ member, roles }: { member: { id: string; email: string; role: string; active: boolean }; roles: string[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const save = async (body: unknown) => {
    setBusy(true);
    setError("");
    try {
      await send(`/api/members/${encodeURIComponent(member.id)}`, "PATCH", body);
      setConfirming(false);
      router.refresh();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <tr>
      <td>
        <span className="k-name">{member.email}</span>
        {error && (
          <span className="k-error sub" role="alert">
            {error}
          </span>
        )}
      </td>
      <td className="tight">
        <select className="k-select k-select-sm" value={member.role} disabled={busy} onChange={(e) => save({ role: e.target.value })} aria-label={`Role of ${member.email}`}>
          {roles.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </td>
      <td className="tight">{member.active ? <Pill tone="ok">Active</Pill> : <Pill tone="outline">Deactivated</Pill>}</td>
      <td className="tight">
        {!member.active ? (
          <button type="button" className="k-btn-ghost" disabled={busy} onClick={() => save({ active: true })}>
            Reactivate
          </button>
        ) : confirming ? (
          <span className="k-pills" role="alertdialog" aria-label={`Deactivate ${member.email}`}>
            <span className="muted">Their keys stop working.</span>
            <button type="button" className="k-btn-danger" disabled={busy} onClick={() => save({ active: false })}>
              Deactivate
            </button>
            <button type="button" className="k-btn-ghost" onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </span>
        ) : (
          <button type="button" className="k-btn-ghost" onClick={() => setConfirming(true)}>
            Deactivate…
          </button>
        )}
      </td>
    </tr>
  );
}
