"use client";

import { useState } from "react";

/**
 * One optional free-text question, answered once. Free text rather than a list:
 * "a Reddit thread" and "Perplexity" are the answers that matter and no list has them.
 * The answer goes to the same cookie-less counter as the page view (components/Analytics.tsx)
 * and nowhere else; it is not stored with the account.
 */
export function HeardFrom() {
  const [answer, setAnswer] = useState("");
  const [sent, setSent] = useState(false);
  if (sent) return <p className="gs-note">Thanks.</p>;
  return (
    <form
      className="gs-row"
      onSubmit={(e) => {
        e.preventDefault();
        const text = answer.trim();
        if (text) window.umami?.track("heard_from", { answer: text });
        setSent(true);
      }}
    >
      <label htmlFor="heard-from">How did you hear about AgentFox?</label>
      <input
        id="heard-from"
        className="k-input"
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        maxLength={200}
        placeholder="Optional"
      />
      <button type="submit" className="k-btn">Send</button>
    </form>
  );
}
