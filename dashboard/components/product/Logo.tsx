import { useId } from "react";

/**
 * The AgentFox mark: a fox's head whose ears and chin make a shield. The fox is the
 * name; the shield is what it does. Drawn as an SVG so it stays sharp at every size,
 * from the 14px badge on a guarded tool to the sidebar. Fixed brand colours, not
 * theme tokens: a logo that changes colour with the theme is not a logo.
 * Same artwork as `public/brand/mark-shield.svg`.
 */
export function Logo({ size = 22, title }: { size?: number; title?: string }) {
  const g = useId();
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      style={{ flex: `0 0 ${size}px`, display: "block" }}
    >
      <defs>
        <linearGradient id={g} x1="6" y1="3" x2="26" y2="29" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#E0486F" />
          <stop offset="1" stopColor="#B21F4B" />
        </linearGradient>
      </defs>
      <path d="M5 3 12.6 9.6h6.8L27 3v12c0 6.6-4.6 11.3-11 14-6.4-2.7-11-7.4-11-14V3Z" fill={`url(#${g})`} />
      <path d="M5 3 12.6 9.6H9.4L5 5.8V3ZM27 3l-7.6 6.6h3.2L27 5.8V3Z" fill="#fff" fillOpacity=".25" />
      <path d="M5.2 16.6c4.4-.2 8.3 2.3 10.8 6.6 2.5-4.3 6.4-6.8 10.8-6.6-.9 5.6-5 9.7-10.8 12.1-5.8-2.4-9.9-6.5-10.8-12.1Z" fill="#fff" />
      <path d="M9.6 14.4c.9-1.3 2.6-1.6 3.8-.6-1.2 1-2.6 1.2-3.8.6ZM22.4 14.4c-.9-1.3-2.6-1.6-3.8-.6 1.2 1 2.6 1.2 3.8.6Z" fill="#2A0F18" />
      <path d="M14.4 23.4h3.2L16 25.3l-1.6-1.9Z" fill="#2A0F18" />
      <path d="M5 3 12.6 9.6h6.8L27 3v12c0 6.6-4.6 11.3-11 14-6.4-2.7-11-7.4-11-14V3Z" stroke="#B21F4B" strokeWidth="1.1" strokeLinejoin="round" />
    </svg>
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
