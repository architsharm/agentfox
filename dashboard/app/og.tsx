/**
 * The social card, shared by app/opengraph-image.tsx and app/twitter-image.tsx.
 *
 * Both metadata routes want the identical 1200x630 image, and Next requires each
 * to be its own file with its own `size`/`contentType`/default export, so the
 * actual drawing lives here once and each route re-exports it.
 *
 * Two constraints shape everything below:
 *
 * 1. `ImageResponse` renders through Satori, which does NOT resolve CSS custom
 *    properties. `var(--mk-accent)` would silently come out as nothing. So every
 *    colour is the literal hex read out of app/marketing.css, with the line it
 *    came from named beside it.
 * 2. Satori supports a subset of CSS. Every container with more than one child
 *    sets `display: "flex"` explicitly, because Satori has no block layout and
 *    throws on a multi-child div without it. No `filter`, no `box-shadow` blur,
 *    no web fonts loaded over the network: next/og ships a default font and using
 *    it is the difference between a card that always renders and one that fails
 *    whenever a font CDN is slow.
 */

import { ImageResponse } from "next/og";

import { OG_MARK_DATA_URI } from "./og-mark";

/**
 * The dark palette from app/marketing.css's dark block. Dark rather than light
 * because a social card is shown at thumbnail size against feed chrome, and a
 * near-white ground disappears into most of it.
 */
const MK = {
  bg: "#000000", // --mk-bg
  surface: "#1d1d1f", // --mk-surface
  border: "#333336", // --mk-border
  borderStrong: "#48484a", // --mk-border-strong
  text: "#f5f5f7", // --mk-text
  muted: "#a1a1a6", // --mk-muted
  faint: "#86868b", // --mk-faint
  accent: "#ff7a45", // --mk-accent, the text-safe orange
  brand: "#fd4901", // --mk-brand, the logo orange
} as const;

export const OG_SIZE = { width: 1200, height: 630 };
export const OG_CONTENT_TYPE = "image/png";

/** Alt text, reused by the `images` entries in app/layout.tsx. */
export const OG_ALT =
  "AgentFox: your agent believes what it reads, so limit what it is allowed to do. Open source, Apache-2.0.";

/**
 * The brand mark, drawn from the supplied artwork rather than redrawn in paths.
 *
 * This used to hand-trace the old shield into two SVG paths. There is now a real
 * logo file, and a second version of it maintained in code is a thing that silently
 * drifts from the original. Satori renders a data URI fine, so the card shows the
 * same pixels as the favicon and the page header.
 */
export function BrandMarkStatic({ size = 64 }: { size?: number }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={OG_MARK_DATA_URI} width={size} height={size} alt="" />
  );
}

export function ogImage(): ImageResponse {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "68px 76px",
          backgroundColor: MK.bg,
          // Stands in for the hero's ambient wash. A linear gradient is one of the
          // few backgrounds Satori renders; the blurred radial the site uses is not.
          backgroundImage: `linear-gradient(135deg, ${MK.surface} 0%, ${MK.bg} 46%, ${MK.bg} 100%)`,
          color: MK.text,
        }}
      >
        {/* Lockup */}
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <BrandMarkStatic size={64} />
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: 44, fontWeight: 700, letterSpacing: "-0.02em" }}>
              AgentFox
            </span>
            <span style={{ fontSize: 21, color: MK.muted, marginTop: 2 }}>
              by Nometria
            </span>
          </div>
        </div>

        {/* Headline. The same sentence the homepage hero renders, so the card
            and the page a reader lands on say one thing. */}
        <div style={{ display: "flex", flexDirection: "column", maxWidth: 1000 }}>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              fontSize: 58,
              fontWeight: 700,
              lineHeight: 1.08,
              letterSpacing: "-0.03em",
            }}
          >
            <span style={{ width: "100%" }}>Secure your agents.</span>
            <span style={{ width: "100%", color: MK.brand }}>One control plane.</span>
          </div>
          <div style={{ display: "flex", fontSize: 26, color: MK.muted, marginTop: 22, lineHeight: 1.45 }}>
            One platform for the agents you already run: discovery, access
            control, runtime guardrails, and an audit trail.
          </div>
        </div>

        {/* Footing */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 18,
            paddingTop: 26,
            borderTop: `1px solid ${MK.border}`,
            fontSize: 24,
            color: MK.faint,
          }}
        >
          <span
            style={{
              display: "flex",
              padding: "7px 16px",
              borderRadius: 999,
              border: `1px solid ${MK.borderStrong}`,
              color: MK.accent,
              fontSize: 22,
              fontWeight: 600,
            }}
          >
            Apache-2.0
          </span>
          <span style={{ display: "flex" }}>Open source</span>
          <span style={{ display: "flex", color: MK.border }}>·</span>
          <span style={{ display: "flex" }}>github.com/architsharm/agentfox</span>
        </div>
      </div>
    ),
    { ...OG_SIZE },
  );
}

/**
 * A blog post's card: same ground, lockup and footing as the site card, with the
 * post's topic and title where the strapline goes. The title is sized down for
 * long headlines so it never runs off the card — Satori does not shrink to fit.
 */
export function articleOgImage({ kicker, title }: { kicker: string; title: string }): ImageResponse {
  const fontSize = title.length > 70 ? 50 : title.length > 50 ? 58 : 66;
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "68px 76px",
          backgroundColor: MK.bg,
          backgroundImage: `linear-gradient(135deg, ${MK.surface} 0%, ${MK.bg} 46%, ${MK.bg} 100%)`,
          color: MK.text,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <BrandMarkStatic size={52} />
          <span style={{ fontSize: 34, fontWeight: 700, letterSpacing: "-0.02em" }}>AgentFox</span>
          <span style={{ display: "flex", fontSize: 30, color: MK.border }}>/</span>
          <span style={{ fontSize: 30, color: MK.muted }}>Blog</span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", maxWidth: 1040 }}>
          <span
            style={{
              display: "flex",
              fontSize: 24,
              fontWeight: 600,
              color: MK.accent,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            {kicker}
          </span>
          <div
            style={{
              display: "flex",
              marginTop: 18,
              fontSize,
              fontWeight: 700,
              lineHeight: 1.08,
              letterSpacing: "-0.03em",
            }}
          >
            {title}
          </div>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 18,
            paddingTop: 26,
            borderTop: `1px solid ${MK.border}`,
            fontSize: 24,
            color: MK.faint,
          }}
        >
          <span style={{ display: "flex", color: MK.brand }}>useagentfox.com/blog</span>
          <span style={{ display: "flex", color: MK.border }}>·</span>
          <span style={{ display: "flex" }}>Open source, Apache-2.0</span>
        </div>
      </div>
    ),
    { ...OG_SIZE },
  );
}
