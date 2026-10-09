import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Start here and connect",
  description:
    "The Start here checklist and what completes each step, connecting a GitHub repository or a hosted API, and minting, copying and revoking API tokens.",
  path: "/docs/app/start",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Web app</p>
      <h1>Start here and connect</h1>
      <p className="docs-lede">
        Get started walks a new workspace from an empty dashboard to an enforcing one, all in
        the browser. Settings → Connections lists every way in, and Settings → API keys holds
        the keys for agents, the CLI, the SDK and scripts.
      </p>
      <InTheApp path="/app/start">Get started</InTheApp>

      <h2>When to use this</h2>
      <ul>
        <li>On a new workspace, to see what is not set up yet. GitHub sign-in lands you on Connect.</li>
        <li>To find the agents already in a repository or behind an API, without running anything.</li>
        <li>To get a token for a CI job or a script that calls the gateway.</li>
      </ul>

      <h2>Get started</h2>
      <p>
        <code>/app/start</code>. Six steps, each finished in the browser, with the same step
        from the command line underneath. Every step is computed from the database on each
        load by <code>GET /api/onboarding</code>; nothing is stored as &quot;done&quot;, so the
        list cannot disagree with the system. The first unfinished step opens marked{" "}
        <strong>Next</strong>, and also appears at the top of Overview.
      </p>
      <table>
        <thead>
          <tr>
            <th>Step</th>
            <th>Done when</th>
            <th>The page offers</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Register your agent</td>
            <td>At least one agent exists.</td>
            <td>An id and name form, and a picker for which agent the later steps are about.</td>
          </tr>
          <tr>
            <td>Create an API key</td>
            <td>A live API key exists, other than a GitHub sign-in session.</td>
            <td>A button that mints a key and shows it once, with a copy button and the export line.</td>
          </tr>
          <tr>
            <td>Send the first request</td>
            <td>At least one trace has been recorded.</td>
            <td>
              Snippets for HTTP, Python, TypeScript, an OpenAI-compatible client, Claude Code,
              Codex and OpenTelemetry, with the gateway URL and agent filled in. <strong>Send a
              test request</strong> runs one message check through the gateway as that agent
              (with the new key, if one was just created) and shows the verdict and a link to
              the trace.
            </td>
          </tr>
          <tr>
            <td>Grant tools and choose protections</td>
            <td>A tool grant exists, or an agent has its own protection layer.</td>
            <td>
              <strong>Protect</strong> opens the agent&apos;s protection wizard;{" "}
              <strong>Grant tools</strong> opens its Access tab.
            </td>
          </tr>
          <tr>
            <td>Declare what your agent can answer</td>
            <td>At least one knowledge boundary exists.</td>
            <td>A link to the boundary form on the agent&apos;s Access tab (<Link href="/docs/app/agents#boundary">Knowledge boundary</Link>).</td>
          </tr>
          <tr>
            <td>Turn enforcement on</td>
            <td>
              The <code>baseline</code> pack (injection, PII, safety) is bound in enforce mode.
            </td>
            <td>The same <strong>Start enforcing</strong> control as Policies, which simulates first.</td>
          </tr>
        </tbody>
      </table>
      <Callout kind="note">
        Tool containment enforces from install; the last step is about the content policies,
        which start in observe. The trace and decision counts on this page are counted up to
        10,000 and shown as &quot;10,000+&quot; beyond that.
      </Callout>

      <h2 id="connect">Connect</h2>
      <InTheApp path="/app/start?tab=connect">Settings → Connections</InTheApp>
      <p>
        One card per way in, each with its status and one action: <strong>Gateway</strong>{" "}
        (the API base and the OpenAI-compatible base URL), <strong>GitHub</strong>,{" "}
        <strong>Hosted API</strong>, <strong>SDK</strong> (Python, TypeScript, HTTP),{" "}
        <strong>Coding agents</strong> (Claude Code, Codex) and <strong>OpenTelemetry</strong>{" "}
        (OTLP/HTTP ingest at <code>/v1/traces</code>, observe only). A card whose action is a
        snippet or a form opens in place.
      </p>
      <p>
        GitHub and Hosted API find <em>agents</em>. For the data they read, see{" "}
        <Link href="/docs/app/access-and-sources#sources">Verified sources</Link>. Both are
        read-only, and what they propose is inert until a person approves it on Agents and
        Policies.
      </p>

      <h3>A GitHub repository</h3>
      <p>
        Until GitHub is connected, the tab shows a <strong>Connect GitHub</strong> button. It
        is the same OAuth flow as sign-in. Once connected, the tab lists every repository the
        GitHub account can see, with a filter box, an account column (company or personal),
        the default branch, when it was last updated, and whether it has already been scanned.
        <strong> Scan</strong> (or <strong>Scan again</strong>) posts the repository and its
        default branch to <code>POST /api/integrations/github/scan</code>.
      </p>
      <p>
        The gateway downloads the archive of that branch, runs the same static scan as{" "}
        <Link href="/docs/reference/cli#cmd-scan-repo">agentfox scan repo</Link> on it (source
        is parsed, never imported or executed), and deletes it. The result appears at the top
        of the tab: frameworks detected, and how many agents and policies were proposed, with
        links to review them. Proposed agents appear as <strong>Pending review</strong> drafts
        on Agents; proposed policies appear on Policies already in observe mode. The{" "}
        <strong>reconnect</strong> link re-runs the GitHub grant.
      </p>
      <p>
        A scanned repository is then monitored: it is scanned again every six hours (and on
        every push once the GitHub webhook is registered), and what changed becomes a
        finding. The scan response&apos;s summary carries the <code>monitor_id</code>. See{" "}
        <Link href="/docs/guides/monitoring">Monitor connected sources</Link>.
      </p>
      <p>
        The scope GitHub is asked for is <code>repo</code>, which includes private
        repositories. That is what lets the scan download one.
      </p>

      <h3>A hosted API</h3>
      <p>
        <strong>Point us at a hosted API</strong> needs no repository access. The form has four
        fields: <strong>API endpoint</strong> (required), <strong>OpenAPI / Swagger spec URL</strong>,{" "}
        <strong>Docs URL</strong> and <strong>What does it do?</strong>. <strong>Connect &amp; scan</strong>{" "}
        posts them to <code>POST /api/integrations/hosted-api/scan</code>. The gateway fetches
        the spec document, never the API itself, turns each operation into a tool, and
        proposes one draft agent named after the host and one observe-mode policy. With no
        spec URL, the endpoint is still registered as a draft agent with no known operations.
        With one, the spec is then fetched again every six hours and new operations, new
        destructive ones above all, become findings (the summary&apos;s{" "}
        <code>monitor_id</code>).
      </p>
      <p>
        The spec URL must be <code>http</code> or <code>https</code> and resolve to a public
        address; every redirect is checked the same way. Loopback and private-network
        addresses are refused unless the gateway runs with{" "}
        <code>AGENTFOX_OUTBOUND_ALLOW_PRIVATE_HOSTS=true</code>, for a self-hosted
        deployment whose spec lives on its own network. Link-local addresses, including the
        cloud metadata address <code>169.254.169.254</code>, are always refused.
      </p>
      <p>
        The same call over HTTP, against a local gateway&apos;s own OpenAPI document (started
        with <code>AGENTFOX_OUTBOUND_ALLOW_PRIVATE_HOSTS=true</code>, since the spec is on
        loopback):
      </p>
      <Code>{`curl -s -X POST http://127.0.0.1:8080/api/integrations/hosted-api/scan \\
  -H "Authorization: Bearer $AGENTFOX_API_TOKEN" -H 'Content-Type: application/json' \\
  -d '{"endpoint_url":"http://127.0.0.1:8080","openapi_spec_url":"http://127.0.0.1:8080/openapi.json","purpose":"local test"}'`}</Code>
      <Output>{`{"scan_run_id":"scn_01m469kx28t61akkj5","status":"completed","summary":{"endpoint_url":"http://127.0.0.1:8791","sites":{"tool":182},"agents_proposed":["127-0-0-1"],"policies_proposed":["scan-scn_01m469kx28t61akkj5-hosted-api"]},"agent":"127-0-0-1"}`}</Output>
      <p>
        The tab then shows &quot;Scan of http://127.0.0.1:8080 · completed · Operations
        found: 182 · Proposed: 1 agent(s), 1 policy/ies&quot;. (The output above was captured
        against a gateway on port 8791.)
      </p>

      <h3>A scan from your own machine</h3>
      <p>
        <code>agentfox scan repo</code> with <code>--submit</code> sends the redacted result
        of a local scan to the workspace, using a token from the next section. The
        proposals land in the same review queues.
      </p>
      <Code>{`export AGENTFOX_API_URL=http://127.0.0.1:8080
export AGENTFOX_API_TOKEN=nom_api_…
agentfox scan repo ./support_bot --submit`}</Code>
      <Output>{`…
Submitted. scan scn_01m469n3ft87ygcgz3 — 0 draft agent(s), 2 proposed polic(ies)
— review them in the dashboard.`}</Output>

      <h2 id="tokens">API tokens</h2>
      <InTheApp path="/app/start?tab=tokens">Start here → API tokens</InTheApp>
      <p>
        A token acts as you, with your role, in your workspace. Use it as{" "}
        <code>Authorization: Bearer nom_api_…</code> on any <code>/api/…</code> route, or set
        it as <code>AGENTFOX_API_TOKEN</code> for <code>agentfox scan repo --submit</code>.
      </p>
      <ul>
        <li>
          <strong>Generate a token</strong>: give it a name that says what it is for (&quot;CI
          runner&quot;), then <strong>Generate token</strong>. Unnamed tokens are called{" "}
          <code>self-service</code>. Calls <code>POST /api/tokens</code>.
        </li>
        <li>
          <strong>Your new token — copy it now</strong>: the full value, with a{" "}
          <strong>Copy to clipboard</strong> button. Only a hash is stored. Leave the page and
          it is gone; revoke it and generate another.
        </li>
        <li>
          <strong>The table</strong>: name, the first characters of the token, created,
          expiry countdown, active or revoked. Every GitHub sign-in adds a row named{" "}
          <code>github-login</code>. Listed by <code>GET /api/tokens</code>.
        </li>
        <li>
          <strong>Revoke</strong> takes effect on the next request:{" "}
          <code>POST /api/tokens/&#123;id&#125;/revoke</code>. There is no confirmation step.
        </li>
      </ul>
      <p>What a token minted here looks like to the gateway, then after Revoke:</p>
      <Code>{`curl -s http://127.0.0.1:8080/api/me -H "Authorization: Bearer $TOKEN"`}</Code>
      <Output>{`{"id":"usr_01m4697abjqq2fkwg0","email":"admin@example.com","name":"Admin","role":"owner","org_id":"org_default","workspace":"org_default"}`}</Output>
      <Output title="After Revoke">{`{"detail":"invalid, expired or revoked API token"}`}</Output>
      <p>
        On a self-hosted deployment the operator commands do the same against the database:
      </p>
      <Code>{`agentfox admin auth issue admin@example.com --name ci-runner --days 90
agentfox admin auth tokens
agentfox admin auth revoke tok_01m469mm9pt4qcfghd`}</Code>
      <Output title="agentfox admin auth tokens">{`  state     name            user            role     prefix         expires
  active    ci-runner       admin@examp…    owner    nom_api_kH…    2027-10-05
  active    dashboard-d…    admin@examp…    owner    nom_api_Z1…    2027-10-05`}</Output>
      <Callout kind="warning">
        Tokens minted in the web app last 365 days and there is no lifetime field. Use{" "}
        <code>agentfox admin auth issue --days</code> on a self-hosted deployment for a shorter
        one, and revoke CI tokens when the job no longer needs them.
      </Callout>
      <p>
        These are user tokens. An agent calling the guard API or the proxy authenticates with
        its own agent key; see <Link href="/docs/guides/gateway">the gateway guide</Link>.
      </p>

      <h2>Common tasks</h2>
      <TaskTable
        rows={[
          { task: "Scan a local checkout and send it to the workspace", run: "agentfox scan repo . --submit", href: "/docs/guides/scan-a-repo" },
          { task: "Mint a short-lived token (self-hosted)", run: "agentfox admin auth issue you@example.com --name ci --days 30" },
          { task: "List tokens (self-hosted)", run: "agentfox admin auth tokens" },
          { task: "Revoke a token (self-hosted)", run: "agentfox admin auth revoke TOKEN_ID" },
          { task: "Promote content policies once findings look right", run: "agentfox policy enforce baseline", href: "/docs/app/policies" },
        ]}
      />

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong>&quot;Scan failed: …&quot; at the top of Connect.</strong> The gateway could not
          download the repository (no GitHub connection, a revoked grant, an archive over the
          size limit) or could not fetch the spec. Use <strong>reconnect</strong>, or check the
          spec URL loads in a browser. &quot;refusing to fetch the spec&quot; means the URL
          resolves to a loopback, private or link-local address (see above).
        </li>
        <li>
          <strong>Connecting GitHub returns a 503.</strong> The gateway has no{" "}
          <code>AGENTFOX_TOKEN_ENCRYPTION_KEY</code>, and refuses to store the GitHub token
          unencrypted.
        </li>
        <li>
          <strong>The scan proposes nothing.</strong> It reads Python, TypeScript and
          JavaScript and recognises known frameworks. An agent behind a wrapper it does not
          know is invisible to it; govern it with the SDK instead.
        </li>
        <li>
          <strong>A hosted-API draft agent shows up as &quot;running and was never
          registered&quot;</strong> in the attention queue. It is a scan proposal; approve or
          reject it on Agents and the row goes away.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>
          The hosted-API scan fetches whatever URL you give it from the gateway&apos;s network,
          with no allow-list and regardless of <code>allow_egress</code>.
        </li>
        <li>Repository scans read the default branch only; there is no branch picker.</li>
        <li>Token lifetime is fixed at 365 days in the web app.</li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/app/agents", label: "Agents", why: "approve what a scan proposed" },
          { href: "/docs/guides/python-auto", label: "One line in Python", why: "record your first trace" },
          { href: "/docs/guides/scan-a-repo", label: "Audit a repository", why: "the scan in depth" },
          { href: "/docs/reference/api", label: "HTTP API", why: "everything a token can call" },
        ]}
      />
    </article>
  );
}
