"use client";

import { createContext, useContext, type ReactNode } from "react";

/**
 * The range a page chose for itself when the URL named none (`lib/product/range.ts`),
 * so the filter bar highlights the window the numbers are actually for without a
 * redirect round trip to put it in the URL.
 */
const RangeContext = createContext<string | undefined>(undefined);

export function RangeProvider({ range, children }: { range?: string; children: ReactNode }) {
  return <RangeContext.Provider value={range}>{children}</RangeContext.Provider>;
}

export function usePageRange(): string | undefined {
  return useContext(RangeContext);
}
