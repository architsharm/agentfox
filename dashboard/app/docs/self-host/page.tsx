import type { Metadata } from "next";
import Link from "next/link";

import { Code, NextSteps, Step, Steps } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Self-host",
  description: "Run the AgentFox gateway and dashboard yourself: Docker Compose, Render, or a Python app.",
  path: "/docs/self-host",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Self-host</h1>
      <p className="docs-lede">
        Run the gateway, the dashboard and Postgres on your own machine or cloud, and sign in to your own
        copy of the app.
      </p>

      <p>
        Nothing phones home and nothing leaves by default: a fresh install has outbound calls switched
        off and answers with a built-in test model, so it works end to end with no model key.
      </p>

      <h2 id="compose">Docker Compose</h2>
      <Steps>
        <Step title="Get the code and make two secrets">
          <p>
            The gateway refuses to start without both. Keep a copy of the signing key outside the
            database: it is what makes the audit trail tamper-evident.
          </p>
          <Code>{`git clone https://github.com/architsharm/agentfox.git && cd agentfox
export AGENTFOX_SERVICE_AUTH_SECRET="$(openssl rand -hex 32)"
export AGENTFOX_AUDIT_SIGNING_KEY="$(openssl rand -hex 32)"`}</Code>
        </Step>

        <Step title="Start it">
          <p>
            This starts Postgres, the gateway on port 8080 and the dashboard on port 3000. Change the
            database password in <code>deploy/docker-compose.yml</code> before real use.
          </p>
          <Code>{`docker compose -f deploy/docker-compose.yml up -d`}</Code>
        </Step>

        <Step title="Create the first owner">
          <p>No demo data is loaded. This creates you as owner and prints a token, once.</p>
          <Code>{`docker compose -f deploy/docker-compose.yml exec gateway \\
  agentfox admin users create you@example.com --role owner --token`}</Code>
        </Step>

        <Step title="Sign in">
          <p>
            Open <code>http://localhost:3000/login</code>, choose{" "}
            <strong>Self-hosted? Sign in with an API token</strong> and paste the token. Signing out
            revokes it.
          </p>
        </Step>

        <Step title="Connect your agents to it">
          <p>
            Follow the <Link href="/docs/quickstart">Quickstart</Link> against your own dashboard, or
            point clients at <code>http://localhost:8080</code> as in{" "}
            <Link href="/docs/connect/http">Any language (HTTP)</Link>.
          </p>
        </Step>
      </Steps>

      <h2 id="render">Render</h2>
      <p>
        <code>render.yaml</code> at the repository root creates Postgres, the gateway and the dashboard.
        In Render choose <strong>New</strong>, <strong>Blueprint</strong>, and pick your fork. It asks for{" "}
        <code>AGENTFOX_AUDIT_SIGNING_KEY</code> once: paste a random value and keep a copy. It also asks
        for <code>GITHUB_CLIENT_ID</code> and <code>GITHUB_CLIENT_SECRET</code> for GitHub sign-in; set the
        OAuth app&apos;s callback to <code>https://&lt;dashboard-host&gt;/api/auth/github/callback</code>. Google and
        Microsoft sign-in are optional: set <code>GOOGLE_CLIENT_ID</code>/<code>GOOGLE_CLIENT_SECRET</code> or{" "}
        <code>MICROSOFT_CLIENT_ID</code>/<code>MICROSOFT_CLIENT_SECRET</code>, with callbacks at{" "}
        <code>/api/auth/google/callback</code> and <code>/api/auth/microsoft/callback</code>.
      </p>

      <h2 id="python">A Python app</h2>
      <p>If you already run Python services and want no containers:</p>
      <Code>{`pip install "agentfox[postgres]"
export AGENTFOX_DATABASE_URL="postgresql+psycopg://agentfox:PASSWORD@db.internal:5432/agentfox"
export AGENTFOX_ENVIRONMENT=production    # plus the two secrets above
agentfox init
agentfox serve --host 0.0.0.0 --port 8080`}</Code>
      <p>
        Then create the owner with <code>agentfox admin users create</code> as above. To keep it running
        on Linux, with scheduled jobs, use the{" "}
        <a href="https://github.com/architsharm/agentfox/blob/main/docs/deployment/systemd.md">systemd guide</a>.
      </p>

      <h2 id="upgrade">Upgrades</h2>
      <p>
        Back up the database, pull the new image or package, then migrate before the new version serves
        traffic. In Compose or Render, run this inside the gateway container:
      </p>
      <Code>{`agentfox admin db upgrade`}</Code>

      <p>
        Every setting, including models, detectors and outbound calls, is on{" "}
        <Link href="/docs/reference/config">Configuration</Link>. Before real traffic, go through the{" "}
        <Link href="/docs/production">Production checklist</Link>.
      </p>

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
            <td>refusing to start in environment &apos;production&apos;</td>
            <td>Set the variable it names to a random value, not a published default.</td>
          </tr>
          <tr>
            <td>401 on every <code>/api</code> call</td>
            <td>Production needs a token. Create one with <code>agentfox admin auth issue</code>.</td>
          </tr>
          <tr>
            <td>unknown user, when issuing a token</td>
            <td>No owner exists yet. Run <code>agentfox admin users create</code> first.</td>
          </tr>
          <tr>
            <td>GitHub sign-in fails</td>
            <td>
              <code>GITHUB_CLIENT_*</code> is unset, or <code>AGENTFOX_SERVICE_AUTH_SECRET</code> differs between
              gateway and dashboard. Token sign-in works without either.
            </td>
          </tr>
          <tr>
            <td>cannot use a string pattern on a bytes-like object</td>
            <td>The Postgres database is <code>SQL_ASCII</code>. Create it as UTF-8.</td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: "/docs/production", label: "Production checklist", why: "what to set before real traffic" },
          { href: "/docs/reference/config", label: "Configuration", why: "every setting" },
        ]}
      />
    </article>
  );
}
