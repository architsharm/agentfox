import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Output } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Install and configure",
  description:
    "Install AgentFox, pick extras, fetch detector weights, decide where state lives, and read agentfox.toml.",
  path: "/docs/install",
});

const EXTRAS: { name: string; installs: string; enables: string }[] = [
  { name: "pii", installs: "presidio-analyzer, presidio-anonymizer", enables: "The pii.presidio detector. Also needs a spaCy model (below)." },
  { name: "classifiers", installs: "transformers, torch", enables: "injection.classifier (PIGuard with a backstop model), injection.similarity (embedding match), safety.granite (Granite Guardian). Each needs its weights." },
  { name: "sql", installs: "sqlglot", enables: "SQL blast-radius and data-access analysis. Without it, SQL analysis fails closed rather than passing statements through." },
  { name: "langgraph", installs: "langgraph", enables: "The AgentFoxGuard node wrappers in agentfox.frameworks.langgraph." },
  { name: "postgres", installs: "psycopg[binary]", enables: "A Postgres database_url (postgresql+psycopg://…)." },
  { name: "otel", installs: "opentelemetry-api, -sdk, -exporter-otlp-proto-http", enables: "OpenTelemetry trace export." },
  { name: "rails", installs: "nemoguardrails", enables: "The rails.nemo detector, once nemo_rails_config_path points at a NeMo Guardrails config." },
  { name: "validators", installs: "guardrails-ai", enables: "rails.guardrails_ai and the rails.hub.* detectors, once guardrails_ai_validators names installed Hub validators." },
  { name: "redteam", installs: "garak, pyrit", enables: "The wrapped Garak and PyRIT runners alongside the built-in probes (agentfox test probes lists them)." },
  { name: "bedrock", installs: "boto3", enables: "The Amazon Bedrock model provider." },
  { name: "vertex", installs: "google-auth", enables: "The Google Vertex model provider." },
  { name: "prometheus", installs: "prometheus-client", enables: "Pushing metrics to a Prometheus push gateway. Scraping needs no extra." },
  { name: "ragas", installs: "ragas", enables: "Ragas scorers in evaluation suites." },
  { name: "all", installs: "pii, classifiers, rails, validators, redteam, otel, postgres, langgraph, sql", enables: "Every permissive extra. Excludes the cloud provider SDKs and restricted-classifiers." },
  { name: "restricted-classifiers", installs: "transformers, torch", enables: "safety.restricted (Llama Guard). Non-OSI licence: it also refuses to load unless AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1." },
  { name: "dev", installs: "pytest, pytest-asyncio, ruff, mypy", enables: "Working on AgentFox itself." },
];

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Start</p>
      <h1>Install and configure</h1>
      <p className="docs-lede">
        Install the package, add only the extras you need, decide where the database lives,
        and check the result with <code>agentfox doctor</code>.
      </p>

      <h2>When to use this</h2>
      <p>
        Before you put AgentFox in front of a real agent, and whenever you add a detector,
        move the database, or upgrade. For a first look, the{" "}
        <Link href="/docs/quickstart">Quickstart</Link> is enough. For a server, read{" "}
        <Link href="/docs/self-host">Self-hosting</Link> after this page.
      </p>

      <h2>Install</h2>
      <p>
        AgentFox needs Python 3.11 or newer (<code>requires-python = &quot;&gt;=3.11&quot;</code>).
        The core install is deliberately light: a web framework, SQLAlchemy, Alembic, Typer,
        and nothing that downloads model weights.
      </p>
      <Code>{`python3 -m venv .venv && source .venv/bin/activate
pip install agentfox
agentfox --version`}</Code>
      <Output>{`agentfox 0.3.1`}</Output>
      <p>With uv, in a project:</p>
      <Code>{`uv add agentfox`}</Code>
      <p>From source, for the latest commit:</p>
      <Code>{`pip install "git+https://github.com/architsharm/agentfox.git"`}</Code>
      <p>
        The package installs one command, <code>agentfox</code>.
      </p>

      <h2 id="extras">Extras</h2>
      <p>
        Each extra wraps a third-party engine, and each is optional. Add them in brackets:{" "}
        <code>pip install &quot;agentfox[pii,sql]&quot;</code>. Installing an extra makes a
        detector <em>available</em>; it runs only once it is also listed in{" "}
        <code>enabled_detectors</code> (<Link href="/docs/reference/config#detectors">Configuration</Link>).
      </p>
      <table>
        <thead>
          <tr>
            <th>Extra</th>
            <th>Installs</th>
            <th>Enables</th>
          </tr>
        </thead>
        <tbody>
          {EXTRAS.map((x) => (
            <tr key={x.name}>
              <td>
                <code>{x.name}</code>
              </td>
              <td>{x.installs}</td>
              <td>{x.enables}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        Five detectors need no extra and are on by default: <code>injection.heuristic</code>,{" "}
        <code>pii.native</code>, <code>secrets.native</code>, <code>safety.lexicon</code> and{" "}
        <code>schema.json</code>. <code>agentfox.auto()</code> needs no extra either; it
        patches whichever of <code>openai</code>, <code>anthropic</code>,{" "}
        <code>litellm</code> and <code>langchain</code> are already installed.
      </p>

      <h2 id="weights">Detector weights</h2>
      <p>
        No detector downloads anything while handling a request. A model-backed detector
        whose weights are absent reports itself unavailable instead of reaching the network
        mid-decision. Fetch weights on purpose, once:
      </p>
      <Code>{`python -m spacy download en_core_web_lg`}</Code>
      <p>
        That is the spaCy model for <code>pii.presidio</code>, about 400MB. The classifier
        detectors load from Hugging Face the same way (<code>leolee99/PIGuard</code>,{" "}
        <code>protectai/deberta-v3-base-prompt-injection-v2</code>,{" "}
        <code>sentence-transformers/all-MiniLM-L6-v2</code>,{" "}
        <code>ibm-granite/granite-guardian-3.0-2b</code>); the model names are settings. The
        gateway Docker image ships with the permissive ones already inside.
      </p>
      <p>Then check which detectors this process can actually run:</p>
      <Code>{`agentfox doctor`}</Code>
      <Output>{`…
  ✓    detectors           5 running: injection.heuristic, pii.native, safety.lexicon,
                           schema.json, secrets.native
…`}</Output>
      <Callout kind="note" title="Enabled but unavailable">
        The <code>detectors</code> line lists what is enabled <em>and</em> can run. A
        detector you enabled whose extra or weights are missing turns the line into a
        warning and is named with the reason: enabling <code>injection.classifier</code>{" "}
        without the <code>classifiers</code> extra prints{" "}
        <code>enabled but unavailable: injection.classifier (…)</code>.
      </Callout>

      <h2 id="state">Where state lives</h2>
      <p>
        AgentFox keeps a database and a directory of evidence packages. Where they go
        depends on how it is installed:
      </p>
      <table>
        <thead>
          <tr>
            <th>Situation</th>
            <th>Database</th>
            <th>Evidence packages</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <code>AGENTFOX_STATE_DIR</code> is set
            </td>
            <td>
              <code>$AGENTFOX_STATE_DIR/agentfox.db</code>
            </td>
            <td>
              <code>$AGENTFOX_STATE_DIR/var/evidence</code>
            </td>
          </tr>
          <tr>
            <td>Installed package (pip, uv)</td>
            <td>
              <code>~/.agentfox/agentfox.db</code>, or{" "}
              <code>$XDG_DATA_HOME/agentfox/agentfox.db</code> when that is set
            </td>
            <td>
              <code>~/.agentfox/var/evidence</code>
            </td>
          </tr>
          <tr>
            <td>Running from a source checkout</td>
            <td>
              <code>agentfox.db</code> at the repository root
            </td>
            <td>
              <code>var/evidence</code> at the repository root
            </td>
          </tr>
        </tbody>
      </table>
      <p>
        State is per installation, not per directory, so <code>agentfox findings</code> shows
        the same findings from wherever you type it. To keep two projects apart, give each
        its own <code>AGENTFOX_STATE_DIR</code>. <code>AGENTFOX_DATABASE_URL</code> and{" "}
        <code>AGENTFOX_EVIDENCE_DIR</code> override the two locations individually.
      </p>
      <h3>Postgres</h3>
      <p>
        SQLite is fine for one process. For a server, or more than one worker, use Postgres
        with the <code>postgres</code> extra:
      </p>
      <Code>{`pip install "agentfox[postgres]"
export AGENTFOX_DATABASE_URL="postgresql+psycopg://agentfox:PASSWORD@db.internal:5432/agentfox"
agentfox init`}</Code>
      <Output>{`Setting up AgentFox
  ✓ database ready  postgresql+psycopg://agentfox@127.0.0.1:55439/agentfox
  ✓ 43 controls across 7 frameworks  v0.1.0-draft (draft)
  ✓ 3 policy pack(s) loaded
…`}</Output>
      <p>
        That output is from a local Postgres 16 cluster; use your own host and credentials.
        Create the database with UTF-8 encoding.
      </p>

      <h2 id="init">agentfox init and agentfox.toml</h2>
      <Code>{`agentfox init`}</Code>
      <Output>{`Setting up AgentFox
  ✓ database ready
sqlite:////…/agentfox.db
  ✓ 43 controls across 7 frameworks  v0.1.0-draft (draft)
  ✓ 3 policy pack(s) loaded
      baseline                 observe  recorded, nothing blocked
      eu-ai-act-high-risk      observe  recorded, nothing blocked
      tool-containment         enforce  violations are blocked now
      coding-agent not enabled — no coding-agent hooks in this repo. \`agentfox admin hooks install
--agent <slug> --write\` turns it on for that agent.
      tool-containment blocks from the start — demote with \`agentfox policy observe <key>\`.
  ✓ wrote agentfox.toml
…`}</Output>
      <p>
        It creates and migrates the database, loads 43 controls and the policy packs, and
        writes <code>agentfox.toml</code> in the current directory (or <code>--path</code>).
        Run it again and it changes nothing it does not need to:{" "}
        <code>· agentfox.toml already exists, left alone</code>. Three packs load in a plain
        repository; the fourth, <code>coding-agent</code>, applies only once a coding agent
        has hooks installed (<Link href="/docs/guides/coding-agents">Coding agents</Link>).
      </p>
      <p>The generated file, exactly:</p>
      <Code lang="toml" title="agentfox.toml">{`# AgentFox configuration.
# Everything here has a safe default; this file exists so the defaults are visible
# rather than implicit. The [agentfox] table is read from the working directory;
# environment variables (AGENTFOX_*) override it.

[agentfox]
environment = "development"

# Default mode for a policy that does not declare its own. Packs that declare a mode
# keep it (the shipped tool-containment pack declares enforce).
default_policy_mode = "observe"

# Zero egress: no model call leaves this machine unless you turn it on.
allow_egress = false

# The whole pre-flight pipeline's latency ceiling, in milliseconds.
enforcement_budget_ms = 300

# Where a tool call's provenance is read from, for the taint rules.
#   "session"  - the worst untrusted content anywhere in the run so far, or in the
#                call's own arguments. Contains more; escalates more benign calls.
#   "argument" - only what the call's own arguments were copied from.
# Every published number was measured under "session". docs/getting-started.md, step 5b.
taint_scope = "session"`}</Code>
      <p>How settings are read, highest precedence first:</p>
      <ol>
        <li>
          <code>AGENTFOX_*</code> environment variables;
        </li>
        <li>
          the <code>[agentfox]</code> table of <code>$AGENTFOX_CONFIG</code> if set (it must
          exist), otherwise of <code>./agentfox.toml</code> in the working directory;
        </li>
        <li>built-in defaults.</li>
      </ol>
      <p>
        Keys are the setting names without the prefix. An unknown key is ignored with a
        warning that names it. <code>AGENTFOX_CONFIG=none</code> turns file loading off. Every
        key is on <Link href="/docs/reference/config">Configuration</Link>. Settings are read
        once per process, so restart after a change.
      </p>
      <Callout kind="note" title="The file is per working directory">
        <code>agentfox.toml</code> is looked up in the directory a process starts in, so an
        agent started from elsewhere does not read it. In services, prefer environment
        variables or an explicit <code>AGENTFOX_CONFIG</code>.
      </Callout>

      <h2 id="doctor">Check it: agentfox doctor</h2>
      <p>
        <code>doctor</code> grades the configuration, not the traffic. It changes nothing.
        On a fresh install:
      </p>
      <Code>{`agentfox doctor`}</Code>
      <Output>{`Runtime check
  ✓    database            reachable — 0 agent(s), 0 trace(s)
  !    traffic             no decisions recorded — nothing has been governed yet. Add
                           \`agentfox.auto()\` to your entry point.
  !    authentication      the X-AgentFox-User header is accepted (environment=development,
                           auth_mode=auto) — anyone who can reach this port is any user they name.
                           Fine locally, unacceptable anywhere else.
  !    containment         no tools declared — nothing constrains what an agent may do when a
                           detector misses. Declare them with \`agentfox declare tool <key>
                           --impact ...\`.
  !    data scope          no table row-scoping declared — a query across every customer's rows
                           reads as ordinary. Declare with \`agentfox declare scope <table>
                           --column ...\`.
  ✓    detectors           5 running: injection.heuristic, pii.native, safety.lexicon,
                           schema.json, secrets.native
  ✓    providers           offline only (echo). No model call can leave this machine — set
                           AGENTFOX_ALLOW_EGRESS=1 and a key to change that.
  !    detector failure    fail-open: a detector that times out lets the request through and
                           records the gap
  !    answerability       no knowledge boundary declared — nothing stops an agent answering a
                           question it has no data for.
  ✓    findings            none open`}</Output>
      <p>
        <code>!</code> lines are warnings, <code>✗</code> lines are failures. Two are about
        AgentFox itself rather than your agents: development authentication, and a detector
        that fails open. <code>agentfox doctor --json</code> emits one record per check and
        exits non-zero on a failed check, for CI.
      </p>

      <h2 id="upgrade">Upgrade</h2>
      <Code>{`pip install --upgrade agentfox
agentfox admin db upgrade
agentfox admin db current`}</Code>
      <Output>{`…
migrated b8d3f6a2c915 → b8d3f6a2c915
schema revision: b8d3f6a2c915`}</Output>
      <p>
        <code>admin db upgrade</code> applies any new migrations and is safe to run when there
        are none. Run it before you restart a server on new code. <code>agentfox init</code>{" "}
        also migrates. <code>agentfox admin db downgrade</code> exists and can drop columns
        and data; take a backup first.
      </p>

      <h2 id="uninstall">Uninstall and clean up</h2>
      <Code>{`pip uninstall agentfox`}</Code>
      <p>
        Uninstalling removes the code and leaves your data: the database and evidence in the
        state directory, and each project&apos;s <code>agentfox.toml</code>. That is
        deliberate, because the audit chain is evidence. To remove them too:
      </p>
      <Code>{`rm -rf ~/.agentfox        # or $AGENTFOX_STATE_DIR / $XDG_DATA_HOME/agentfox
rm agentfox.toml          # in each project where you ran agentfox init`}</Code>
      <p>
        Also remove the two lines of <code>agentfox.auto()</code> from your entry point, and
        any hooks written into <code>.claude/settings.json</code> by{" "}
        <code>agentfox admin hooks install --write</code>.
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
            <td>
              <code>ConfigFileError: AGENTFOX_CONFIG=… does not point at a readable file.</code>
            </td>
            <td>The file you named explicitly does not exist. Fix the path, or set it to <code>none</code>.</td>
          </tr>
          <tr>
            <td>
              <code>taint_scope … must be one of session, argument</code>
            </td>
            <td>A typo in a validated setting stops startup on purpose, rather than falling back.</td>
          </tr>
          <tr>
            <td>A setting in <code>agentfox.toml</code> has no effect</td>
            <td>
              An environment variable overrides it, the key is misspelled (look for the
              warning), or the process started in another directory.
            </td>
          </tr>
          <tr>
            <td>
              Postgres: <code>TypeError: cannot use a string pattern on a bytes-like object</code>
            </td>
            <td>The database uses <code>SQL_ASCII</code>. Create it with UTF-8 encoding.</td>
          </tr>
          <tr>
            <td>
              <code>agentfox init --path</code> to a directory that does not exist raises{" "}
              <code>FileNotFoundError</code>
            </td>
            <td>Create the directory first.</td>
          </tr>
        </tbody>
      </table>

      <NextSteps
        items={[
          { href: "/docs/reference/config", label: "Configuration reference", why: "every setting, its variable, key and default" },
          { href: "/docs/self-host", label: "Self-hosting", why: "the gateway and dashboard as a service" },
          { href: "/docs/quickstart", label: "Quickstart", why: "use what you just installed" },
        ]}
      />
    </article>
  );
}
