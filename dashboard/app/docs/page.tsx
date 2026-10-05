import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Getting started",
  description: "Install AgentFox, scan a repository, and run the offline demo.",
  path: "/docs",
});

export default function GettingStarted() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Start</p>
      <h1>Getting started</h1>
      <p>
        A first hour, from an empty directory to one of your own agents behind the
        control plane. You need Python 3.11 or newer. Every step below runs offline
        after the install: no API key, no model weights, no network egress. The built-in{" "}
        <code>echo</code> provider makes the enforcement path demonstrable with nothing
        else installed.
      </p>
      <p>
        If you would rather see a refusal before installing anything, the{" "}
        <Link href="/playground">playground</Link> needs no account.
      </p>

      <h2>1. Install</h2>
      <pre>
        <code>{`python3 -m venv .venv && source .venv/bin/activate
pip install agentfox
agentfox --help`}</code>
      </pre>
      <p>
        The core install pulls no model weights and no detector frameworks. Optional
        extras (<code>[pii]</code>, <code>[classifiers]</code>, <code>[redteam]</code>,{" "}
        <code>[langgraph]</code>, <code>[sql]</code>, <code>[otel]</code>,{" "}
        <code>[postgres]</code>, or <code>[all]</code>) add wrapped engines later.
      </p>
      <p>
        For a first look at the directory you are standing in, without a permanent
        install:
      </p>
      <pre>
        <code>curl -fsSL https://raw.githubusercontent.com/architsharm/agentfox/main/scripts/quickscan.sh | bash</code>
      </pre>
      <p>The script uses a virtualenv and removes it on exit.</p>

      <h2>2. Initialise</h2>
      <pre>
        <code>agentfox init</code>
      </pre>
      <p>
        This creates a SQLite database in the current directory, loads 43 controls and
        four policy packs, and writes <code>agentfox.toml</code> if there is not one.
        It is idempotent. Read the mode column. <code>baseline</code>,{" "}
        <code>coding-agent</code> and <code>eu-ai-act-high-risk</code> start in
        observe: they record what they would
        have done and block nothing. <code>tool-containment</code> starts in enforce,
        because it does not guess. It refuses a call with no grant, and a call that
        carries an untrusted argument into an irreversible tool.
      </p>

      <h2>3. Scan a repository</h2>
      <pre>
        <code>{`cd /path/to/your/project
agentfox scan`}</code>
      </pre>
      <p>
        A static read of the source. It reports model call sites, which of them are
        ungoverned, agent definitions, MCP servers, hard-coded credentials, and shell
        and SQL construction near model output. It writes nothing to the project and
        sends nothing anywhere.
      </p>
      <p>
        <code>agentfox scan --sessions</code> is the same look plus local AI-tool session
        transcripts, and it runs a handful of known-adversarial prompts through the
        detector pipeline in the terminal. Nothing leaves the machine. The rest of the
        inventory commands are on <Link href="/docs/discovery">Discovery</Link>.
      </p>

      <h2>4. Run the demo</h2>
      <pre>
        <code>agentfox init && agentfox demo</code>
      </pre>
      <p>
        <code>init</code> takes about a second. <code>demo</code> is a thirteen-step
        walkthrough in about five, against three seeded agents. The step to read is the
        transfer whose recipient came out of a poisoned document: the injection has
        already succeeded, and the transfer is refused anyway, because one argument
        came from untrusted content and <code>tool-containment</code> is in enforce.
        A transfer the user typed is allowed. A transfer over the argument limit is
        blocked. None of the three is decided by a detector.
      </p>
      <p>
        Later in the same run the demo verifies the audit chain, edits an entry in the
        database, and verifies again. The second check reports the chain tampered. The
        demo promotes <code>baseline</code> to enforce partway through and restores
        observe when it finishes, so it leaves the database as it found it.
      </p>

      <h2>5. Put your own agent behind it</h2>
      <p>
        This path needs no Python in the application. Start the control plane, then ask
        about a tool call before the agent runs it.
      </p>
      <pre>
        <code>{`agentfox serve
curl -s -X POST http://localhost:8080/v1/guard/tool_call \\
  -H "Content-Type: application/json" \\
  -d '{"agent":"my-agent","tool":"payments.transfer","arguments":{"amount":250},"provenance":{"amount":"user"},"intent":"refund a duplicate charge"}'`}</code>
      </pre>
      <p>
        On a database you have not configured, for an agent that does not exist yet,
        the verdict is <code>block</code> with <code>capability.denied</code>. The
        endpoint returns HTTP 200 and a verdict (<code>allow</code>, <code>redact</code>,{" "}
        <code>escalate</code>, or <code>block</code>), so the caller branches on the
        verdict rather than on an error status. <code>agentfox agents list</code> then
        shows <code>my-agent</code> as shadow traffic, unowned, registered by the call
        itself.
      </p>
      <p>
        Declare the tool, grant the capability, and the same call with a different
        provenance gets a different answer. That sequence, the gateway headers, and
        the Python one-liner are on <Link href="/docs/connect">Where it connects</Link>{" "}
        and <Link href="/docs/access">Access control</Link>.
      </p>

      <h2>6. Read what it found</h2>
      <pre>
        <code>{`agentfox findings
agentfox findings --severity high
agentfox doctor`}</code>
      </pre>
      <p>
        <code>findings</code> is the list a person should look at: shadow agents, agents
        with no owner, stale identities, and detections that led to a block or a
        redaction. <code>doctor</code> grades the configuration rather than the traffic.
        It will tell you when authentication is still the development header, and when
        a detector that times out fails open. Both are meant to be read before you
        trust the deployment.
      </p>

      <h2>7. Test, then turn enforcement on</h2>
      <p>
        <code>agentfox test redteam my-agent</code> probes this deployment&apos;s grants
        and policy bindings. It includes benign controls, so a configuration that blocks
        everything scores badly. It is a posture check, not a robustness certificate.{" "}
        <code>agentfox policy simulate --file candidate.yaml</code> replays recorded
        traffic against a candidate before the candidate is in force.
      </p>
      <pre>
        <code>{`agentfox policy list
agentfox policy effective --agent my-agent
agentfox policy enforce baseline`}</code>
      </pre>
      <p>
        <code>policy enforce baseline</code> is the step that starts blocking model
        traffic. <code>tool-containment</code> was already enforcing from{" "}
        <code>init</code>. <code>agentfox policy observe baseline</code> puts baseline
        back. <code>agentfox agents quarantine my-agent --reason &quot;...&quot;</code>{" "}
        stops one agent without touching the rest. Both are reversible and both are
        audited.
      </p>

      <h2>Next</h2>
      <ul>
        <li>
          <Link href="/docs/commands">Commands</Link>, grouped by what you are trying to do.
        </li>
        <li>
          <Link href="/docs/connect">Where it connects</Link>, if an agent is already running.
        </li>
        <li>
          <Link href="/docs/self-host">Self-hosting</Link>, for more than a laptop database.
        </li>
      </ul>
    </article>
  );
}
