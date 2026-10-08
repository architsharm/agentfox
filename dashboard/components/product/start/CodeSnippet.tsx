"use client";

import { useState } from "react";

/** A command or code block with a copy button — what every setup step hands over. */
export function CodeSnippet({ code, label }: { code: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="snippet">
      {label && <div className="snippet-label">{label}</div>}
      <pre>
        <code>{code}</code>
      </pre>
      <button
        type="button"
        className="snippet-copy"
        aria-label={`Copy${label ? ` ${label}` : ""}`}
        onClick={() =>
          navigator.clipboard
            .writeText(code)
            .then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            })
            .catch(() => setCopied(false))
        }
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}
