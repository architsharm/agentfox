/*
 * Charts for /benchmark.
 *
 * The page had sixteen headings, 4,400 words and six tables, and a reader who
 * came to check one figure had to read a paragraph to find it. Every number
 * below is already in a table on that page and in a results file in the
 * repository; these draw the same numbers so the shape of the result is visible
 * before the prose is read. Nothing here is decorative, and nothing here is a
 * number the tables do not also state.
 *
 * No charting library. Every one of these is a handful of divs or one inline
 * SVG, which is both smaller than a CDN bundle and the only way to get the
 * theme tokens into the marks — a library's default palette would be the one
 * place on the site where a colour was not chosen.
 *
 * Colour is semantic and matches the rest of the site: --mk-good is a call that
 * was allowed or an attack that was contained, --mk-stop is an escape,
 * --mk-hold is a call that stopped for a human.
 */

import type { CSSProperties, ReactNode } from "react";

/* --- Shared frame -------------------------------------------------------- */

/**
 * One figure: a label, the drawing, and the sentence that says what to take from
 * it. The caption is required on purpose — a chart nobody can read a conclusion
 * off is a decoration, and this page cannot afford any.
 */
export function Figure({
  label,
  caption,
  children,
}: {
  label: string;
  caption: ReactNode;
  children: ReactNode;
}) {
  return (
    <figure className="bm-fig">
      <span className="mk-label">{label}</span>
      <div className="bm-fig-body">{children}</div>
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

/* --- 1. Composition of a run --------------------------------------------- */

export type Segment = {
  n: number;
  label: string;
  tone: "good" | "stop" | "hold" | "quiet";
};

const TONE: Record<Segment["tone"], string> = {
  good: "var(--mk-good)",
  stop: "var(--mk-stop)",
  hold: "var(--mk-hold)",
  quiet: "var(--mk-border-strong)",
};

/**
 * A whole, as one bar, to scale.
 *
 * Used for the AgentDojo utility cost: of 97 benign tasks, 24 ran without
 * escalation and 73 were sent to a human. Written as a ratio beside "588 of 588
 * contained", the cost reads as a footnote. Drawn to scale, the reader sees that
 * it is three quarters of the bar.
 */
export function Composition({
  segments,
  unit,
}: {
  segments: Segment[];
  unit: string;
}) {
  const total = segments.reduce((a, s) => a + s.n, 0);
  return (
    <div>
      <div
        className="bm-bar"
        role="img"
        aria-label={segments.map((s) => `${s.n} ${s.label}`).join("; ")}
      >
        {segments.map((s) => (
          <span
            key={s.label}
            className="bm-bar-seg"
            style={{ flex: `${s.n} 0 0`, background: TONE[s.tone] }}
            title={`${s.n} ${s.label}`}
          />
        ))}
      </div>
      <ul className="bm-key">
        {segments.map((s) => (
          <li key={s.label}>
            <i style={{ background: TONE[s.tone] }} aria-hidden />
            <b>{s.n}</b>
            <span>{s.label}</span>
          </li>
        ))}
      </ul>
      <p className="bm-total">
        {total} {unit}
      </p>
    </div>
  );
}

/* --- 2. Ranked bars ------------------------------------------------------- */

export type Bar = {
  label: string;
  /** 0–100. Drawn on a fixed 0–100 axis so two charts on the page compare. */
  value: number;
  display?: string;
  tone?: "good" | "stop" | "hold" | "accent" | "quiet";
  /** Draws the bar hollow, for "this is the one we lose". */
  rival?: boolean;
};

const BAR_TONE: Record<string, string> = {
  good: "var(--mk-good)",
  stop: "var(--mk-stop)",
  hold: "var(--mk-hold)",
  accent: "var(--mk-accent)",
  quiet: "var(--mk-border-strong)",
};

/**
 * Horizontal bars on a fixed 0–100 axis.
 *
 * Fixed rather than fitted to the data, because three of these appear on one
 * page and a reader comparing 66.7% in one with 81.8% in another has to be able
 * to trust that the same width means the same number.
 */
export function Bars({ rows, axis = true }: { rows: Bar[]; axis?: boolean }) {
  return (
    <div className="bm-bars">
      {rows.map((r) => (
        <div key={r.label} className="bm-bars-row">
          <span className="bm-bars-label">{r.label}</span>
          <span className="bm-bars-track">
            <span
              className={r.rival ? "bm-bars-fill bm-bars-fill-rival" : "bm-bars-fill"}
              style={
                {
                  width: `${Math.max(0, Math.min(100, r.value))}%`,
                  "--bar": BAR_TONE[r.tone ?? "accent"],
                } as CSSProperties
              }
            />
          </span>
          <span className="bm-bars-value">{r.display ?? `${r.value}%`}</span>
        </div>
      ))}
      {axis && (
        <div className="bm-bars-axis" aria-hidden>
          <span />
          <span className="bm-bars-axis-ticks">
            <i>0</i>
            <i>50</i>
            <i>100%</i>
          </span>
          <span />
        </div>
      )}
    </div>
  );
}

/* --- 3. Attack success against attempts ---------------------------------- */

export type Series = {
  name: string;
  /** Attack success rate, 0–1, at each x. */
  points: number[];
  tone: "stop" | "hold";
};

/**
 * The adaptive result, which is the one number on this page that is a curve
 * rather than a value: an attacker who reads our verdict and revises gets more
 * through the longer it is allowed to try. The table gives asr@1, @5, @10, @25
 * and @50; the shape between them is the finding, and a table cannot show a
 * shape.
 *
 * The x axis is log-spaced because the attempt budgets are (1, 5, 10, 25, 50) —
 * drawn linearly, four of the five points would sit in the left fifth of the
 * plot and the steep early climb, which is the part that matters, would be
 * invisible.
 */
export function AsrCurve({
  xs,
  series,
}: {
  xs: number[];
  series: Series[];
}) {
  const W = 560;
  const H = 240;
  const PAD = { t: 14, r: 16, b: 34, l: 40 };
  const iw = W - PAD.l - PAD.r;
  const ih = H - PAD.t - PAD.b;
  const lx = (x: number) => Math.log(x);
  const x0 = lx(xs[0]);
  const x1 = lx(xs[xs.length - 1]);
  const px = (x: number) => PAD.l + ((lx(x) - x0) / (x1 - x0)) * iw;
  const py = (v: number) => PAD.t + (1 - v) * ih;
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div className="bm-plot">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Attack success rate against attempts allowed">
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.l}
              x2={W - PAD.r}
              y1={py(t)}
              y2={py(t)}
              stroke="var(--mk-border)"
              strokeWidth="1"
            />
            <text x={PAD.l - 8} y={py(t) + 4} textAnchor="end" className="bm-plot-tick">
              {Math.round(t * 100)}
            </text>
          </g>
        ))}
        {xs.map((x) => (
          <text key={x} x={px(x)} y={H - 12} textAnchor="middle" className="bm-plot-tick">
            {x}
          </text>
        ))}
        <text x={PAD.l + iw / 2} y={H - 0.5} textAnchor="middle" className="bm-plot-axis">
          attempts allowed
        </text>
        {series.map((s, si) => {
          const d = s.points
            .map((v, i) => `${i === 0 ? "M" : "L"}${px(xs[i]).toFixed(1)},${py(v).toFixed(1)}`)
            .join(" ");
          const c = s.tone === "stop" ? "var(--mk-stop)" : "var(--mk-hold)";
          return (
            <g key={s.name}>
              <path d={d} fill="none" stroke={c} strokeWidth="2" strokeLinejoin="round" />
              {s.points.map((v, i) => (
                <circle key={xs[i]} cx={px(xs[i])} cy={py(v)} r="3.5" fill={c} />
              ))}
              {/* The endpoint is the number the home page quotes, so it is labelled
                  on the plot rather than left to the reader to read off an axis. */}
              <text
                x={px(xs[xs.length - 1]) - 6}
                y={py(s.points[s.points.length - 1]) + (si === 0 ? 20 : -12)}
                textAnchor="end"
                className="bm-plot-endpoint"
                fill={c}
              >
                {(s.points[s.points.length - 1] * 100).toFixed(1)}%
              </text>
            </g>
          );
        })}
      </svg>
      <ul className="bm-key">
        {series.map((s) => (
          <li key={s.name}>
            <i
              style={{ background: s.tone === "stop" ? "var(--mk-stop)" : "var(--mk-hold)" }}
              aria-hidden
            />
            <span>{s.name}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* --- 4. Two runs, side by side ------------------------------------------- */

export type ParityRow = { label: string; on: string; off: string; same: boolean };

/**
 * The containment result is "these two columns are identical", and that sentence
 * is the whole finding. A plain table states it; this marks each row as matching
 * or not, so the one row that differs — detector entities, 10 against 0 — is the
 * only thing on the figure drawing attention to itself. That row differing is
 * the proof that the bypass was real rather than assumed.
 */
export function Parity({ rows }: { rows: ParityRow[] }) {
  return (
    <div className="bm-parity">
      <div className="bm-parity-head">
        <span />
        <span className="mk-label">detectors on</span>
        <span className="mk-label">detectors off</span>
        <span />
      </div>
      {rows.map((r) => (
        <div key={r.label} className="bm-parity-row">
          <span className="bm-parity-label">{r.label}</span>
          <b>{r.on}</b>
          <b>{r.off}</b>
          <span className={r.same ? "bm-parity-tag bm-parity-same" : "bm-parity-tag"}>
            {r.same ? "identical" : "the bypass"}
          </span>
        </div>
      ))}
    </div>
  );
}

/* --- 5. Method, folded away ----------------------------------------------- */

/**
 * Every method paragraph this page used to run inline.
 *
 * They are not cut — a benchmark page that hides its method is worth nothing —
 * but they are not in the reading path either. Roughly one reader in twenty
 * wants to know that each scenario re-runs its payload through `check_content`
 * to prove the entity count was zero; the other nineteen want the result, and
 * were being charged 4,400 words for it.
 */
export function Method({ children }: { children: ReactNode }) {
  return (
    <details className="bm-method">
      <summary>How this was run</summary>
      <div>{children}</div>
    </details>
  );
}

/* --- 6. The limits, as a designed block ----------------------------------- */

/**
 * Every section on this page ends with what its result does not show, and those
 * lists are the reason the page is worth reading. They were set as ordinary
 * bullet lists in ordinary prose, which is where a reader's eye skips to the
 * next heading — the most credible material on the site rendered in the least
 * visible style available.
 *
 * Here it gets an edge, a label and tight rows, so the honesty reads as
 * something the page was built around rather than something appended to it.
 */
export function Limits({
  title = "What this does not show",
  items,
}: {
  title?: string;
  items: { lead: string; body: ReactNode }[];
}) {
  return (
    <section className="bm-limits" aria-label={title}>
      <h3>{title}</h3>
      <ul>
        {items.map((it) => (
          <li key={it.lead}>
            <strong>{it.lead}</strong> {it.body}
          </li>
        ))}
      </ul>
    </section>
  );
}
