import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Screenshot } from "@/components/docs/blocks";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Send traces elsewhere",
  description:
    "Connect AgentFox to the tools you already watch: OpenTelemetry, Langfuse, LangSmith, Prometheus, your SIEM, webhooks and Slack.",
  path: "/docs/prove/integrations",
});

const cfg = (anchor: string) => `/docs/reference/config#${anchor}`;

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Send traces elsewhere</h1>
      <p className="docs-lede">
        Get AgentFox&apos;s decisions and issues into the tools your team already watches, and your
        existing traces into AgentFox.
      </p>

      <div className="docs-table"><table>
        <thead>
          <tr>
            <th>Destination</th>
            <th>What you get</th>
            <th>Turn it on</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>OpenTelemetry (in)</td>
            <td>Agents you already trace show up for review, without code changes. Recorded, not checked.</td>
            <td>
              Point your OTLP/HTTP exporter at <code>&lt;server&gt;/v1/traces</code>.{" "}
              <strong>Settings → Connections → OpenTelemetry</strong> shows the setup.{" "}
              <Link href={cfg("otlp")}>Details</Link>
            </td>
          </tr>
          <tr>
            <td>Langfuse, LangSmith</td>
            <td>Find the AgentFox decision behind one of their traces, and tag their run with the verdict.</td>
            <td>
              Send calls through the proxy with their trace header. To tag runs, set{" "}
              <code>AGENTFOX_CORRELATION_PUSH=true</code> and their keys.{" "}
              <Link href={cfg("integrations")}>Details</Link>
            </td>
          </tr>
          <tr>
            <td>Prometheus</td>
            <td>Decisions, detector health and open issues as metrics.</td>
            <td>
              Scrape <code>&lt;server&gt;/metrics</code>. <Link href={cfg("metrics")}>Details</Link>
            </td>
          </tr>
          <tr>
            <td>SIEM (Splunk, ArcSight, QRadar)</td>
            <td>Decisions and issues as JSON lines, CEF, LEEF or OTLP logs.</td>
            <td>
              Fetch <code>&lt;server&gt;/api/export/siem?format=cef</code> on a schedule.{" "}
              <Link href={cfg("siem")}>Details</Link>
            </td>
          </tr>
          <tr>
            <td>Webhook</td>
            <td>A signed POST when an issue is raised, resolved or reopened.</td>
            <td>
              <code>AGENTFOX_WEBHOOK_URL</code> and <code>AGENTFOX_WEBHOOK_SECRET</code>.{" "}
              <Link href={cfg("webhooks")}>Details</Link>
            </td>
          </tr>
          <tr>
            <td>Slack (Enterprise)</td>
            <td>A message when monitoring opens or closes an issue.</td>
            <td>
              <strong>Settings → Alerts → Slack</strong>, or <code>AGENTFOX_SLACK_WEBHOOK_URL</code>.
            </td>
          </tr>
        </tbody>
      </table></div>

      <Screenshot {...SCREENS.integrations} />

      <Callout kind="note" title="Nothing leaves without egress">
        Webhooks, Slack and pushing verdicts to Langfuse or LangSmith send data out, so each needs{" "}
        <code>AGENTFOX_ALLOW_EGRESS=true</code>. Metrics, the SIEM export and OTLP ingest are on your
        server and need nothing extra.
      </Callout>

      <h2>Try a webhook</h2>
      <p>
        Set the variables on the server, restart it, and raise an issue (an agent nobody registered
        does it). Your receiver should check the <code>X-AgentFox-Signature</code> header: an
        HMAC-SHA256 of the raw body with your secret.
      </p>
      <Code>{`export AGENTFOX_ALLOW_EGRESS=true
export AGENTFOX_WEBHOOK_URL=https://hooks.example.com/agentfox
export AGENTFOX_WEBHOOK_SECRET=whsec_…
export AGENTFOX_WEBHOOK_MIN_SEVERITY=high`}</Code>

      <h2>Good to know</h2>
      <ul>
        <li>
          Spans sent to <code>/v1/traces</code> are recorded but not checked. To block, route calls
          through <Link href="/docs/connect/python">agentfox.auto()</Link> or{" "}
          <Link href="/docs/connect/http">the proxy</Link>.
        </li>
        <li>
          The <code>_total</code> metrics count the last 24 hours, so they can go down. Alert on the
          value, such as <code>agentfox_detector_degraded_total &gt; 0</code>, not on{" "}
          <code>rate()</code>.
        </li>
        <li>
          A webhook is retried once, then dropped. Use the SIEM export to backfill.
        </li>
        <li>
          Outside development, <code>/api/export/siem</code> and <code>/v1/traces</code> need a token
          or agent key. <code>/metrics</code> is open: keep it on a private network.
        </li>
      </ul>

      <h2>If something goes wrong</h2>
      <div className="docs-table"><table>
        <thead>
          <tr>
            <th>You see</th>
            <th>Do this</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>No webhook arrives</td>
            <td>
              Set <code>AGENTFOX_ALLOW_EGRESS=true</code>, and check the issue&apos;s severity against{" "}
              <code>AGENTFOX_WEBHOOK_MIN_SEVERITY</code>.
            </td>
          </tr>
          <tr>
            <td>
              <code>/v1/traces</code> returns 415
            </td>
            <td>
              Install <code>agentfox[otel]</code> on the server for protobuf, or export JSON.
            </td>
          </tr>
          <tr>
            <td>
              <code>/api/traces/resolve</code> returns 404
            </td>
            <td>The call did not go through the proxy with a Langfuse, LangSmith or <code>traceparent</code> header.</td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: cfg("integrations"), label: "Integration settings", why: "every variable, default and header" },
          { href: "/docs/prove/audit", label: "Audit evidence", why: "the same records as a package an auditor verifies" },
        ]}
      />
    </article>
  );
}
