/**
 * What one agent actually reaches, drawn.
 *
 * The same data was already on this page as a four-column table — from,
 * relation, to, seen — which answers "is there an edge" and not the question
 * anyone opens it for: how far does this thing reach, and is any of it a
 * surprise. Microsoft ships an "Agent map" in Agent 365 for exactly this, and
 * it is the right idea: an estate is a shape before it is a list.
 *
 * Two things here that a map of the estate does not give you:
 *
 *   - Every edge is *observed*, from traced traffic, not read from a manifest.
 *     An edge that is observed and was never declared is drawn as such, because
 *     that gap is registry drift — the agent is doing something nobody wrote
 *     down — and it is the single most useful thing this picture can say.
 *   - Blast radius is the count the picture is of, so it sits on the picture
 *     rather than in a tile somewhere else claiming the same thing.
 *
 * Server-rendered SVG, no client JS and no layout library: the geometry is a
 * circle, and a force-directed graph would cost a dependency and a hydration
 * boundary to arrange fifteen nodes that a circle arranges exactly.
 */

type Node = { id: string; type: string };
type Link = {
  source: string;
  target: string;
  relation: string;
  observed_count: number;
  declared: boolean;
};

const TYPE_FILL: Record<string, string> = {
  agent: "var(--accent)",
  tool: "var(--text)",
  model: "var(--muted)",
  source: "var(--muted)",
};

/** Long identifiers are the norm here (`redteam.sim.close_account`). */
function short(id: string): string {
  if (id.length <= 22) return id;
  const tail = id.split(".").slice(-2).join(".");
  return tail.length <= 22 ? tail : `${tail.slice(0, 21)}…`;
}

export function AgentMap({
  root,
  nodes,
  links,
  blastRadius,
}: {
  root: string;
  nodes: Node[];
  links: Link[];
  blastRadius: number;
}) {
  const others = nodes.filter((n) => n.id !== root);
  if (others.length === 0) return null;

  // Geometry. Height grows with the node count so labels never collide: at
  // twenty-plus nodes a fixed box would overlap them into illegibility.
  const W = 760;
  const R = Math.min(250, 110 + others.length * 7);
  const H = R * 2 + 90;
  const cx = W / 2;
  const cy = H / 2;

  const undeclared = links.filter((l) => !l.declared).length;
  const maxSeen = Math.max(...links.map((l) => l.observed_count || 1), 1);

  // Start at the top and go clockwise; a node's angle is stable for a given
  // node list, so the picture does not reshuffle between page loads.
  const placed = others.map((n, i) => {
    const angle = (i / others.length) * Math.PI * 2 - Math.PI / 2;
    return {
      ...n,
      x: cx + Math.cos(angle) * R,
      y: cy + Math.sin(angle) * R,
      // Which side the label sits on, so it never runs back over the node.
      anchor: Math.cos(angle) > 0.2 ? "start" : Math.cos(angle) < -0.2 ? "end" : "middle",
      dx: Math.cos(angle) > 0.2 ? 11 : Math.cos(angle) < -0.2 ? -11 : 0,
      dy: Math.abs(Math.cos(angle)) <= 0.2 ? (Math.sin(angle) > 0 ? 20 : -12) : 4,
    };
  });
  const at = new Map(placed.map((p) => [p.id, p]));

  return (
    <figure className="agent-map">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label={`${root} reaches ${others.length} other things across ${links.length} observed relationships.`}
      >
        {links.map((l, i) => {
          const a = l.source === root ? { x: cx, y: cy } : at.get(l.source);
          const b = l.target === root ? { x: cx, y: cy } : at.get(l.target);
          if (!a || !b) return null;
          return (
            <line
              key={i}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              className={l.declared ? "am-edge" : "am-edge am-edge-undeclared"}
              // Weight carries how often it happened. A tool called four times
              // and one called once are not the same edge.
              strokeWidth={1 + (l.observed_count / maxSeen) * 2.4}
            />
          );
        })}

        {placed.map((n) => (
          <g key={n.id}>
            <circle
              cx={n.x}
              cy={n.y}
              r={5.5}
              fill={TYPE_FILL[n.type] || "var(--muted)"}
              className="am-node"
            />
            <text
              x={n.x + n.dx}
              y={n.y + n.dy}
              textAnchor={n.anchor}
              className="am-label"
            >
              {short(n.id)}
            </text>
          </g>
        ))}

        <circle cx={cx} cy={cy} r={9} fill="var(--accent)" className="am-node am-root" />
        <text x={cx} y={cy - 22} textAnchor="middle" className="am-label am-root-label">
          {short(root)}
        </text>
      </svg>

      <figcaption>
        <span className="am-legend">
          <i className="am-key am-key-agent" /> agent
          <i className="am-key am-key-tool" /> tool
          <i className="am-key am-key-model" /> model
        </span>
        <span>
          <strong>{blastRadius}</strong> reachable within two hops of observed traffic —
          how far a bad decision here could travel.
          {undeclared > 0 && (
            <>
              {" "}
              <strong className="am-warn">{undeclared} of {links.length}</strong> were
              observed but never declared.
            </>
          )}
        </span>
      </figcaption>
    </figure>
  );
}
