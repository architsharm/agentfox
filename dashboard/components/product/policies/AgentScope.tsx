"use client";

/** One agent a new rule can be limited to. */
export type ScopeAgent = { slug: string; name: string };

/**
 * Which agents a new rule applies to: one agent (the current one by default) or
 * every agent. `value` is the agent's slug, or "" for every agent.
 */
export function AgentScope({
  agents,
  value,
  onChange,
  disabled,
  id = "rule-scope",
}: {
  agents: ScopeAgent[];
  value: string;
  onChange: (slug: string) => void;
  disabled?: boolean;
  id?: string;
}) {
  return (
    <div className="k-field">
      <label htmlFor={id}>Applies to</label>
      <div className="k-form" style={{ gap: 4 }}>
        <select id={id} className="k-select" value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} style={{ maxWidth: 360 }}>
          {agents.map((a) => (
            <option key={a.slug} value={a.slug}>
              Only {a.name}
            </option>
          ))}
          <option value="">Every agent</option>
        </select>
        <p className="k-help">
          {value ? "Other agents are not affected." : "Every agent in the workspace, including ones added later."}
        </p>
      </div>
    </div>
  );
}
