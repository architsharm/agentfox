"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Play, Plus, Search, X } from "lucide-react";

/**
 * The project's attack test, in the map's panel when nothing is selected: one row per
 * attack set (name and what it tries; the result on the right), a "+" to add sets
 * from the library, and Run.
 *
 * The first test runs by itself when `agentfox init` connects the project, with no
 * guardrails. Then one click adds the basic guardrails and tests again; each row shows
 * before → after. Everything else is set up from the map.
 */

type ByType = { type: string; label: string; total: number; done: number; gotThrough: number };
type Run = {
  id: string;
  status: "running" | "done" | "failed";
  phase: "before" | "after";
  total: number;
  byType: ByType[];
  waitingForRunner: boolean;
  error: string | null;
};
type LibrarySet = { key: string; name: string; description: string; attacks: number };
type Tests = {
  first: Run | null;
  withBasic: Run | null;
  basicOn: boolean;
  connectedProject: string | null;
  sets: string[];
  library: LibrarySet[];
};

const POLL_MS = 1500;

async function send(url: string, method = "GET", body?: unknown): Promise<any> {
  const res = await fetch(url, {
    method,
    cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || data?.error || `Something went wrong (${res.status}).`);
  return data;
}

const of = (run: Run | null | undefined, type: string) => run?.byType.find((t) => t.type === type);

/** The right-hand side of a row: how many got through, before → with basic guardrails. */
function Result({ before, after, live }: { before?: ByType; after?: ByType; live?: ByType }) {
  if (live && live.done < live.total) {
    return (
      <span className="at-r at-r-live">
        {live.done}/{live.total}
      </span>
    );
  }
  const n = (t: ByType) => (
    <b className={t.gotThrough ? "at-bad" : "at-good"} title={`${t.gotThrough} of ${t.total} got through`}>
      {t.gotThrough}/{t.total}
    </b>
  );
  if (!before && !after) return <span className="at-r at-r-none">—</span>;
  return (
    <span className="at-r">
      {before ? n(before) : null}
      {before && after ? <span className="at-arrow">→</span> : null}
      {after ? n(after) : null}
    </span>
  );
}

function Library({ items, onAdd, onClose }: { items: LibrarySet[]; onAdd: (key: string) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const away = (e: MouseEvent) => !box.current?.contains(e.target as globalThis.Node) && onClose();
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [onClose]);
  const shown = items.filter((x) => `${x.name} ${x.description}`.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <div className="at-lib" ref={box} role="dialog" aria-label="Add attack sets">
      <label className="at-lib-search">
        <Search size={13} aria-hidden />
        <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the attack library" />
      </label>
      {shown.length ? (
        <ul>
          {shown.map((x) => (
            <li key={x.key}>
              <button type="button" onClick={() => onAdd(x.key)}>
                <span>
                  <strong>{x.name}</strong>
                  <em>{x.description}</em>
                </span>
                <span className="at-lib-n">{x.attacks}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="gm-sub">{items.length ? "Nothing matches." : "Every set in the library is already added."}</p>
      )}
    </div>
  );
}

export function AttackTests({ project }: { project: string }) {
  const router = useRouter();
  const [tests, setTests] = useState<Tests | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const base = `/api/onboarding/projects/${encodeURIComponent(project)}`;

  const load = useCallback(async () => {
    try {
      setTests(await send(`${base}/tests`));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [base]);

  const live = tests?.first?.status === "running" ? tests.first : tests?.withBasic?.status === "running" ? tests.withBasic : null;
  useEffect(() => {
    load();
  }, [load]);
  // Watch while a test runs, and while the first one is still to start.
  useEffect(() => {
    if (!live && tests?.first) return;
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [live, tests?.first, load]);

  const act = async (fn: () => Promise<unknown>, refresh = false) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
      if (refresh) router.refresh(); // the map's rails show the new guardrails
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const run = () => act(() => send(`${base}/tests`, "POST"));
  const addBasic = () =>
    act(async () => {
      await send(`${base}/basic-guardrails`, "POST");
      await send(`${base}/tests`, "POST"); // straight into the second run: the difference is the point
    }, true);
  const setSets = (sets: string[]) => act(() => send(`${base}/tests/sets`, "PUT", { sets }));

  const library = useMemo(() => tests?.library ?? [], [tests?.library]);
  if (!tests) {
    return (
      <section className="at">
        <h4 className="at-title">Attack test</h4>
        <p className="gm-sub">{error ?? "Loading…"}</p>
      </section>
    );
  }
  const { first, withBasic, basicOn, sets } = tests;
  const here = tests.connectedProject === project;
  const done = withBasic?.status === "done" ? withBasic : null;
  const rows = sets.map((key) => library.find((x) => x.key === key)).filter((x): x is LibrarySet => Boolean(x));
  const rest = library.filter((x) => !sets.includes(x.key));
  const failed = live ? null : [withBasic, first].find((r) => r?.status === "failed") ?? null;

  return (
    <section className="at" aria-label="Attack test">
      <div className="at-head">
        <h4 className="at-title">Attack test</h4>
        <div className="at-actions">
          <button
            type="button"
            className="at-icon"
            onClick={run}
            disabled={busy || !here || Boolean(live)}
            title={here ? "Run the test" : "Run agentfox init in this project's repository to test it"}
            aria-label="Run the test"
          >
            <Play size={13} aria-hidden />
          </button>
          <button type="button" className="at-icon" onClick={() => setAdding((v) => !v)} title="Add from the library" aria-label="Add attack sets">
            <Plus size={14} aria-hidden />
          </button>
        </div>
        {adding ? (
          <Library
            items={rest}
            onClose={() => setAdding(false)}
            onAdd={(key) => {
              setAdding(false);
              setSets([...sets, key]);
            }}
          />
        ) : null}
      </div>

      {live ? (
        <div className="at-bar" role="progressbar" aria-valuemin={0} aria-valuemax={live.total} aria-valuenow={live.byType.reduce((n, t) => n + t.done, 0)}>
          <i style={{ width: `${live.total ? (live.byType.reduce((n, t) => n + t.done, 0) / live.total) * 100 : 0}%` }} />
        </div>
      ) : null}
      {live?.waitingForRunner && live.byType.every((t) => t.done === 0) ? (
        <p className="gm-sub">Waiting for agentfox init on your machine…</p>
      ) : null}

      <ul className="at-rows">
        {rows.map((x) => (
          <li key={x.key}>
            <div className="at-row-text">
              <strong>{x.name}</strong>
              <span>{x.description}</span>
            </div>
            <Result before={of(first, x.key)} after={of(done, x.key)} live={of(live, x.key)} />
            {sets.length > 1 ? (
              <button type="button" className="at-remove" onClick={() => setSets(sets.filter((k) => k !== x.key))} aria-label={`Remove ${x.name}`} title="Remove">
                <X size={12} aria-hidden />
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {first && done ? <p className="at-legend">got through: no guardrails → basic guardrails</p> : null}

      {!first && !here ? (
        <p className="gm-sub">
          Run <code>agentfox init</code> in this project&apos;s repository; the test starts by itself.
        </p>
      ) : null}
      {failed ? <p className="at-error">{failed.error || "The test couldn't reach your agent."}</p> : null}

      {first?.status === "done" && !basicOn ? (
        <div className="at-next">
          <div>
            <strong>Add basic guardrails</strong>
            <p>Blocks attacks in what users send; hides personal data and secrets in replies. Nothing on tools.</p>
          </div>
          <button type="button" className="at-btn" onClick={addBasic} disabled={busy || !here}>
            Add and test again
          </button>
        </div>
      ) : null}
      {error ? <p className="at-error">{error}</p> : null}
    </section>
  );
}
