"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { RANGES } from "@/lib/product/vocab";

/**
 * Time range, agent and environment — the same three filters on every view that
 * has numbers. They live in the URL, so a filtered view is a link someone can
 * share, and changing one never resets the others.
 */
export function FilterBar({
  agents,
  environments,
  range = true,
  defaultRange = "7d",
  children,
}: {
  agents?: { slug: string; name?: string | null }[];
  environments?: string[];
  range?: boolean;
  defaultRange?: string;
  children?: ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    router.replace(`${pathname}${next.toString() ? `?${next}` : ""}`, { scroll: false });
  };

  const current = params.get("range") || defaultRange;
  return (
    <div className="k-toolbar">
      {range && (
        <div className="k-seg" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              className={current === r.key ? "active" : ""}
              aria-pressed={current === r.key}
              onClick={() => set("range", r.key)}
            >
              {r.label}
            </button>
          ))}
        </div>
      )}
      {agents && agents.length > 0 && (
        <select
          className="k-select"
          aria-label="Agent"
          value={params.get("agent") || ""}
          onChange={(e) => set("agent", e.target.value)}
        >
          <option value="">All agents</option>
          {agents.map((a) => (
            <option key={a.slug} value={a.slug}>
              {a.name || a.slug}
            </option>
          ))}
        </select>
      )}
      {environments && environments.length > 1 && (
        <select
          className="k-select"
          aria-label="Environment"
          value={params.get("env") || ""}
          onChange={(e) => set("env", e.target.value)}
        >
          <option value="">All environments</option>
          {environments.map((env) => (
            <option key={env} value={env}>
              {env}
            </option>
          ))}
        </select>
      )}
      {children && <div className="k-toolbar-end">{children}</div>}
    </div>
  );
}
