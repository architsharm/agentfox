/**
 * The shell's mark, and the same artwork the marketing pages and the favicon use
 * (`public/brand/mark.webp`, `app/icon.png`). It replaced a hand-drawn shield: once
 * real brand artwork exists, a second mark drawn in code is just a thing that drifts
 * from it.
 *
 * It is a raster with fixed brand colours rather than an SVG inheriting `--accent`,
 * which is correct for a logo. Both of its colours read on the light and the dark
 * shell, and a logo that changes colour with the theme is not a logo.
 */
export function Logo({ size = 22 }: { size?: number }) {
  return (
    <img
      src="/brand/mark.webp"
      alt=""
      width={size}
      height={size}
      decoding="async"
      style={{ flex: `0 0 ${size}px`, width: size, height: size, display: "block" }}
    />
  );
}

export function Wordmark({ size = 22 }: { size?: number }) {
  return (
    <span className="wordmark">
      <Logo size={size} />
      <span>AgentFox</span>
    </span>
  );
}
