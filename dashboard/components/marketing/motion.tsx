"use client";

import { useEffect } from "react";

/**
 * Scroll-reveal, and the two failure modes it has to avoid.
 *
 * What was here before was a load animation: `.mk-up` with staggered delays,
 * fired once when the document parsed. Everything below the fold had therefore
 * already played by the time anyone scrolled to it, so a page eight thousand
 * pixels tall had motion in its first screen and none in the other seven.
 *
 * **Failure one: the blank page.** The previous comment in marketing.css
 * records it — `animation: … both` holds an element at opacity 0 through its
 * delay, a browser throttles animations in a background tab, and a page opened
 * in one rendered 34 invisible elements waiting on a frame that never came.
 * So this uses a *transition* between two real states rather than an
 * animation: the revealed state is an ordinary style, and a throttled or
 * skipped transition still lands on it.
 *
 * **Failure two: no JavaScript, no page.** The hidden state is scoped to
 * `[data-reveal]` on the root, which only this component sets. Without it —
 * script blocked, crawler, reader mode — every `.mk-reveal` is simply visible,
 * which is also what `prefers-reduced-motion` gets.
 *
 * The failsafe exists because IntersectionObserver is not the only way an
 * element can end up off-screen forever: inside a collapsed parent, behind a
 * `content-visibility` skip, or in a browser that mis-reports a scroll
 * container. Two seconds after mount everything is revealed regardless. A
 * missed animation is a blemish; unreadable text is a broken page.
 */
export function ScrollReveal() {
  useEffect(() => {
    const root = document.documentElement;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    root.setAttribute("data-reveal", "");
    const targets = () => Array.from(document.querySelectorAll<HTMLElement>(".mk-reveal"));
    const revealAll = () => targets().forEach((el) => el.classList.add("is-in"));

    if (!("IntersectionObserver" in window)) {
      revealAll();
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          // Once. A section that re-animates every time it scrolls back into
          // view reads as a glitch, not as polish.
          entry.target.classList.add("is-in");
          observer.unobserve(entry.target);
        }
      },
      // A little before it arrives, so the element is settled by the time the
      // reader's eye reaches it rather than moving under them.
      { rootMargin: "0px 0px -12% 0px", threshold: 0.01 },
    );

    targets().forEach((el) => observer.observe(el));
    const failsafe = window.setTimeout(revealAll, 2000);

    return () => {
      window.clearTimeout(failsafe);
      observer.disconnect();
      root.removeAttribute("data-reveal");
    };
  }, []);

  return null;
}

/**
 * The threat marquee.
 *
 * Borrowed in form from the competitor page that reads fastest, and it earns
 * its place for a reason beyond decoration: this product's subject is a list
 * of attack names that means nothing to most readers in prose and a great deal
 * at a glance. A paragraph naming six of them is a paragraph people skip; the
 * same six drifting past are absorbed without being read.
 *
 * CSS only — no library, no scroll listener, no measurement. The track holds
 * the list twice and translates by exactly half its own width, which loops
 * seamlessly at any content length without JavaScript computing anything.
 *
 * `aria-hidden` on the duplicate, because a screen reader should hear the list
 * once. Paused entirely under `prefers-reduced-motion`, where an endlessly
 * moving band is not a flourish but a barrier.
 */
const THREATS = [
  "prompt injection",
  "tool poisoning",
  "credential-file access",
  "unbounded DELETE",
  "rug-pulled MCP tool",
  "hidden text in a document",
  "excessive agency",
  "cross-tenant leakage",
  "history rewrite",
  "supply-chain publish",
];

export function ThreatMarquee() {
  const run = (
    <span className="mk-marquee-run">
      {THREATS.map((threat) => (
        <span key={threat}>
          {threat}
          <i aria-hidden>//</i>
        </span>
      ))}
    </span>
  );

  return (
    <div className="mk-marquee" role="group" aria-label="Failures AgentFox checks for">
      <div className="mk-marquee-track">
        {run}
        <span aria-hidden>{run}</span>
      </div>
    </div>
  );
}
