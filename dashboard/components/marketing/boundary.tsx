/**
 * The Boundary — the hero visual, and the one idea this product has.
 *
 * What was here before was a panel of log rows: four tool calls with verdict
 * chips beside them. It is accurate and it is not a design. It shows *what
 * happened* the way a terminal would, so the picture carries no argument of its
 * own — swap the logo and it could sit on any observability product.
 *
 * This product is a boundary. Calls approach it, most go through, one does not.
 * That is the entire proposition, it is inherently visual, and nobody else in
 * the category is using it. So the hero draws the boundary itself and lets the
 * calls be lines that either cross it or stop at it.
 *
 * Why the refusal is the third of four rather than the last: last would read as
 * a conclusion the demo was built to reach. In the middle it reads as what it
 * is — one call among several, caught on the way past.
 *
 * Built as one inline SVG with CSS animation. No canvas, no chart library, no
 * client component: the geometry is fixed, so anything more is a dependency and
 * a hydration boundary bought for nothing. Every line is drawn with
 * stroke-dashoffset, which means the whole thing degrades to a complete, static
 * diagram the moment animation is off — see prefers-reduced-motion in the CSS.
 */

type Track = {
  tool: string;
  arg: string;
  /** false = stops at the boundary. */
  passes: boolean;
  rule?: string;
};

const TRACKS: Track[] = [
  { tool: "kb.search", arg: 'q: "refund policy"', passes: true },
  { tool: "crm.lookup", arg: "customer: cus_882", passes: true },
  {
    tool: "payments.transfer",
    arg: "amount: 5000 → acct_x",
    passes: false,
    rule: "capability.denied",
  },
  { tool: "tickets.create", arg: "order: #4471", passes: true },
];

/* Geometry. One place, so the labels and the lines cannot drift apart.
 *
 * W is the number that matters and it is not a canvas size: an SVG scales to
 * its container, so the viewBox width sets how large everything inside it
 * *appears*. The first attempt used 720 in a ~500px column, which scaled the
 * whole drawing to 69% and rendered 13px labels at nine. Narrower viewBox,
 * bigger type, same column. */
const W = 520;
const ROW_H = 62;
const TOP = 44;
const H = TOP + TRACKS.length * ROW_H + 18;
const GATE = 300; // x of the boundary
const TRACK_START = 168; // where a line leaves its label
const TRACK_END = 452; // where a passing line ends

export function Boundary() {
  return (
    <figure className="bd">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={ARIA}>
        <defs>
          {/* The glow either side of the boundary. Soft, and only where a line
              meets it — a full-height halo would read as decoration. */}
          {/* userSpaceOnUse, not the default objectBoundingBox: a vertical
              line has zero bounding-box WIDTH, so a bounding-box gradient on
              one degenerates and the line renders invisible. That is exactly
              what happened here — the boundary was not faint, it was absent,
              and only the tick marks were holding the position. */}
          <linearGradient
            id="bd-gate"
            gradientUnits="userSpaceOnUse"
            x1={GATE}
            y1={24}
            x2={GATE}
            y2={H - 8}
          >
            <stop offset="0%" stopColor="currentColor" stopOpacity="0" />
            <stop offset="16%" stopColor="currentColor" stopOpacity=".95" />
            <stop offset="84%" stopColor="currentColor" stopOpacity=".95" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
          {/* A soft band either side, so the checkpoint has depth rather than
              being one hairline. */}
          <linearGradient
            id="bd-band"
            gradientUnits="userSpaceOnUse"
            x1={GATE - 26}
            y1={0}
            x2={GATE + 26}
            y2={0}
          >
            <stop offset="0%" stopColor="currentColor" stopOpacity="0" />
            <stop offset="50%" stopColor="currentColor" stopOpacity=".1" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* --- the boundary ------------------------------------------------ */}
        <g className="bd-gate">
          <rect x={GATE - 26} y={18} width={52} height={H - 22} fill="url(#bd-band)" />
          <line x1={GATE} y1={24} x2={GATE} y2={H - 8} stroke="url(#bd-gate)" strokeWidth="1.75" />
          {/* Tick marks up the line: this is a checkpoint, not a wall. They are
              what make it read as an instrument rather than a border. */}
          {Array.from({ length: 11 }).map((_, i) => (
            <line
              key={i}
              x1={GATE - 3}
              x2={GATE + 3}
              y1={34 + i * ((H - 56) / 10)}
              y2={34 + i * ((H - 56) / 10)}
              className="bd-tick"
            />
          ))}
          <text x={GATE} y={16} className="bd-gate-label" textAnchor="middle">
            CAPABILITY CHECK
          </text>
        </g>

        {/* --- the calls ---------------------------------------------------- */}
        {TRACKS.map((t, i) => {
          const y = TOP + i * ROW_H + ROW_H / 2;
          const stop = t.passes ? TRACK_END : GATE;
          const delay = 0.25 + i * 0.22 + (t.passes ? 0 : 0.1);
          return (
            <g key={t.tool} className={t.passes ? "bd-track" : "bd-track bd-track-stop"}>
              <text x={0} y={y - 6} className="bd-tool">
                {t.tool}
              </text>
              <text x={0} y={y + 10} className="bd-arg">
                {t.arg}
              </text>

              <line
                x1={TRACK_START}
                y1={y}
                x2={stop}
                y2={y}
                className="bd-line"
                style={{ "--d": `${delay}s`, "--len": `${stop - TRACK_START}` } as React.CSSProperties}
              />

              {t.passes ? (
                <>
                  {/* Through, and gone. The arrowhead sits past the boundary so
                      the eye reads direction, not just a line. */}
                  <path
                    d={`M${TRACK_END - 7} ${y - 4} L${TRACK_END} ${y} L${TRACK_END - 7} ${y + 4}`}
                    className="bd-head"
                    style={{ "--d": `${delay + 0.42}s` } as React.CSSProperties}
                  />
                  <text x={TRACK_END + 9} y={y + 4} className="bd-verdict bd-verdict-go">
                    ran
                  </text>
                </>
              ) : (
                <>
                  {/* Stopped. A ring that expands once at the point of contact,
                      then a bar across the line: the call got here and no
                      further. The bar is 2px and full-height of the row so it
                      reads as an obstruction rather than a dot. */}
                  <circle
                    cx={GATE}
                    cy={y}
                    r="5"
                    className="bd-impact"
                    style={{ "--d": `${delay + 0.34}s` } as React.CSSProperties}
                  />
                  <line
                    x1={GATE}
                    y1={y - 13}
                    x2={GATE}
                    y2={y + 13}
                    className="bd-bar"
                    style={{ "--d": `${delay + 0.34}s` } as React.CSSProperties}
                  />
                  <text
                    x={GATE + 14}
                    y={y - 2}
                    className="bd-verdict bd-verdict-stop"
                    style={{ "--d": `${delay + 0.46}s` } as React.CSSProperties}
                  >
                    refused
                  </text>
                  <text
                    x={GATE + 14}
                    y={y + 14}
                    className="bd-rule"
                    style={{ "--d": `${delay + 0.46}s` } as React.CSSProperties}
                  >
                    {t.rule}
                  </text>
                </>
              )}
            </g>
          );
        })}
      </svg>

      <figcaption>
        Refused on this agent&rsquo;s grants and the call&rsquo;s own arguments — no
        prompt recognition involved.
      </figcaption>
    </figure>
  );
}

const ARIA =
  "Four tool calls from one agent approach a capability check. kb.search, " +
  "crm.lookup and tickets.create pass through and run. payments.transfer, " +
  "moving 5000 to acct_x, is stopped at the check by capability.denied.";
