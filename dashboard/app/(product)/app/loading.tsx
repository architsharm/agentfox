/**
 * What shows while an app page's data is on its way.
 *
 * It sits inside the app layout, so the sidebar and header stay where they are and
 * only the content area changes. With the only loading boundary at the root, every
 * navigation blanked the whole frame — sidebar included — until the server answered,
 * and the page jumped when it came back. Next also prefetches this boundary for every
 * link, so a click shows it at once.
 */

const PULSE = `
@keyframes k-skel { 0%,100% { opacity: 1 } 50% { opacity: .55 } }
.k-skel { background: var(--dim-bg); border-radius: 6px; animation: k-skel 1.6s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) { .k-skel { animation: none; } }
`;

function Bar({ w, h = 12 }: { w: number | string; h?: number }) {
  return <div className="k-skel" style={{ width: w, height: h }} />;
}

export default function Loading() {
  return (
    <div aria-busy="true" aria-label="Loading">
      <style>{PULSE}</style>
      <div style={{ margin: "6px 0 22px" }}>
        <Bar w={200} h={26} />
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
        {[90, 110, 80, 100].map((w, i) => (
          <Bar key={i} w={w} h={14} />
        ))}
      </div>
      <div className="k-grid k-grid-4">
        {[0, 1, 2, 3].map((i) => (
          <section key={i} className="k-card">
            <div className="k-card-body" style={{ display: "grid", gap: 10 }}>
              <Bar w={70} h={10} />
              <Bar w={56} h={22} />
            </div>
          </section>
        ))}
      </div>
      <section className="k-card" style={{ marginTop: 16 }}>
        <div className="k-card-body" style={{ display: "grid", gap: 14 }}>
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} style={{ display: "flex", gap: 20 }}>
              <Bar w={120} h={10} />
              <div style={{ flex: 1 }}>
                <Bar w="65%" h={10} />
              </div>
              <Bar w={60} h={10} />
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
