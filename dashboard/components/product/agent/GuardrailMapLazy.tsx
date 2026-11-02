"use client";

import dynamic from "next/dynamic";
import type { AgentMap, Catalog } from "./GuardrailMap";
import type { AgentFacts } from "@/lib/product/agentStatus";

/**
 * The map's graph library is the heaviest thing on the agent page; load it only when
 * the canvas is open, not with every project view.
 */
const Map = dynamic(() => import("./GuardrailMap").then((m) => m.GuardrailMap), {
  ssr: false,
  // Visible while the graph library downloads, so the tab never reads as empty.
  loading: () => (
    <div className="gm-canvas gm-loading" aria-busy="true">
      <div className="k-skel gm-loading-bar" />
      <span className="muted small">Drawing the map…</span>
    </div>
  ),
});

export function GuardrailMapLazy(props: {
  maps: AgentMap[];
  focus: string;
  project: string;
  catalog?: Catalog;
  facts?: Record<string, AgentFacts>;
  actor?: string | null;
}) {
  return <Map {...props} />;
}
