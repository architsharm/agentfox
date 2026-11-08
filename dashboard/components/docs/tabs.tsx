"use client";

import { Children, isValidElement, useState, type ReactElement, type ReactNode } from "react";

/**
 * The same step done two ways, side by side: in the web app, or on the command line.
 * Everything in AgentFox can be done from either, so a step shows both and the reader
 * picks one. The first tab is open by default.
 *
 *   <Tabs>
 *     <Tab label="In the app">...</Tab>
 *     <Tab label="CLI"><Code>{`agentfox ...`}</Code></Tab>
 *   </Tabs>
 */
export function Tabs({ children }: { children: ReactNode }) {
  const tabs = Children.toArray(children).filter(isValidElement) as ReactElement<{
    label: string;
    children: ReactNode;
  }>[];
  const [open, setOpen] = useState(0);
  return (
    <div className="docs-tabs">
      <div role="tablist" className="docs-tabs-list">
        {tabs.map((tab, i) => (
          <button
            key={tab.props.label}
            type="button"
            role="tab"
            aria-selected={i === open}
            onClick={() => setOpen(i)}
          >
            {tab.props.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="docs-tabs-panel">
        {tabs[open]?.props.children}
      </div>
    </div>
  );
}

export function Tab({ children }: { label: string; children: ReactNode }) {
  return <>{children}</>;
}
