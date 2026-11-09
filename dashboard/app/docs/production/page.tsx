import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Production checklist",
  description:
    "What to set on a self-hosted AgentFox before real traffic: secrets, keys, Postgres, judge outages, alerts, scheduled jobs, backups and sign-in.",
  path: "/docs/production",
});

const REPO = "https://github.com/architsharm/agentfox/blob/main/docs/deployment";

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Production checklist</h1>
      <p className="docs-lede">
        Go through this list before a self-hosted AgentFox sees real traffic. Each row is one setting or
        one habit.
      </p>

      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>Check</th>
            <th>What to set</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Production mode</td>
            <td>
              <code>AGENTFOX_ENVIRONMENT=production</code>. The API then needs a token and refuses the
              development identity header.
            </td>
          </tr>
          <tr>
            <td>Secrets</td>
            <td>
              <code>AGENTFOX_SERVICE_AUTH_SECRET</code> (same value on gateway and dashboard) and{" "}
              <code>AGENTFOX_AUDIT_SIGNING_KEY</code>, both random. The gateway will not start on a
              published default.
            </td>
          </tr>
          <tr>
            <td>Encryption key</td>
            <td>
              <code>AGENTFOX_TOKEN_ENCRYPTION_KEY</code>, a Fernet key. Stored secrets (GitHub
              connections, platform connections) are encrypted with it; without it those features are
              off.
            </td>
          </tr>
          <tr>
            <td>Database</td>
            <td>
              <code>AGENTFOX_DATABASE_URL</code> pointing at Postgres. SQLite is refused for a server with
              more than one worker.
            </td>
          </tr>
          <tr>
            <td>Judge outage</td>
            <td>
              Decide whether a request is denied when an AI judge does not answer. Per workspace:{" "}
              <strong>Settings</strong>, <strong>Detection</strong>, <strong>AI judges &amp; egress</strong>,{" "}
              <strong>Deny the request</strong>. For every workspace:{" "}
              <code>AGENTFOX_JUDGMENT_FAIL_CLOSED=true</code>. It is off by default.
            </td>
          </tr>
          <tr>
            <td>Alerts</td>
            <td>
              <strong>Settings</strong>, <strong>Alerts</strong>, <strong>Slack</strong>, or{" "}
              <code>AGENTFOX_WEBHOOK_URL</code> for new issues. Both need{" "}
              <code>AGENTFOX_ALLOW_EGRESS=true</code>.
            </td>
          </tr>
          <tr>
            <td>Scheduled jobs</td>
            <td>
              Run <code>agentfox admin jobs run-due</code> every 10 to 30 minutes from cron or a systemd
              timer. Monitors, drift and compliance checks only run when it does.
            </td>
          </tr>
          <tr>
            <td>Backups</td>
            <td>
              Back up Postgres with your provider or <code>pg_dump</code>, and always before an upgrade.
              Keep the signing and encryption keys somewhere else: a backup without the encryption key
              cannot decrypt its stored secrets.
            </td>
          </tr>
          <tr>
            <td>Sign-in</td>
            <td>
              Operators sign in with an API token or GitHub. There is no SSO, OIDC or SCIM yet, and one
              organisation per deployment.
            </td>
          </tr>
          <tr>
            <td>Guardrails</td>
            <td>
              New guardrails watch first. <Link href="/docs/protect">Switch them to Block</Link> once you
              have read what they would have stopped.
            </td>
          </tr>
        </tbody>
      </table></div>

      <h2>Rotate a key</h2>
      <p>
        Put the new value in the variable and the old one in the same name with{" "}
        <code>_PREVIOUS</code> (for example <code>AGENTFOX_TOKEN_ENCRYPTION_KEY_PREVIOUS</code>), restart,
        then re-encrypt. Remove the <code>_PREVIOUS</code> variables once status says{" "}
        <code>complete</code>. The full steps are in the{" "}
        <a href={`${REPO}/key-rotation.md`}>key rotation guide</a>.
      </p>
      <Code>{`agentfox admin keys rotate
agentfox admin keys status`}</Code>

      <h2>Check it</h2>
      <p>Run these with the deployment&apos;s environment:</p>
      <Code>{`agentfox doctor
agentfox admin auth status
agentfox report verify`}</Code>
      <p>
        <code>doctor</code> should say API tokens are required. <code>report verify</code> checks the audit
        trail has not been changed.
      </p>

      <Callout kind="note" title="Running on Linux">
        <p>
          The <a href={`${REPO}/systemd.md`}>systemd guide</a> runs the gateway as a service, migrations as
          a one-shot unit, and the scheduled jobs on a timer.
        </p>
      </Callout>

      <NextSteps
        items={[
          { href: "/docs/reference/config", label: "Configuration", why: "every setting named here, and the rest" },
          { href: "/docs/prove/integrations", label: "Send traces elsewhere", why: "OpenTelemetry and SIEM export" },
        ]}
      />
    </article>
  );
}
