"use client";

import { useState } from "react";
import Link from "next/link";
import { AgentLink, ControlChip, Severity, findingTypeInfo, ts } from "@/components/ui";
import { FindingEvidence } from "@/components/product/FindingEvidence";

/**
 * The list already carries the full evidence blob (same object the detail page
 * fetches separately) — expanding in place costs no extra request, just a state
 * toggle, so "scan twenty, look closely at one" doesn't force a page jump.
 *
 * The row used to be the only control: a click handler on the <tr> with no role,
 * no tab stop and no key handler, which meant a keyboard or screen-reader user
 * could not open a finding at all, and the collapsed row linked only sideways (to
 * the agent and the controls) — never to the finding itself. So there are now two
 * real controls: the title is a link to the detail page, and expansion is its own
 * <button> with aria-expanded. The row click still works for mouse users, and the
 * two links inside it stop propagation so following one doesn't also toggle.
 */
export function ExpandableFindingRow({
  finding,
  agents,
  controlTitles,
}: {
  finding: any;
  agents: any[];
  controlTitles: Record<string, string>;
}) {
  const [open, setOpen] = useState(false);
  const typeInfo = findingTypeInfo(finding.type);
  const panelId = `finding-detail-${finding.id}`;

  return (
    <>
      <tr
        onClick={() => setOpen((v) => !v)}
        style={{ cursor: "pointer" }}
        className={open ? "row-expanded" : undefined}
      >
        <td><Severity value={finding.severity} /></td>
        <td className="small" onClick={(e) => e.stopPropagation()}>
          {finding.agent_slug ? (
            <AgentLink slug={finding.agent_slug} agents={agents} />
          ) : (
            <span className="muted">unattributed</span>
          )}
        </td>
        <td className="small">{typeInfo.label}</td>
        <td className="small wrap" style={{ minWidth: "22ch" }}>
          <span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setOpen((v) => !v);
              }}
              aria-expanded={open}
              aria-controls={open ? panelId : undefined}
              aria-label={`${open ? "Hide" : "Show"} evidence for ${finding.title}`}
              style={{
                background: "none",
                border: "none",
                padding: 0,
                margin: 0,
                cursor: "pointer",
                color: "inherit",
                font: "inherit",
                lineHeight: 1,
                marginRight: 6,
              }}
            >
              <span className="expand-caret" aria-hidden="true">{open ? "▾" : "▸"}</span>
            </button>
            <Link href={`/app/findings/${finding.id}`} onClick={(e) => e.stopPropagation()}>
              {finding.title}
            </Link>
          </span>
          {typeInfo.blurb && <div className="small muted">{typeInfo.blurb}</div>}
        </td>
        <td className="small w-name" onClick={(e) => e.stopPropagation()}>
          {(finding.controls || []).map((c: string) => (
            <ControlChip key={c} code={c} titles={controlTitles} />
          ))}
        </td>
        <td className="small muted w-when">{ts(finding.created_at)}</td>
      </tr>
      {open && (
        <tr className="row-expanded" id={panelId}>
          <td colSpan={6} style={{ padding: "4px 14px 18px" }}>
            <FindingEvidence finding={finding} />
            <div style={{ marginTop: 10 }}>
              <Link href={`/app/findings/${finding.id}`} onClick={(e) => e.stopPropagation()}>
                Open full finding →
              </Link>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
