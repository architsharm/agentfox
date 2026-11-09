import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Output } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Install options",
  description:
    "Install AgentFox, pick extras, fetch detector weights, decide where state lives, read agentfox.toml, upgrade and uninstall.",
  path: "/docs/reference/install",
});

const EXTRAS: { name: string; installs: string; enables: string }[] = [
  { name: "pii", installs: "presidio-analyzer, presidio-anonymizer", enables: "The pii.presidio detector. Also needs a spaCy model (below)." },
  { name: "classifiers", installs: "transformers, torch", enables: "injection.classifier (PIGuard with a backstop model, on by default once it can run), injection.similarity (embedding match), safety.granite (Granite Guardian). Each needs its weights." },
  { name: "sql", installs: "sqlglot", enables: "SQL blast-radius and data-access analysis. Without it, SQL analysis fails closed rather than passing statements through." },
  { name: "langgraph", installs: "langgraph", enables: "The AgentFoxGuard node wrappers in agentfox.frameworks.langgraph." },
  { name: "openai-agents", installs: "openai-agents", enables: "The OpenAI Agents SDK adapter. Not in all, because it pulls in the openai client, which changes what auto() patches." },
  { name: "postgres", installs: "psycopg[binary]", enables: "A Postgres database_url (postgresql+psycopg://…)." },
  { name: "otel", installs: "opentelemetry-api, -sdk, -exporter-otlp-proto-http", enables: "OpenTelemetry trace export, and decoding protobuf OTLP on ingest." },
  { name: "rails", installs: "nemoguardrails", enables: "The rails.nemo detector, once nemo_rails_config_path points at a NeMo Guardrails config." },
  { name: "validators", installs: "guardrails-ai", enables: "rails.guardrails_ai, to run your own Guard. The Guardrails AI validators themselves are built in and need no extra." },
  { name: "redteam", installs: "garak, pyrit", enables: "The wrapped Garak and PyRIT runners next to the built-in probes (agentfox test probes lists them)." },
  { name: "bedrock", installs: "boto3", enables: "The Amazon Bedrock model provider." },
  { name: "vertex", installs: "google-auth", enables: "The Google Vertex model provider." },
  { name: "prometheus", installs: "prometheus-client", enables: "Pushing metrics to a Prometheus push gateway. Scraping needs no extra." },
  { name: "ragas", installs: "ragas", enables: "Ragas scorers in evaluation suites." },
  { name: "all", installs: "pii, classifiers, rails, validators, redteam, otel, postgres, langgraph, sql", enables: "Every permissive extra. Excludes the cloud provider SDKs, openai-agents and restricted-classifiers." },
  { name: "restricted-classifiers", installs: "transformers, torch", enables: "safety.restricted (Llama Guard). Non-OSI licence: it also refuses to load unless AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1." },
  { name: "dev", installs: "pytest, pytest-asyncio, pytest-xdist, ruff, mypy, import-linter", enables: "Working on AgentFox itself." },
];

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Install options</h1>
      <p className="docs-lede">
        Ways to install, the optional extras, detector weights, where state lives, and how to
        upgrade or remove AgentFox.
      </p>

      <h2 id="install">Install</h2>
      <p>
        AgentFox needs Python 3.11 or newer. The core install has no model weights and nothing
        that downloads them.
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>How</th>
            <th>Command</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>pip, in a virtual environment</td>
            <td><code>pip install agentfox</code></td>
          </tr>
          <tr>
            <td>uv, in a project</td>
            <td><code>uv add agentfox</code></td>
          </tr>
          <tr>
            <td>
              As a tool, on the PATH everywhere. Claude Code and Codex hooks call AgentFox by
              absolute path, so they work from any of these installs; a tool install keeps them
              working if you delete the virtual environment.
            </td>
            <td><code>uv tool install agentfox</code> or <code>pipx install agentfox</code></td>
          </tr>
          <tr>
            <td>From source, latest commit</td>
            <td><code>pip install &quot;git+https://github.com/architsharm/agentfox.git&quot;</code></td>
          </tr>
        </tbody>
      </table></div>
      <p>
        The package installs one command, <code>agentfox</code>. <code>agentfox --version</code>{" "}
        prints the version.
      </p>
      <p>
        Then, with an account, run the command from the dashboard&apos;s card:{" "}
        <code>pip install -U agentfox</code> and <code>agentfox init --key … --server …</code> (
        <Link href="/docs/quickstart">Quickstart</Link>). Without one, run <code>agentfox scan</code> and{" "}
        <code>agentfox up</code> (<Link href="/docs/quickstart/cli">Quickstart without an account</Link>).
      </p>

      <h2 id="extras">Extras</h2>
      <p>
        Add extras in brackets: <code>pip install &quot;agentfox[pii,sql]&quot;</code>. An extra
        makes a detector <em>available</em>; it runs only once it is also listed in{" "}
        <code>enabled_detectors</code> (<Link href="/docs/reference/config#detectors">Configuration</Link>).
      </p>
      <div className="docs-table" tabIndex={0}><table>
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
      </table></div>
      <p>
        Enabled by default: <code>injection.heuristic</code>, <code>injection.classifier</code>,{" "}
        <code>pii.native</code>, <code>secrets.native</code>, <code>safety.lexicon</code>,{" "}
        <code>schema.json</code>, <code>unicode.tags</code>, <code>custom.lists</code> and{" "}
        <code>code.insecure</code>. All but <code>injection.classifier</code> need no extra;
        without the <code>classifiers</code> extra and its weights, the classifier is skipped
        and <code>agentfox doctor</code> says so. <code>agentfox.auto()</code> needs no extra: it
        patches whichever of <code>openai</code>, <code>anthropic</code>, <code>litellm</code>{" "}
        and <code>langchain</code> are installed.
      </p>

      <h2 id="weights">Detector weights</h2>
      <p>
        No detector downloads anything while handling a request. A model-backed detector
        without its weights reports itself unavailable. Fetch weights once, on purpose:
      </p>
      <Code>{`agentfox admin detectors pull injection.classifier
python -m spacy download en_core_web_lg   # for pii.presidio, about 400MB`}</Code>
      <p>
        The classifier detectors load from Hugging Face (<code>leolee99/PIGuard</code>,{" "}
        <code>protectai/deberta-v3-base-prompt-injection-v2</code>,{" "}
        <code>sentence-transformers/all-MiniLM-L6-v2</code>,{" "}
        <code>ibm-granite/granite-guardian-3.0-2b</code>); the model names are settings. The
        gateway Docker image ships with the permissive ones inside.{" "}
        <code>agentfox admin detectors list</code> shows what can run here. Pulling{" "}
        <code>injection.classifier</code> fetches two of them, and says so: PIGuard, which
        it checks with, and the protectai model, a second opinion asked only when PIGuard
        finds nothing, whose hits are recorded and never blocked on.
      </p>
      <Callout kind="note" title="Enabled but unavailable">
        The <code>detectors</code> line of <code>agentfox doctor</code> lists what is enabled{" "}
        <em>and</em> can run. An enabled detector whose extra or weights are missing turns the
        line into a warning, named with the reason.
      </Callout>

      <h2 id="state">Where state lives</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>Situation</th>
            <th>Database</th>
            <th>Evidence packages</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>AGENTFOX_STATE_DIR</code> is set</td>
            <td><code>$AGENTFOX_STATE_DIR/agentfox.db</code></td>
            <td><code>$AGENTFOX_STATE_DIR/var/evidence</code></td>
          </tr>
          <tr>
            <td>Installed package (pip, uv)</td>
            <td>
              <code>~/.agentfox/agentfox.db</code>, or{" "}
              <code>$XDG_DATA_HOME/agentfox/agentfox.db</code> when that is set
            </td>
            <td><code>~/.agentfox/var/evidence</code></td>
          </tr>
          <tr>
            <td>Source checkout</td>
            <td><code>agentfox.db</code> at the repository root</td>
            <td><code>var/evidence</code> at the repository root</td>
          </tr>
        </tbody>
      </table></div>
      <p>
        State is per installation, not per directory: <code>agentfox findings</code> shows the
        same findings from anywhere. Give each project its own <code>AGENTFOX_STATE_DIR</code>{" "}
        to keep them apart. <code>AGENTFOX_DATABASE_URL</code> and{" "}
        <code>AGENTFOX_EVIDENCE_DIR</code> override the two locations one at a time.
      </p>
      <p>
        With an account key (<code>AGENTFOX_URL</code> and <code>AGENTFOX_API_KEY</code>, or the{" "}
        <code>.agentfox/agentfox.env</code> that <code>init --key</code>, <code>up</code> and{" "}
        <code>login</code> write), the commands that show what the dashboard shows read and write the
        account instead, and say so on their first line. An explicit{" "}
        <code>AGENTFOX_DATABASE_URL</code>, or <code>AGENTFOX_LOCAL=1</code>, keeps them on the
        database.
      </p>
      <h3 id="postgres">Postgres</h3>
      <p>
        SQLite is fine for one process. For a server or more than one worker, use Postgres
        with the <code>postgres</code> extra, and create the database with UTF-8 encoding:
      </p>
      <Code>{`pip install "agentfox[postgres]"
export AGENTFOX_DATABASE_URL="postgresql+psycopg://agentfox:PASSWORD@db.internal:5432/agentfox"
agentfox init`}</Code>

      <h2 id="init">agentfox init and agentfox.toml</h2>
      <p>
        Without <code>--key</code>, <code>agentfox init</code> sets up a local install. It is
        offline and safe to run twice. To connect to an account without the key showing in{" "}
        <code>ps</code> or your shell history, export it and name the server:{" "}
        <code>export AGENTFOX_API_KEY=…</code> then <code>agentfox init --server &lt;url&gt;</code>{" "}
        (with <code>--server</code> and no <code>--key</code>, init reads{" "}
        <code>AGENTFOX_API_KEY</code>).
      </p>
      <Code>{`agentfox init`}</Code>
      <Output>{`Setting up AgentFox
  ✓ database ready  sqlite:////…/agentfox.db
  ✓ 44 controls across 7 frameworks  v0.1.0-draft (draft)
  ✓ 4 policy packs loaded
      agent-integrity          observe  recorded, nothing blocked
      baseline                 observe  recorded, nothing blocked
      eu-ai-act-high-risk      observe  recorded, nothing blocked
      tool-containment         observe  recorded, nothing blocked
      coding-agent not enabled — no coding-agent hooks in this repo. \`agentfox admin hooks install
--agent <slug> --write\` turns it on for that agent.
      Missing grants, destructive commands and tampering are still refused. When the would-block
decisions look right: \`agentfox policy enforce tool-containment\`.
  ✓ wrote agentfox.toml`}</Output>
      <p>
        It creates and migrates the database, loads the control catalog and the policy packs
        every one watching (switch one to blocking with{" "}
        <code>agentfox policy enforce &lt;key&gt;</code>; a second run keeps each pack&apos;s
        mode), and writes <code>agentfox.toml</code> in the current
        directory (or <code>--path</code>, which must be an existing directory). A second run
        leaves an existing <code>agentfox.toml</code> alone. The fifth pack,{" "}
        <code>coding-agent</code>, applies only once a coding agent has hooks installed (
        <Link href="/docs/connect/coding-agents">Claude Code and Codex</Link>).{" "}
        <code>--demo</code> also loads three demo agents and an eval suite.
      </p>
      <p>The generated file:</p>
      <Code lang="toml" title="agentfox.toml">{`[agentfox]
environment = "development"

# Default mode for a policy that does not declare its own. \`agentfox init\` starts every
# shipped pack in observe; \`agentfox policy enforce <key>\` starts one blocking.
default_policy_mode = "observe"

# Zero egress: no model call leaves this machine unless you turn it on.
allow_egress = false

# The whole pre-flight pipeline's latency ceiling, in milliseconds.
enforcement_budget_ms = 300

# Where a tool call's provenance is read from, for the taint rules.
#   "session"  - the worst untrusted content anywhere in the run so far, or in the
#                call's own arguments. Contains more; escalates more benign calls.
#   "argument" - only what the call's own arguments were copied from.
taint_scope = "session"`}</Code>
      <p>Settings are read in this order, first match wins:</p>
      <ol>
        <li><code>AGENTFOX_*</code> environment variables.</li>
        <li>
          The <code>[agentfox]</code> table of <code>$AGENTFOX_CONFIG</code> if set (it must
          exist), otherwise of <code>./agentfox.toml</code>.
        </li>
        <li>Built-in defaults.</li>
      </ol>
      <p>
        Keys are the setting names without the prefix. An unknown key is ignored with a
        warning. <code>AGENTFOX_CONFIG=none</code> turns file loading off. Settings are read
        once per process, so restart after a change. Every key is on{" "}
        <Link href="/docs/reference/config">Configuration</Link>.
      </p>
      <Callout kind="note" title="The file is per working directory">
        <code>agentfox.toml</code> is looked up in the directory a process starts in. In
        services, use environment variables or an explicit <code>AGENTFOX_CONFIG</code>.
      </Callout>

      <h2 id="doctor">Check it: agentfox doctor</h2>
      <p>
        <code>agentfox doctor</code> grades the configuration, not the traffic, and changes
        nothing. <code>!</code> lines are warnings and <code>✗</code> lines are failures. On a
        fresh install expect warnings for no traffic yet, development authentication, no
        declared tools, no row scoping, fail-open detectors and no knowledge boundary.{" "}
        <code>agentfox doctor --json</code> prints one record per check and exits non-zero on a
        failed check, for CI.
      </p>

      <h2 id="upgrade">Upgrade</h2>
      <Code>{`pip install -U agentfox
agentfox admin db upgrade
agentfox admin db current`}</Code>
      <p>
        <code>admin db upgrade</code> applies new migrations and is safe to run when there are
        none. Run it before restarting a server on new code; <code>agentfox init</code> also
        migrates. <code>agentfox admin db downgrade</code> can drop columns and data: take a
        backup first.
      </p>

      <h2 id="turn-off">Turn it off for a while</h2>
      <p>
        Set <code>AGENTFOX_DISABLED=1</code> in the app&apos;s environment and restart it.{" "}
        <code>agentfox.auto()</code> then patches nothing, checks nothing, stores nothing and
        sends nothing; it prints one line, <code>agentfox: off (AGENTFOX_DISABLED is set)</code>,
        so a switch left on is easy to spot. Unset it to turn AgentFox back on. No code change
        either way.
      </p>
      <ul>
        <li>
          To keep recording but never refuse a call, use <code>agentfox.auto(mode=&quot;observe&quot;)</code>{" "}
          instead.
        </li>
        <li>
          To stop one agent everywhere at once, press <strong>Pause</strong> on its page (or{" "}
          <strong>Stop</strong>, which also records an incident). That refuses its calls until you
          resume; it does not turn checks off.
        </li>
        <li>
          Coding-agent hooks have no switch: remove them from the settings file (below) to pause
          them.
        </li>
      </ul>

      <h2 id="uninstall">Uninstall</h2>
      <p>
        Uninstalling the package removes the code and keeps your data. Remove each piece you
        set up, in this order.
      </p>
      <ol>
        <li>
          <strong>Your code.</strong> Delete the two lines <code>agentfox up</code> or{" "}
          <code>init</code> added to your entry point: <code>import agentfox</code> and the{" "}
          <code>agentfox.auto(…)</code> line marked <code># added by `agentfox up`</code>.
        </li>
        <li>
          <strong>The project folder.</strong> <code>.agentfox/</code> holds{" "}
          <code>agentfox.env</code> (your account key, if you connected one),{" "}
          <code>up.json</code> (your <code>up</code> answers) and logs. <code>agentfox.toml</code>{" "}
          is the project&apos;s settings. <code>agentfox up --with ci</code> wrote{" "}
          <code>.github/workflows/agentfox.yml</code>; <code>up</code> may also have added an{" "}
          <code>agentfox</code> entry to <code>.mcp.json</code>.
        </li>
        <li>
          <strong>Coding-agent hooks.</strong> Remove the entries whose command runs{" "}
          <code>hooks run</code> from <code>.claude/settings.json</code> (or{" "}
          <code>settings.local.json</code>, or <code>~/.claude/settings.json</code> for{" "}
          <code>--scope user</code>) and, for Codex, from <code>.codex/hooks.json</code> or{" "}
          <code>~/.codex/hooks.json</code>. Stop the daemon if it is running:{" "}
          <code>agentfox admin hooks status</code> says whether it is.
        </li>
        <li>
          <strong>The package.</strong> Whichever way you installed it:{" "}
          <code>pip uninstall agentfox</code>, <code>uv remove agentfox</code>,{" "}
          <code>uv tool uninstall agentfox</code> or <code>pipx uninstall agentfox</code>.
        </li>
        <li>
          <strong>Local state.</strong> The database and evidence in the state directory. The
          audit chain is evidence, so this is a separate, deliberate step.
        </li>
        <li>
          <strong>Your account key.</strong> If you connected an account, revoke the key on{" "}
          <strong>Settings → API keys</strong>. Deleting <code>agentfox.env</code> does not
          revoke it.
        </li>
      </ol>
      <Code>{`rm -rf .agentfox agentfox.toml .github/workflows/agentfox.yml   # in each project
uv tool uninstall agentfox      # or: pip uninstall agentfox / pipx uninstall agentfox
rm -rf ~/.agentfox              # or $AGENTFOX_STATE_DIR / $XDG_DATA_HOME/agentfox`}</Code>

      <h2 id="troubleshooting">Troubleshooting</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>You see</th>
            <th>Do this</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>ConfigFileError: AGENTFOX_CONFIG=… does not point at a readable file.</code></td>
            <td>Fix the path, or set it to <code>none</code>.</td>
          </tr>
          <tr>
            <td><code>taint_scope … must be one of session, argument</code></td>
            <td>Fix the typo. Validated settings stop startup rather than fall back.</td>
          </tr>
          <tr>
            <td>A setting in <code>agentfox.toml</code> has no effect</td>
            <td>
              An environment variable overrides it, the key is misspelled (look for the
              warning), or the process started in another directory.
            </td>
          </tr>
          <tr>
            <td>Postgres: <code>TypeError: cannot use a string pattern on a bytes-like object</code></td>
            <td>The database uses <code>SQL_ASCII</code>. Create it with UTF-8 encoding.</td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: "/docs/quickstart", label: "Quickstart", why: "connect your first agent" },
          { href: "/docs/reference/config", label: "Configuration", why: "every setting, with its default" },
          { href: "/docs/self-host", label: "Self-host", why: "run the gateway and dashboard yourself" },
        ]}
      />
    </article>
  );
}
