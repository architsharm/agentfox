"use client";

/*
 * The request, changing as you read what happens to it.
 *
 * The previous version put a sticky trace beside the eight stations, which
 * filled the empty half of the screen but showed the same frame the whole way
 * down. This one advances: as a station scrolls into the reading band, the panel
 * shows that stage of the same request.
 *
 * Why this is a client component when almost nothing else on the site is: there
 * is no CSS mechanism for "which element is currently being read". Scroll-driven
 * animations cannot branch on it, and `:target` only follows clicks. It needs an
 * IntersectionObserver, so it needs to hydrate.
 *
 * What that buys has to survive the observer never running — a reader on a slow
 * connection, with JS disabled, or with reduced motion set. So:
 *
 *   - Every stage's panel is rendered on the server, in the markup, all of them.
 *     Nothing is fetched and nothing is constructed at runtime.
 *   - Before hydration the LAST stage is the visible one, because it is the
 *     completed record — the most informative single frame, and the same one the
 *     static version showed.
 *   - Under prefers-reduced-motion the observer is never attached and the panel
 *     never moves; the reader keeps that completed record.
 *
 * So the enhancement is genuinely progressive: with JS it follows you, without
 * it you see the finished trace, and in neither case is anything missing.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

export type Frame = {
  /** Matches the station index it belongs to. */
  at: number;
  label: string;
  body: ReactNode;
};

export function FollowRequest({
  frames,
  children,
}: {
  frames: Frame[];
  children: ReactNode;
}) {
  const last = frames.length - 1;
  const [active, setActive] = useState(last);
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;

    const stations = Array.from(el.querySelectorAll<HTMLElement>("[data-station]"));
    if (!stations.length) return;

    // The reading band is the middle of the viewport rather than its top edge:
    // a reader's attention sits where their eyes are, not where the scroll
    // position happens to be.
    const seen = new Map<number, boolean>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const i = Number((e.target as HTMLElement).dataset.station);
          seen.set(i, e.isIntersecting);
        }
        // The furthest station currently in the band wins, so scrolling back up
        // rewinds rather than sticking at the deepest point ever reached.
        const inBand = [...seen.entries()].filter(([, v]) => v).map(([k]) => k);
        if (!inBand.length) return;
        const station = Math.max(...inBand);
        let next = 0;
        frames.forEach((f, i) => {
          if (f.at <= station) next = i;
        });
        setActive(next);
      },
      { rootMargin: "-45% 0px -45% 0px", threshold: 0 },
    );
    stations.forEach((s) => io.observe(s));
    return () => io.disconnect();
  }, [frames]);

  return (
    <div className="fr" ref={host}>
      <div className="fr-stations">{children}</div>
      <aside className="fr-panel" aria-live="polite">
        <div className="fr-panel-inner">
          <div className="fr-steps" aria-hidden>
            {frames.map((f, i) => (
              <span key={f.at} className={i === active ? "fr-step fr-step-on" : "fr-step"} />
            ))}
          </div>
          <span className="mk-label">{frames[active]?.label}</span>
          {/* All frames are in the markup; only one is shown. Keeping the others
              mounted means no layout jump when the panel advances and nothing to
              build at the moment it does. */}
          {frames.map((f, i) => (
            <div key={f.at} className="fr-frame" hidden={i !== active}>
              {f.body}
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}
