"use client";

/**
 * Board view is explicitly framed as the artifact shown to leadership, but had
 * no way to get it out of the browser — a screenshot was the only option.
 * window.print() plus the @media print rules in globals.css (hide the nav
 * chrome, let panels break cleanly across pages) turns it into a real
 * "save as PDF" / print flow via the browser's own print dialog.
 */
export function PrintButton() {
  return (
    <button type="button" className="btn-scan no-print" onClick={() => window.print()}>
      Print / save as PDF
    </button>
  );
}
