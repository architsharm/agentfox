"use client";

import dynamic from "next/dynamic";
import type { AgentMap } from "./GuardrailMap";

/**
 * The map's graph library is the heaviest thing on the agent page; load it only when
 * the Map tab is open, not with every agent view.
 */
const Map = dynamic(() => import("./GuardrailMap").then((m) => m.GuardrailMap), {
  ssr: false,
  loading: () => <div className="gm-canvas" aria-busy="true" />,
});

export function GuardrailMapLazy({ map }: { map: AgentMap }) {
  return <Map map={map} />;
}
