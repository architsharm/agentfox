import Link from "next/link";
import type { ReactNode } from "react";
import { InfoTip } from "@/components/ui/InfoTip";
import { ACTIONS, IMPACT, MODES, OUTCOMES, type Outcome } from "@/lib/product/vocab";

/**
 * The dashboard's building blocks. Every signed-in page is made of these, so a
 * number, a status or a list looks and behaves the same everywhere: every number
 * that has records behind it is a link to them, every status uses one of the
 * pills below, and explanations live in a hover tip rather than on the page.
 */

// --- Formatting --------------------------------------------------------------

export function num(n?: number | null): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (Math.abs(n) >= 10_000) return `${Math.round(n / 1000)}k`;
  if (Math.abs(n) >= 1_000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(Math.round(n * 100) / 100);
}

export function pctOf(part: number, whole: number): string {
  if (!whole) return "0%";
  const v = (part / whole) * 100;
  return `${v < 1 && v > 0 ? v.toFixed(1) : Math.round(v)}%`;
}

export function money(n?: number | null): string {
  if (!n) return "$0";
  if (n >= 0.01) return `$${n.toFixed(2)}`;
  // Two significant figures below a cent: a request costs fractions of one.
  return `$${n.toPrecision(2).replace(/0+$/, "").replace(/\.$/, "")}`;
}

export function ago(iso?: string | null): string {
  if (!iso) return "—";
  const s = (Date.now() - Date.parse(iso)) / 1000;
  if (Number.isNaN(s)) return "—";
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d ago`;
  return iso.slice(0, 10);
}

export function when(iso?: string | null): string {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 16);
}

/** Build a URL from a base path and params, dropping empty ones. */
export function href(path: string, params: Record<string, string | number | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `${path}?${s}` : path;
}

// --- Page frame --------------------------------------------------------------

export function Header({
  title,
  hint,
  meta,
  actions,
  back,
}: {
  title: ReactNode;
  hint?: string;
  meta?: ReactNode;
  actions?: ReactNode;
  back?: { href: string; label: string };
}) {
  return (
    <header className="k-head">
      {back && (
        <Link href={back.href} className="k-back">
          ← {back.label}
        </Link>
      )}
      <div className="k-head-row">
        <div className="k-head-title">
          <h1>{title}</h1>
          {hint && <InfoTip text={hint} />}
          {meta && <div className="k-head-meta">{meta}</div>}
        </div>
        {actions && <div className="k-head-actions">{actions}</div>}
      </div>
    </header>
  );
}

export type TabItem = { key: string; label: string; href: string; count?: number | null };

export function Tabs({ items, active }: { items: TabItem[]; active: string }) {
  return (
    <nav className="tabbar k-tabs" aria-label="Sections">
      {items.map((t) => (
        <Link
          key={t.key}
          href={t.href}
          className={t.key === active ? "active" : ""}
          aria-current={t.key === active ? "page" : undefined}
        >
          {t.label}
          {t.count ? <span className="tab-count">{num(t.count)}</span> : null}
        </Link>
      ))}
    </nav>
  );
}

export function Grid({ cols = 2, children }: { cols?: 2 | 3 | 4 | 5 | 6; children: ReactNode }) {
  return <div className={`k-grid k-grid-${cols}`}>{children}</div>;
}

export function Card({
  title,
  hint,
  action,
  children,
  flush,
}: {
  title?: ReactNode;
  hint?: string;
  action?: ReactNode;
  children: ReactNode;
  /** Content runs to the card's edges (tables). */
  flush?: boolean;
}) {
  return (
    <section className={`k-card${flush ? " k-flush" : ""}`}>
      {(title || action) && (
        <div className="k-card-head">
          <h3>
            {title}
            {hint && <InfoTip text={hint} />}
          </h3>
          {action && <div className="k-card-action">{action}</div>}
        </div>
      )}
      <div className="k-card-body">{children}</div>
    </section>
  );
}

export function Empty({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="k-empty">
      <span>{children}</span>
      {action}
    </div>
  );
}

export function Meta({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="k-meta">
      {items.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

// --- Numbers -----------------------------------------------------------------

export function Kpi({
  label,
  value,
  prev,
  current,
  better = "down",
  href: link,
  spark,
  tone,
  hint,
}: {
  label: string;
  value: ReactNode;
  /** Previous period's value, for the change arrow. */
  prev?: number;
  /** This period's raw value, when `value` is formatted. */
  current?: number;
  /** Which direction is good news. */
  better?: "up" | "down" | "none";
  href?: string;
  spark?: number[];
  tone?: "bad" | "warn" | "ok";
  hint?: string;
}) {
  let delta: ReactNode = null;
  if (prev !== undefined && current !== undefined) {
    if (prev === 0 && current === 0) delta = <span className="k-delta">—</span>;
    else if (prev === 0) delta = <span className="k-delta">new</span>;
    else {
      const change = ((current - prev) / prev) * 100;
      const up = change > 0;
      const good = better === "none" ? null : (better === "up") === up;
      delta = (
        <span className={`k-delta ${good === null ? "" : good ? "good" : "bad"}`}>
          {up ? "▲" : "▼"} {Math.abs(Math.round(change))}%
        </span>
      );
    }
  }
  const body = (
    <>
      <div className="k-kpi-label">
        {label}
        {hint && <InfoTip text={hint} />}
      </div>
      <div className={`k-kpi-value${tone ? ` ${tone}` : ""}`}>{value}</div>
      <div className="k-kpi-foot">
        {delta}
        {spark && spark.length > 1 && <Sparkline values={spark} />}
      </div>
    </>
  );
  return link ? (
    <Link href={link} className="k-kpi k-kpi-link">
      {body}
    </Link>
  ) : (
    <div className="k-kpi">{body}</div>
  );
}

export function Sparkline({ values, width = 72, height = 22 }: { values: number[]; width?: number; height?: number }) {
  const max = Math.max(1, ...values);
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(height - 2 - (v / max) * (height - 4)).toFixed(1)}`);
  return (
    <svg className="k-spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <polyline points={pts.join(" ")} />
    </svg>
  );
}

// --- Status ------------------------------------------------------------------

export type Tone = "neutral" | "ok" | "warn" | "held" | "bad" | "info" | "outline";

export function Pill({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`k-pill k-pill-${tone}`} title={title}>
      {children}
    </span>
  );
}

const OUTCOME_TONE: Record<Outcome, Tone> = { allowed: "neutral", masked: "info", held: "held", blocked: "bad" };

export function OutcomePill({ outcome }: { outcome: Outcome }) {
  return <Pill tone={OUTCOME_TONE[outcome]}>{OUTCOMES.find((o) => o.key === outcome)?.label}</Pill>;
}

export function ActionPill({ effect }: { effect?: string | null }) {
  const tone: Tone =
    effect === "block" ? "bad" : effect === "escalate" ? "held" : effect === "allow" ? "neutral" : "info";
  return <Pill tone={tone}>{ACTIONS[effect || ""] || effect || "—"}</Pill>;
}

export function ModePill({ mode }: { mode?: string | null }) {
  if (!mode) return <Pill tone="outline">Off</Pill>;
  return <Pill tone={mode === "enforce" ? "ok" : "outline"}>{MODES[mode] || mode}</Pill>;
}

export function SeverityPill({ value }: { value?: string | null }) {
  const tone: Tone = value === "critical" ? "bad" : value === "high" ? "held" : value === "medium" ? "warn" : "neutral";
  return <Pill tone={tone}>{value || "—"}</Pill>;
}

export function ImpactPill({ impact }: { impact?: string | null }) {
  const tone: Tone = impact === "irreversible" ? "bad" : impact === "high_impact" ? "held" : impact === "write" ? "warn" : "neutral";
  return <Pill tone={tone}>{IMPACT[impact || ""] || impact || "Unknown"}</Pill>;
}

export function Dot({ tone }: { tone: "ok" | "warn" | "bad" | "idle" }) {
  return <span className={`k-dot k-dot-${tone}`} aria-hidden />;
}

// --- Charts ------------------------------------------------------------------

type Segments = { allowed?: number; masked?: number; held?: number; blocked?: number };

/** One horizontal bar split into passed / held / blocked. */
export function StackBar({ s, total, scale }: { s: Segments; total: number; scale: number }) {
  const passed = (s.allowed || 0) + (s.masked || 0);
  const w = (n: number) => `${scale ? (n / scale) * 100 : 0}%`;
  return (
    <span className="k-stack" aria-hidden>
      {passed > 0 && <span className="k-seg-passed" style={{ width: w(passed) }} />}
      {(s.held || 0) > 0 && <span className="k-seg-held" style={{ width: w(s.held || 0) }} />}
      {(s.blocked || 0) > 0 && <span className="k-seg-blocked" style={{ width: w(s.blocked || 0) }} />}
      {!total && <span />}
    </span>
  );
}

export type BarRow = {
  key: string;
  label: ReactNode;
  href?: string;
  value: number;
  segments?: Segments;
  note?: ReactNode;
};

/** A ranked list with a proportional bar — the breakdown view everywhere. */
export function BarList({ rows, limit = 8, format = num, empty = "No data" }: {
  rows: BarRow[];
  limit?: number;
  format?: (n: number) => string;
  empty?: string;
}) {
  if (!rows.length) return <Empty>{empty}</Empty>;
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="k-bars">
      {rows.slice(0, limit).map((r) => (
        <li key={r.key}>
          <span className="k-bars-label">
            {r.href ? <Link href={r.href}>{r.label}</Link> : r.label}
            {r.note && <span className="k-bars-note">{r.note}</span>}
          </span>
          {r.segments ? (
            <StackBar s={r.segments} total={r.value} scale={max} />
          ) : (
            <span className="k-stack" aria-hidden>
              <span className="k-seg-solid" style={{ width: `${(r.value / max) * 100}%` }} />
            </span>
          )}
          <span className="k-bars-value">{format(r.value)}</span>
        </li>
      ))}
    </ul>
  );
}

export type Bucket = { t: string; allowed: number; masked: number; held: number; blocked: number; errors?: number };

export const SERIES = [
  { key: "passed", label: "Allowed", cls: "k-fill-passed" },
  { key: "held", label: "Held", cls: "k-fill-held" },
  { key: "blocked", label: "Blocked", cls: "k-fill-blocked" },
] as const;

/**
 * Requests over time, stacked by outcome. Allowed and masked share the grey fill
 * (both went through); held and blocked are the two colours that separate under
 * colour-blindness. Each column links to the runs in that slot.
 */
export function TimeChart({
  buckets,
  bucketSeconds,
  linkFor,
  height = 140,
}: {
  buckets: Bucket[];
  bucketSeconds: number;
  linkFor?: (start: string, end: string) => string;
  height?: number;
}) {
  const W = 720;
  const H = height;
  const gap = buckets.length > 60 ? 1 : 3;
  const barW = (W - gap * (buckets.length - 1)) / Math.max(1, buckets.length);
  const totals = buckets.map((b) => b.allowed + b.masked + b.held + b.blocked);
  const max = Math.max(1, ...totals);
  const sum = { passed: 0, held: 0, blocked: 0 };
  for (const b of buckets) {
    sum.passed += b.allowed + b.masked;
    sum.held += b.held;
    sum.blocked += b.blocked;
  }
  const label = (iso: string) => {
    const d = new Date(iso);
    return bucketSeconds < 86400
      ? d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit" })
      : d.toLocaleDateString([], { month: "short", day: "numeric" });
  };
  const ticks = [0, Math.floor(buckets.length / 2), buckets.length - 1].filter((v, i, a) => a.indexOf(v) === i);

  return (
    <div className="k-chart">
      <ul className="k-legend">
        {SERIES.map((s) => (
          <li key={s.key}>
            <span className={`k-swatch ${s.cls}`} aria-hidden />
            {s.label} <strong>{num(sum[s.key])}</strong>
          </li>
        ))}
      </ul>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${num(sum.passed)} allowed, ${num(sum.held)} held, ${num(sum.blocked)} blocked`}
      >
        <line x1="0" x2={W} y1={H - 0.5} y2={H - 0.5} className="k-axis" vectorEffect="non-scaling-stroke" />
        {buckets.map((b, i) => {
          const x = i * (barW + gap);
          const end = new Date(Date.parse(b.t) + bucketSeconds * 1000).toISOString();
          const parts = [
            { cls: "k-fill-passed", v: b.allowed + b.masked },
            { cls: "k-fill-held", v: b.held },
            { cls: "k-fill-blocked", v: b.blocked },
          ];
          let y = H;
          const rects = parts.map((p) => {
            if (!p.v) return null;
            const h = Math.max(2, (p.v / max) * (H - 6));
            y -= h;
            return <rect key={p.cls} x={x} y={y} width={barW} height={Math.max(1, h - 1.5)} className={p.cls} />;
          });
          const tip = `${label(b.t)} · ${totals[i]} requests · ${b.held} held · ${b.blocked} blocked${b.errors ? ` · ${b.errors} errors` : ""}`;
          const col = (
            <g className="k-col">
              <rect x={x - gap / 2} y={0} width={barW + gap} height={H} className="k-hit">
                <title>{tip}</title>
              </rect>
              {rects}
            </g>
          );
          return linkFor && totals[i] ? (
            <a key={i} href={linkFor(b.t, end)}>
              {col}
            </a>
          ) : (
            <g key={i}>{col}</g>
          );
        })}
      </svg>
      <div className="k-ticks">
        {ticks.map((i) => (
          <span key={i}>{buckets[i] ? label(buckets[i].t) : ""}</span>
        ))}
      </div>
    </div>
  );
}
