"use client";

import { useState } from "react";

/** An identifier shown small and secondary, with a copy button: for the IDs that
 *  support and the CLI ask for, which are not something to read. */
export function CopyId({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="copy-id">
      <code className="mono">{value}</code>
      <button
        type="button"
        className="copy-id-btn"
        aria-label={copied ? "Copied" : `Copy ${value}`}
        onClick={() =>
          navigator.clipboard
            .writeText(value)
            .then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            })
            .catch(() => setCopied(false))
        }
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </span>
  );
}
