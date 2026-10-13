import { Act } from "@/components/kit/Act";
import { Card, Empty, Pill } from "@/components/kit";
import { AccessCheckForm, AccessCheckTest } from "@/ee/AccessChecks";

/**
 * The workspace's own access checks (AgentFox Enterprise, BSL 1.1: see ee/LICENSE at the
 * repository root): each one, its state, and the form to add another.
 */
export function AccessChecksCard({ authorizers, canEdit }: { authorizers: any[]; canEdit: boolean }) {
  return (
    <Card
      title="Your access checks"
      hint="Your own RBAC service decides what the person an agent acts for may do. Matching tool calls are sent to it, with that person, before they run."
      flush
    >
      <ul className="k-list">
        {authorizers.map((a: any) => (
          <li key={a.key}>
            <div className="k-list-main">
              <span className="k-name">{a.name}</span>
              <span className="muted k-mono">{a.url}</span>
              <span className="muted">
                Decides {a.tools.join(", ")}
                {a.agents.length ? ` for ${a.agents.join(", ")}` : ""} · a no {a.on_deny === "escalate" ? "asks a person" : "blocks"} ·{" "}
                {a.fail_mode === "closed" ? "refuses calls when down" : "lets calls through when down"}
                {a.last_error ? <span className="k-act-error"> · Last error: {a.last_error}</span> : null}
              </span>
            </div>
            <div className="k-list-end">
              {a.enabled ? <Pill tone="ok">On</Pill> : <Pill tone="outline">Off</Pill>}
              {canEdit && (
                <>
                  <AccessCheckTest checkKey={a.key} tool={a.tools[0] || ""} />
                  <Act url={`/api/authorizers/${encodeURIComponent(a.key)}/enabled`} body={{ enabled: !a.enabled }} className="k-btn">
                    {a.enabled ? "Turn off" : "Turn on"}
                  </Act>
                  <Act url={`/api/authorizers/${encodeURIComponent(a.key)}`} method="DELETE" className="k-btn-ghost" confirm={`Remove ${a.name}? Tool calls stop being checked against it now.`}>
                    Remove
                  </Act>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
      {canEdit ? (
        <div style={{ padding: "8px 16px 14px" }}>
          <AccessCheckForm />
        </div>
      ) : (
        !authorizers.length && <Empty>No access checks yet.</Empty>
      )}
    </Card>
  );
}
