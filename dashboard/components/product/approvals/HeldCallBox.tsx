/**
 * "When a call is held": who hears about it, how long it waits, and what happens
 * if nobody answers. A held refund used to expire as "Nobody answered" with no
 * sign anywhere that nobody had been told.
 *
 * Only what the gateway actually does. A held call is posted to the workspace's
 * Slack channel (Settings → Alerts, an Enterprise feature) when one is connected and
 * outbound messages are allowed; otherwise nobody is told and the line says where to
 * set it up. Every request waits `approval_ttl_minutes`
 * (AGENTFOX_APPROVAL_TTL_MINUTES, 30 by default), and an unanswered one follows its
 * `timeout_action`, which is `deny`.
 */
import Link from "next/link";
import { safeApi } from "@/lib/product/api";
import { DEFAULT_WAIT_MINUTES, minutesLabel, onExpiry, waitMinutes, type Approval } from "@/lib/product/approvals";

export async function HeldCallBox({ waiting }: { waiting: Approval[] }) {
  const slack = await safeApi<any>("/api/alerts/slack", { configured: false });
  // Sent to the tenant's channel or the deployment's, when messages may leave at all.
  const told = Boolean((slack.configured && slack.enabled !== false) || slack.deployment_channel) && slack.egress_allowed !== false;
  const carried = waiting.map(waitMinutes).find((m): m is number => m !== null);
  const wait = carried ?? DEFAULT_WAIT_MINUTES;
  const action = waiting.find((a) => a.timeout_action)?.timeout_action || "deny";

  return (
    <section className="k-card k-held-box" aria-label="When a call is held">
      <div className="k-card-body">
        <strong>When a call is held</strong>
        <dl className="k-held-facts">
          <div>
            <dt>Who is told</dt>
            <dd>
              {told ? (
                <>
                  Your <Link href="/app/settings?tab=alerts">Slack channel</Link>, and they wait here.
                </>
              ) : (
                <>
                  Nobody is notified. Held calls wait here.{" "}
                  <Link href="/app/settings?tab=alerts">{slack.configured ? "Allow outbound messages to post them to Slack" : "Post them to Slack"}</Link>
                </>
              )}
            </dd>
          </div>
          <div>
            <dt>How long it waits</dt>
            <dd>
              {minutesLabel(wait)}
              {carried === undefined ? " (the default)" : ""}
            </dd>
          </div>
          <div>
            <dt>If nobody answers</dt>
            <dd>{onExpiry(action).replace(/^./, (c) => c.toUpperCase())}.</dd>
          </div>
        </dl>
        <div className="k-muted" style={{ fontSize: "var(--t-micro)" }}>
          The wait is set on the gateway with <span className="k-mono">AGENTFOX_APPROVAL_TTL_MINUTES</span>.{" "}
          <Link href="/docs/govern/approvals">How approvals work</Link>
        </div>
      </div>
    </section>
  );
}
