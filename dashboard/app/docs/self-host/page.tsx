import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Output, Step, Steps } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Self-hosting",
  description: "Run the gateway and dashboard yourself: a Python app, Docker Compose, or Render.",
  path: "/docs/self-host",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Operate</p>
      <h1>Self-hosting</h1>
      <p className="docs-lede">
        Run the gateway, the control-plane API and the dashboard on your own infrastructure,
        with Postgres, real authentication and your own signing key.
      </p>

      <h2>When to use this</h2>
      <p>
        When more than one person or process needs the same AgentFox: a dashboard for the
        team, the gateway for agents in other languages, approvals decided by someone other
        than the developer. For one developer on a laptop, the local SQLite database from{" "}
        <Link href="/docs/install">Install and configure</Link> is enough.
      </p>
      <p>
        There is no licence check, no phone-home and no default egress. A fresh deployment
        runs with <code>AGENTFOX_ALLOW_EGRESS=false</code> and the offline <code>echo</code>{" "}
        provider, so it works end to end with no model and no key.
      </p>

      <h2>Three ways to run it</h2>
      <table>
        <thead>
          <tr>
            <th>Option</th>
            <th>What runs</th>
            <th>Use when</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><a href="#python">Python app</a></td>
            <td>The gateway under uvicorn, your database</td>
            <td>You already run Python services and want no containers.</td>
          </tr>
          <tr>
            <td><a href="#compose">Docker Compose</a></td>
            <td>Postgres, gateway, dashboard, optional OPA</td>
            <td>One machine, everything included.</td>
          </tr>
          <tr>
            <td><a href="#render">Render</a></td>
            <td>Postgres, gateway, dashboard from <code>render.yaml</code></td>
            <td>A managed host, from the repository&apos;s blueprint.</td>
          </tr>
        </tbody>
      </table>

      <h2 id="secrets">Settings every deployment must change</h2>
      <table>
        <thead>
          <tr>
            <th>Setting</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>AGENTFOX_ENVIRONMENT=production</code></td>
            <td>
              With <code>auth_mode</code> left at <code>auto</code>, this makes the API require
              tokens and refuse the development identity header.
            </td>
          </tr>
          <tr>
            <td><code>AGENTFOX_AUDIT_SIGNING_KEY</code></td>
            <td>
              Signs the audit chain&apos;s checkpoints. The default is a published string, so
              the gateway refuses to start outside development without this. Keep it
              outside the application database; rotating it ends verification of
              checkpoints signed before.
            </td>
          </tr>
          <tr>
            <td><code>AGENTFOX_DATABASE_URL</code></td>
            <td>Postgres for anything with more than one worker. SQLite is refused for a multi-worker server.</td>
          </tr>
          <tr>
            <td><code>AGENTFOX_SERVICE_AUTH_SECRET</code></td>
            <td>
              Required outside development, even without GitHub sign-in: the default is
              published, and it authenticates the call that mints an owner token, so the
              gateway refuses to start on it. Identical on the gateway and the dashboard.
            </td>
          </tr>
          <tr>
            <td><code>AGENTFOX_TOKEN_ENCRYPTION_KEY</code></td>
            <td>Only for connecting GitHub repositories. Without it that feature fails closed.</td>
          </tr>
        </tbody>
      </table>
      <p>
        Generate the two secrets:
      </p>
      <Code>{`python3 -c "import secrets; print(secrets.token_urlsafe(48))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`}</Code>
      <p>
        Every setting is on <Link href="/docs/reference/config">Configuration</Link>. The
        pre-rename <code>NOMETRIA_*</code> names are no longer read; the gateway and the
        dashboard log a warning naming any that are still set.
      </p>

      <h2 id="python">The gateway as a Python app</h2>
      <Steps>
        <Step title="Install with the Postgres extra">
          <Code>{`pip install "agentfox[postgres]"
export AGENTFOX_DATABASE_URL="postgresql+psycopg://agentfox:PASSWORD@db.internal:5432/agentfox"
export AGENTFOX_ENVIRONMENT=production
export AGENTFOX_AUDIT_SIGNING_KEY="…your generated value…"
export AGENTFOX_SERVICE_AUTH_SECRET="…another generated value…"`}</Code>
        </Step>
        <Step title="Create the schema and load the catalog">
          <Code>{`agentfox init`}</Code>
          <p>
            Creates and migrates the schema and loads the controls and packs. Run it once per
            database; it is idempotent.
          </p>
        </Step>
        <Step title="Start it">
          <Code>{`uvicorn agentfox.apps.gateway.app:app --host 0.0.0.0 --port 8080`}</Code>
          <p>
            Or <code>agentfox serve --host 0.0.0.0 --port 8080</code>, which runs the same
            app. Check it:
          </p>
          <Code>{`curl -s http://localhost:8080/api/health`}</Code>
          <Output>{`{"status":"ok","version":"0.3.1","governance_healthy":true,"degradation":{"healthy":true,"degraded_controls":{},"note":"healthy means every control ran, not that requests succeeded — a fail-open system reports success while checking nothing","fail_mode":"open",…}}`}</Output>
          <p>
            <code>/health</code> answers the same. <code>governance_healthy</code> is about the
            controls, not the HTTP server: a degraded detector shows up there while requests
            still succeed.
          </p>
        </Step>
        <Step title="Create an operator and a token">
          <p>
            The API under <code>/api</code> requires a token in production. A token is minted
            for an operator that already exists, and a database created by{" "}
            <code>init</code> has none. Create the first one; no demo data is loaded:
          </p>
          <Code>{`agentfox admin users create ops@example.com --role owner`}</Code>
          <Output>{`created ops@example.com · owner · org org_default
  Next: agentfox admin auth issue ops@example.com`}</Output>
          <Code>{`agentfox admin auth issue ops@example.com --name dashboard`}</Code>
          <Output>{`╭─ Token issued — copy it now ─────────────────────────────────────────────────────────────────────╮
│ nom_api_…                                                                                        │
│                                                                                                  │
│ dashboard · ops@example.com · owner · org org_default                                            │
│ expires 2027-10-05T15:06:06.434557+00:00                                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
  Only a hash is stored. There is no way to show this value again — issue a new token if it is lost.
…`}</Output>
          <p>Against a production gateway, the header is refused and the token works:</p>
          <Code>{`curl -s -o /dev/null -w "%{http_code}\\n" -H "X-AgentFox-User: admin@example.com" http://localhost:8080/api/findings
curl -s -o /dev/null -w "%{http_code}\\n" -H "Authorization: Bearer $AGENTFOX_TOKEN" http://localhost:8080/api/findings`}</Code>
          <Output>{`401
200`}</Output>
          <Code>{`agentfox admin auth status`}</Code>
          <Output>{`╭─ Authentication: enforced ───────────────────────────────────────────────────────────────────────╮
│ API tokens required.                                                                             │
│                                                                                                  │
│ environment = production · auth_mode = auto                                                      │
│ The development identity header is refused.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯`}</Output>
          <p>
            Sign in to the dashboard with the same token: on <code>/login</code>, open
            &quot;Self-hosted? Sign in with an API token&quot;. Signing out revokes it.
          </p>
          <p>
            The <code>/v1/guard/*</code> routes and the model proxy read no operator
            credential; they identify the agent, and an agent key that does not verify is a
            401. Keep the gateway on a private network.
          </p>
        </Step>
      </Steps>
      <p>
        To keep it running across reboots on Linux, the{" "}
        <a href="https://github.com/architsharm/agentfox/blob/main/docs/deployment/systemd.md">systemd guide</a>{" "}
        runs the gateway as a user service, with schema upgrades as a separate one-shot unit.
      </p>

      <h2 id="compose">Docker Compose</h2>
      <Code>{`git clone https://github.com/architsharm/agentfox.git && cd agentfox
export AGENTFOX_SERVICE_AUTH_SECRET="$(openssl rand -hex 32)"
export AGENTFOX_AUDIT_SIGNING_KEY="$(openssl rand -hex 32)"   # keep a copy
docker compose -f deploy/docker-compose.yml up -d`}</Code>
      <p>
        Both secrets are required: compose stops with an error naming the missing one, and
        the gateway would refuse to start on a published value anyway.
      </p>
      <p>
        Four services: <code>db</code> (Postgres 16), <code>gateway</code> on port 8080,{" "}
        <code>dashboard</code> on port 3000, and <code>opa</code> on 8181, which is optional
        (<code>AGENTFOX_POLICY_ENGINE</code> stays <code>native</code> unless you change it).
        Compose pulls <code>ghcr.io/architsharm/agentfox/gateway:latest</code> and{" "}
        <code>…/dashboard:latest</code>. <code>docker compose -f deploy/docker-compose.yml build</code>{" "}
        builds from source instead; the gateway build downloads 1–2GB of permissive-licence
        detector weights into the image so the running container never fetches them.
      </p>
      <p>What the compose file sets on the gateway, and what to change:</p>
      <table>
        <thead>
          <tr>
            <th>Variable</th>
            <th>Compose value</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>
          <tr><td><code>AGENTFOX_DATABASE_URL</code></td><td><code>postgresql+psycopg://agentfox:agentfox@db:5432/agentfox</code></td><td>Change the password here and on <code>db</code>.</td></tr>
          <tr><td><code>AGENTFOX_ENVIRONMENT</code></td><td><code>production</code></td><td>Tokens required (see below).</td></tr>
          <tr><td><code>AGENTFOX_ALLOW_EGRESS</code></td><td><code>&quot;false&quot;</code></td><td>Set true, plus a key, to use a hosted model.</td></tr>
          <tr><td><code>AGENTFOX_ENABLED_DETECTORS</code></td><td>the five defaults plus <code>injection.classifier</code>, <code>safety.granite</code>, <code>injection.similarity</code></td><td>The image carries their weights.</td></tr>
          <tr><td><code>AGENTFOX_ENFORCEMENT_BUDGET_MS</code></td><td><code>&quot;100&quot;</code></td><td>Lower than the 300 default; with the classifiers on, long inputs can exceed it and fail open.</td></tr>
          <tr><td><code>AGENTFOX_AUDIT_SIGNING_KEY</code></td><td>from your shell (required)</td><td>Keep a copy outside the database.</td></tr>
          <tr><td><code>AGENTFOX_SERVICE_AUTH_SECRET</code></td><td>from your shell (required)</td><td>Also given to the dashboard.</td></tr>
          <tr><td><code>AGENTFOX_EVIDENCE_DIR</code></td><td><code>/var/agentfox/evidence</code></td><td>On the <code>evidence</code> volume.</td></tr>
        </tbody>
      </table>
      <p>
        The gateway loads no demo data. Create the first operator and a token in the
        running container, then sign in on <code>http://localhost:3000/login</code> under
        &quot;Self-hosted? Sign in with an API token&quot;:
      </p>
      <Code>{`docker compose -f deploy/docker-compose.yml exec gateway agentfox admin users create you@example.com --role owner --token`}</Code>
      <p>
        GitHub sign-in is optional: create an OAuth app with the callback{" "}
        <code>http://localhost:3000/api/auth/github/callback</code> and export{" "}
        <code>GITHUB_CLIENT_ID</code> and <code>GITHUB_CLIENT_SECRET</code> before{" "}
        <code>up</code>. Demo data only if you want it:{" "}
        <code>docker compose -f deploy/docker-compose.yml exec gateway agentfox admin seed</code>.
      </p>
      <Callout kind="warning" title="Not run for this page">
        The compose stack pulls images and was not run while writing this page; the steps
        above come from <code>deploy/docker-compose.yml</code> and <code>deploy/Dockerfile</code>,
        and the token requirement from running the same gateway code in production mode.
        If the dashboard shows authentication errors, the missing token is the first thing
        to check.
      </Callout>
      <h3>The licence-gated Llama Guard tier</h3>
      <p>
        <code>safety.restricted</code> (Llama Guard 3-8B) carries a non-OSI licence. It is never
        in the published image and is off by default. To opt in, after your own licence
        review:
      </p>
      <ol>
        <li>accept Meta&apos;s licence for <code>meta-llama/Llama-Guard-3-8B</code> on Hugging Face;</li>
        <li>
          build the image yourself with that account&apos;s token, which bakes the weights in:{" "}
          <code>export HF_TOKEN=hf_…</code> then{" "}
          <code>docker compose -f deploy/docker-compose.yml build gateway</code> (the token is
          a build secret and does not end up in an image layer);
        </li>
        <li>add <code>&quot;safety.restricted&quot;</code> to <code>AGENTFOX_ENABLED_DETECTORS</code>;</li>
        <li>set <code>AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES</code> to <code>&quot;1&quot;</code>.</li>
      </ol>
      <p>Without the token the build skips that tier and everything else still builds.</p>

      <h2 id="render">Render</h2>
      <p>
        <code>render.yaml</code> at the repository root is a blueprint for a complete
        installation: <code>agentfox-db</code> (Postgres, free plan),{" "}
        <code>agentfox-gateway</code> (Docker, <code>starter</code> plan, because the image
        installs the classifier extra), and <code>agentfox-dashboard</code> (free plan). In
        Render: New, Blueprint, pick your fork. It prompts for <code>GITHUB_CLIENT_ID</code>{" "}
        and <code>GITHUB_CLIENT_SECRET</code>. (<code>deploy/render.yaml</code> is a different
        file that deploys only a dashboard against a hosted API; it is not a self-host.)
      </p>
      <Callout kind="warning" title="After the first deploy">
        <ul>
          <li>
            The blueprint generates <code>AGENTFOX_SERVICE_AUTH_SECRET</code> on the gateway
            and copies it to the dashboard. A deployment created from an older blueprint has
            it on the dashboard only, and its gateway now refuses to start on the default:
            sync the blueprint, or copy the dashboard&apos;s value to the gateway.
          </li>
          <li>
            Set <code>AGENTFOX_TOKEN_ENCRYPTION_KEY</code> on the gateway if users will connect
            GitHub repositories; the blueprint does not.
          </li>
        </ul>
      </Callout>
      <p>
        Then set the GitHub OAuth app&apos;s callback to{" "}
        <code>https://&lt;your-dashboard-host&gt;/api/auth/github/callback</code>, exactly,
        including the scheme. The blueprint asks for{" "}
        <code>AGENTFOX_AUDIT_SIGNING_KEY</code> once, on creation: paste a random value and
        keep a copy. A deployment made from an older blueprint has it as{" "}
        <code>NOMETRIA_AUDIT_SIGNING_KEY</code>; copy that value to the new name rather than
        generating a new one, or entries signed before the change stop verifying (the old
        name is no longer read). The dashboard runbook, including Fly.io, is{" "}
        <code>deploy/README-dashboard.md</code>.
      </p>

      <h2 id="upgrade">Upgrades</h2>
      <Code>{`pip install --upgrade "agentfox[postgres]"
agentfox admin db upgrade
agentfox admin db current`}</Code>
      <Output>{`…
migrated b8d3f6a2c915 → b8d3f6a2c915
schema revision: b8d3f6a2c915`}</Output>
      <p>
        Apply migrations before the new code serves traffic. The container&apos;s start command
        seeds but does not migrate an existing database, so for Compose and Render run{" "}
        <code>agentfox admin db upgrade</code> in the gateway container after pulling a new
        image. Take a database backup before any upgrade; <code>admin db downgrade</code> can
        drop columns.
      </p>

      <h2>After it is up</h2>
      <Code>{`agentfox doctor
agentfox admin auth status
agentfox report verify`}</Code>
      <p>
        Run these with the deployment&apos;s environment. <code>doctor</code> should show{" "}
        <code>✓ authentication  API tokens required; the identity header is refused</code>.
        Point agents at it as described in{" "}
        <Link href="/docs/guides/gateway">Any language: the gateway</Link>, and Python agents
        with <code>agentfox.auto()</code> at the same database.
      </p>

      <h2>Troubleshooting</h2>
      <table>
        <thead>
          <tr>
            <th>Symptom</th>
            <th>Cause and fix</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>401 on every <code>/api</code> call</td>
            <td>Production mode refuses the header. Use a token from <code>agentfox admin auth issue</code>.</td>
          </tr>
          <tr>
            <td><code>unknown user</code> when issuing a token</td>
            <td>No operator exists yet. <code>agentfox admin users create EMAIL --role owner</code>, then issue the token.</td>
          </tr>
          <tr>
            <td>GitHub sign-in returns 503 or fails at provisioning</td>
            <td><code>GITHUB_CLIENT_*</code> unset, or <code>service_auth_secret</code> differs between gateway and dashboard. Token sign-in on <code>/login</code> works without either.</td>
          </tr>
          <tr>
            <td>The playground shows &quot;Failed to fetch&quot;</td>
            <td>The browser origin is missing from <code>AGENTFOX_PLAYGROUND_CORS_ORIGIN</code> (comma-separated).</td>
          </tr>
          <tr>
            <td>Postgres: <code>cannot use a string pattern on a bytes-like object</code></td>
            <td>The database is <code>SQL_ASCII</code>. Create it as UTF-8.</td>
          </tr>
        </tbody>
      </table>

      <h2>Limits</h2>
      <ul>
        <li>One organisation per deployment, enforced at the database session. No SSO or OIDC yet.</li>
        <li>
          The fail-open budget and rate limits are per process, so N workers get N times the
          declared budget. Scale-out under load is untested.
        </li>
        <li>Background jobs run in process; there is no external queue.</li>
      </ul>
      <p>More on <Link href="/docs/limits">Limits</Link>.</p>

      <NextSteps
        items={[
          { href: "/docs/reference/config", label: "Configuration", why: "every setting the deployment reads" },
          { href: "/docs/guides/gateway", label: "Any language: the gateway", why: "connect agents to it" },
          { href: "/docs/app", label: "Tour of the web app", why: "what the dashboard shows" },
        ]}
      />
    </article>
  );
}
