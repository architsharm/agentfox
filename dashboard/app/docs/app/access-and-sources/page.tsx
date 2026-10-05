import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Access control and sources",
  description:
    "End-user entitlement (principals, grants, over-permission) and verified sources (tiers, database and API connections, validation, ingestion checks).",
  path: "/docs/app/access-and-sources",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Web app</p>
      <h1>Access control and sources</h1>
      <p className="docs-lede">
        Two pages about what an agent answers from: Access control says which person may see
        which source; Verified sources says which sources can be trusted at all.
      </p>

      <h2>When to use this</h2>
      <ul>
        <li>
          One agent serves many people, and a person must not see another&apos;s data through it
          (a shared support or HR assistant).
        </li>
        <li>
          Answers are grounded in documents and databases, and you need to know whether those
          are the master copy or somebody&apos;s notes, and whether they are still current.
        </li>
      </ul>
      <p>
        These are about end users and data. What an agent may <em>do</em> (call a tool) is a
        capability grant; see <Link href="/docs/guides/contain-tool-calls">Contain tool calls</Link>.
      </p>

      <h2>Access control</h2>
      <InTheApp path="/app/entitlement">Access control</InTheApp>
      <p>
        <code>/app/entitlement</code> loads <code>GET /api/entitlement/over-permission</code>,{" "}
        <code>/principals</code> and <code>/grants</code>. Entitlement is checked when your
        retrieval asks the gateway to filter candidates for a caller (
        <code>/api/entitlement/filter</code>); until something does, the page says
        &quot;Nobody is being checked yet&quot;.
      </p>
      <h3>Over-permission</h3>
      <p>
        Once checks run, four cards: the share of content held back because the caller was not
        cleared for it (this is not an error rate: it is what the agent could reach and
        correctly did not show), checks run in the window, distinct callers, and pieces of
        content evaluated. <strong>Why content was withheld</strong> breaks that down by reason.
      </p>
      <h3>Callers (principals)</h3>
      <p>
        <strong>+ Add a person or group</strong>: email or team name, display name, teams they
        belong to, and the sensitive categories they are cleared to see. Saved with{" "}
        <code>PUT /api/entitlement/principals</code>. The table shows subject, groups,
        clearances and data residency.
      </p>
      <h3>Grants</h3>
      <p>
        <strong>+ Add a grant</strong>: which source (the same key as on Verified sources), which
        person or team (must match a principal), and which sensitive categories the grant
        covers: sensitive personal data (<code>pii_sensitive</code>), insider financial
        information (<code>mnpi</code>), under legal hold, blackout-period restricted,
        insider-only. Saved with <code>POST /api/entitlement/grants</code>.
      </p>
      <ul>
        <li>Default deny: a resource with no grant is invisible to every caller.</li>
        <li>A grant does not open a restricted category on its own; the caller also needs the matching clearance.</li>
        <li>
          The web form always records the grantee as a <code>group</code>. To grant to one
          person by subject, use <code>agentfox permit user … --kind subject</code>.
        </li>
      </ul>
      <Code>{`agentfox declare principal bob@example.com --groups support-team
agentfox permit user "kb/*" support-team
agentfox report entitlement`}</Code>
      <Output>{`✓ principal bob@example.com
  groups: support-team
✓ support-team → kb/*
╭─ No entitlement decisions ─────────────────────────────────────────────────────╮
│ No access checks recorded yet — until the agent is told who's asking, it can't │
│ know whether they're cleared to see the answer.                                │
╰────────────────────────────────────────────────────────────────────────────────╯
  Register a principal with \`agentfox declare principal <subject>\`, then filter retrieval through
/api/entitlement/filter.`}</Output>

      <h2 id="sources">Verified sources</h2>
      <InTheApp path="/app/sources">Verified sources</InTheApp>
      <p>
        <code>/app/sources</code> loads <code>GET /api/sources</code> and{" "}
        <code>/api/sources/health</code>. A tier is a person&apos;s claim about a source;
        validation is AgentFox fetching it and checking the content is still what it was.
      </p>
      <ul>
        <li>
          A bar shows how many sources sit in each tier: <code>system_of_record</code>,{" "}
          <code>approved</code>, <code>unverified</code>, <code>external</code>. A card appears
          when sources are past their freshness SLA; a note when deprecated or unowned sources
          remain.
        </li>
        <li>
          <strong>Registered sources</strong>: tier, key (with <code>deprecated</code> and{" "}
          <code>sample data</code> tags), connection (Database, Enterprise API / KB, plain URL, or
          none), owner, domain, freshness (fresh or stale against its SLA), content check, and an
          actions menu (<strong>⋯</strong>).
        </li>
      </ul>
      <h3>Add a source</h3>
      <p>
        <strong>+ Add a source</strong> asks what you are adding:
      </p>
      <ul>
        <li><strong>Just a name</strong>: register it now with a tier, connect it later.</li>
        <li>
          <strong>Database</strong>: PostgreSQL, MySQL, SQL Server or SQLite; host, port, database,
          username, password, and optionally a table to fingerprint (otherwise every table name
          is used) so schema drift is detected.
        </li>
        <li>
          <strong>API or knowledge base</strong>: Confluence, SharePoint, Notion or any
          authenticated REST endpoint; the URL to check, the auth header name (default{" "}
          <code>Authorization</code>), a prefix (default <code>Bearer </code>) and the token.
        </li>
      </ul>
      <p>
        Every type asks for the name your team uses, the tier (&quot;Official company data, kept
        up to date&quot; through &quot;Someone&apos;s personal notes, or an outside source&quot;),
        the owner&apos;s email and how often it is updated (daily, weekly, monthly, rarely). Submit
        registers it with <code>PUT /api/sources</code> and, for a database or API, attaches the
        connection with <code>POST /api/sources/connections</code>. If the connection fails, the
        source stays registered and the error says so.
      </p>
      <h3>The actions menu</h3>
      <ul>
        <li>
          <strong>Edit details</strong>: tier, owner, domain, freshness SLA (only for sources
          something can re-read), and un-deprecate.
        </li>
        <li>
          <strong>Connect a database or API</strong> / <strong>Reconnect</strong>: for a source
          that is a bare name, or to re-point one. Not offered for an <code>http(s)</code> key,
          which is fetched directly.
        </li>
        <li>
          <strong>Validate now</strong> (<code>POST /api/sources/&#123;key&#125;/validate</code>):
          fetch and compare. The content check column then reads content verified, content
          changed since last check, or could not fetch. A bare name with no connection cannot be
          validated and the menu says so.
        </li>
        <li>
          <strong>Deprecate</strong> (<code>DELETE /api/sources/&#123;key&#125;</code>): keep the
          record as &quot;do not trust&quot;; every answer grounded in it raises a finding.
        </li>
        <li>
          <strong>Delete permanently</strong>, offered only once deprecated (
          <code>?hard=true</code>): removes the record and with it the do-not-trust signal, so an
          answer grounded in it afterwards looks unverified rather than flagged.
        </li>
      </ul>
      <Code>{`agentfox declare source ticket-history --tier system_of_record --owner support-ops@example.com --sla-hours 24
agentfox declare list sources`}</Code>
      <Output>{`✓ ticket-history → system_of_record
  ! a 24h SLA is set but no update time is recorded, so this reads as stale. Pass --updated when the
source changes.
  tier                source                  owner                      domain     state
  approved            crm-notes               priya@example.com          support    ok
  system_of_record    help-center-articles    priya@example.com          support    ok
  system_of_record    ticket-history          support-ops@example.com    —          age unknown`}</Output>
      <p>
        For a whole corpus, <code>agentfox declare import-sources sources.json</code> registers
        a JSON list in one go. (The empty-state text in the app shows the older command name.)
      </p>

      <h3>Check ingestion quality</h3>
      <p>
        At the foot of the page, not tied to a registered source. <strong>Check one
        document</strong> takes extracted text and looks for encoding damage, mojibake,
        unbalanced code fences and words glued together by a lost space.{" "}
        <strong>Check chunk boundaries</strong> takes chunks separated by blank lines and looks
        for orphan fragments, mid-sentence splits and headings with no body. Both call{" "}
        <code>POST /api/sources/context-check</code>.
      </p>
      <Output title="POST /api/sources/context-check, one document">{`{"document":{"score":0.9,"usable":true,"findings":[{"code":"control-characters","detail":"3.5% of the document is control or private-use characters, which usually means a binary was read as text","severity":"warn","evidence":{"printable_ratio":0.9649},"verdict":"allow"}]}}`}</Output>

      <h2>Common tasks</h2>
      <TaskTable
        rows={[
          { task: "Register the person an agent acts for", run: "agentfox declare principal alice@example.com --groups support-team --clearances pii_sensitive" },
          { task: "Grant a group a resource pattern", run: "agentfox permit user \"kb/*\" support-team" },
          { task: "Grant one person", run: "agentfox permit user ticket-history alice@example.com --kind subject" },
          { task: "How much more the agent reaches than callers may see", run: "agentfox report entitlement" },
          { task: "Tier a source", run: "agentfox declare source ticket-history --tier system_of_record" },
          { task: "List sources and their state", run: "agentfox declare list sources" },
        ]}
      />

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong>Access control stays on &quot;Nobody is being checked yet&quot;.</strong>{" "}
          Principals and grants alone do nothing; your retrieval must pass candidates through
          the entitlement filter with the caller&apos;s identity. See{" "}
          <Link href="/docs/guides/rag">Retrieval and answers</Link>.
        </li>
        <li>
          <strong>A grant has no effect.</strong> The principal name in the grant must match a
          registered principal or one of its groups exactly, and the resource must match the
          source key.
        </li>
        <li>
          <strong>A source reads stale right after registering.</strong> An SLA with no
          recorded update time is stale by definition. Pass <code>--updated</code>, or validate
          it.
        </li>
        <li>
          <strong>&quot;registered, but the connection failed&quot;.</strong> The gateway could not
          reach the database or API with those credentials, from where it runs.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>No edit or delete for principals and grants in the web app.</li>
        <li>A tier is a claim. Only validation checks content, and only for URLs and connected sources.</li>
      </ul>
      <Callout kind="note">
        Credentials entered for a connection are sent to the gateway and used from there. Use a
        read-only account.
      </Callout>

      <NextSteps
        items={[
          { href: "/docs/guides/rag", label: "Retrieval and answers", why: "wire entitlement and sources into retrieval" },
          { href: "/docs/app/agents#boundary", label: "Knowledge boundary", why: "what an agent may answer at all" },
          { href: "/docs/app/findings", label: "Findings", why: "stale and deprecated sources raise them" },
        ]}
      />
    </article>
  );
}
