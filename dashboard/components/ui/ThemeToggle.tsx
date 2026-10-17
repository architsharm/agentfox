"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "system" | "dark";

const STORAGE_KEY = "agentfox-theme";

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

/* Three 14px line icons, drawn rather than pulled from a set: it is three glyphs
   and a dependency for three glyphs is a dependency that has to be upgraded. */
const ICONS: Record<Theme, React.ReactNode> = {
  light: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
    </>
  ),
  system: (
    <>
      <rect x="2" y="4" width="20" height="13" rx="2" />
      <path d="M8 21h8M12 17v4" />
    </>
  ),
  dark: <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />,
};

const LABEL: Record<Theme, string> = {
  light: "Light",
  system: "Match system",
  dark: "Dark",
};

/**
 * The theme control, and the only one: the sidebar and the public navigation bar
 * both render this, so a visitor who sets the theme on the marketing site keeps
 * it after signing in, and there is one definition of what the three states are.
 *
 * It used to be three text buttons in the sidebar and nothing at all on the
 * public pages, which meant the setting existed only for people who already had
 * an account — backwards, since the public pages are the ones a visitor meets
 * first. Icons rather than words because this now has to fit a navigation row.
 *
 * The state starts at "light" to agree with the pre-paint script in layout.tsx.
 * Starting at "system" here would light the wrong segment for one frame after
 * hydration, on every load, for the default visitor.
 */
export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    try {
      setTheme((localStorage.getItem(STORAGE_KEY) as Theme | null) || "light");
    } catch {
      // Private modes throw on access. The light default in the markup is right.
    }
  }, []);

  function choose(next: Theme) {
    setTheme(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Not persisting is survivable; not applying it is not.
    }
    apply(next);
  }

  return (
    <div
      className={compact ? "theme-toggle theme-toggle-compact" : "theme-toggle"}
      role="group"
      aria-label="Theme"
    >
      {(["light", "system", "dark"] as Theme[]).map((t) => (
        <button
          key={t}
          type="button"
          aria-pressed={theme === t}
          aria-label={LABEL[t]}
          title={LABEL[t]}
          onClick={() => choose(t)}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            {ICONS[t]}
          </svg>
        </button>
      ))}
    </div>
  );
}
