import Link from "next/link";

import type { TocItem } from "@/components/blog/article";
import { Diagram, InlineCTA, Takeaways, type FaqItem } from "@/components/blog/blocks";
import { Code } from "@/components/docs/blocks";

export const toc: TocItem[] = [
  { id: "why-hooks", label: "Why hooks are the control point" },
  { id: "three-hooks", label: "Three hooks, two can block" },
  { id: "posttooluse", label: "The one that cannot" },
  { id: "install", label: "Install a working baseline" },
  { id: "what-gets-stopped", label: "What gets stopped" },
  { id: "limits", label: "Limits worth knowing" },
];

export const faq: FaqItem[] = [
  {
    q: "Which Claude Code hooks can block a tool call?",
    a: "PreToolUse can deny a tool call before it runs, by returning permissionDecision set to deny. UserPromptSubmit can stop a prompt before it reaches the model. PostToolUse runs after the tool has already executed, so it cannot stop the call; it can only put a warning in front of the model.",
  },
  {
    q: "Can a PostToolUse hook block a command in Claude Code?",
    a: "Not in a way that undoes anything. In our live probe against Claude Code 2.1.220, a PostToolUse hook returning decision block did not stop the command: it had already run and its output came back. Treat PostToolUse as the place to catch indirect prompt injection arriving in a result, never as containment.",
  },
  {
    q: "How do I install AgentFox hooks for Claude Code?",
    a: "Run agentfox admin hooks install --agent claude-dev to print the configuration, then add --write to merge it into .claude/settings.json. The write also registers the agent, declares Claude Code's built-in tools with their impact and binds the coding-agent policy pack in observe mode.",
  },
  {
    q: "What happens if the AgentFox hook daemon is not running?",
    a: "The hook fails open: it allows the call, exits 0 and prints a warning on stderr that the call was not checked. That keeps a developer's session usable, and it is a limit you should know about before relying on the hooks.",
  },
  {
    q: "Do Claude Code hooks protect cloud or remote agent sessions?",
    a: "No. A hook runs in the local Claude Code harness on the developer's machine. Sessions that run elsewhere, and other coding agents, need a different control point such as the gateway or the SDK.",
  },
];

export function Body() {
  return (
    <>
      <Takeaways
        items={[
          "In Claude Code, a hook is the only place a tool call can be refused before it runs, from outside the model.",
          "Two of the three hooks can stop something: PreToolUse stops the call, UserPromptSubmit stops the prompt. PostToolUse cannot; the side effect has already happened.",
          "A useful baseline blocks credential reads, piped remote scripts, destructive commands and edits to the guardrail itself, and asks a person about history rewrites and deploys.",
        ]}
      />

      <h2 id="why-hooks">Why hooks are the control point for coding agents</h2>
      <p>
        A coding agent runs with your shell, your files and your credentials. Its instructions
        come from you, but its context also comes from every README, issue, web page and
        package it reads while working. Any of those can carry an instruction, which makes a
        coding agent the most direct case of{" "}
        <Link href="/blog/prompt-injection-containment-not-detection">
          prompt injection meeting a real tool
        </Link>
        .
      </p>
      <p>
        You cannot put a gateway between Claude Code and <code>bash</code>. What you can do is
        register a <strong>hook</strong>: a command Claude Code runs at fixed points in its
        loop, whose output it reads before continuing. A hook runs outside the model, so a
        prompt cannot talk it out of its answer. That makes it the right place for guardrails
        on coding agents, as long as you know which hooks can actually say no.
      </p>

      <h2 id="three-hooks">Three hooks, and only two can stop anything</h2>
      <Diagram
        label="Claude Code hook lifecycle and which hooks can block"
        caption="Where each hook sits in Claude Code's loop. The two before the side effect can stop it. The one after can only warn the model about what came back."
      >
        <svg className="dg" viewBox="0 0 780 200" xmlns="http://www.w3.org/2000/svg">
          <rect x="10" y="60" width="120" height="56" rx="10" className="dg-box" />
          <text x="70" y="86" textAnchor="middle" className="dg-strong">Your prompt</text>
          <text x="70" y="104" textAnchor="middle" className="dg-small">or a pasted issue</text>

          <rect x="160" y="50" width="150" height="76" rx="10" className="dg-box-good" />
          <text x="235" y="78" textAnchor="middle" className="dg-strong dg-mono">UserPromptSubmit</text>
          <text x="235" y="100" textAnchor="middle" className="dg-small dg-t-good">can block the turn</text>

          <rect x="340" y="50" width="130" height="76" rx="10" className="dg-box-good" />
          <text x="405" y="78" textAnchor="middle" className="dg-strong dg-mono">PreToolUse</text>
          <text x="405" y="100" textAnchor="middle" className="dg-small dg-t-good">can deny the call</text>

          <rect x="500" y="60" width="110" height="56" rx="10" className="dg-box-accent" />
          <text x="555" y="86" textAnchor="middle" className="dg-strong">Tool runs</text>
          <text x="555" y="104" textAnchor="middle" className="dg-small">side effect</text>

          <rect x="640" y="50" width="130" height="76" rx="10" className="dg-box-hold" />
          <text x="705" y="78" textAnchor="middle" className="dg-strong dg-mono">PostToolUse</text>
          <text x="705" y="100" textAnchor="middle" className="dg-small dg-t-hold">observe only</text>

          <path d="M130 88 L160 88" className="dg-line" />
          <path d="M310 88 L340 88" className="dg-line" />
          <path d="M470 88 L500 88" className="dg-line" />
          <path d="M610 88 L640 88" className="dg-line" />
          <path d="M160 160 L470 160" className="dg-line-accent" />
          <text x="315" y="185" textAnchor="middle" className="dg-small dg-t-accent">containment happens here</text>
          <path d="M640 160 L770 160" className="dg-line dg-dash" />
          <text x="705" y="185" textAnchor="middle" className="dg-small">too late to stop</text>
        </svg>
      </Diagram>
      <p>We verified each of these against Claude Code 2.1.220, live where a probe was possible:</p>
      <table>
        <thead>
          <tr>
            <th>Hook</th>
            <th>Can it stop the action?</th>
            <th>How we know</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <code>PreToolUse</code>
            </td>
            <td>
              Yes. <code>permissionDecision: &quot;deny&quot;</code> stops the call and the
              reason reaches the agent verbatim.
            </td>
            <td>Live probe</td>
          </tr>
          <tr>
            <td>
              <code>UserPromptSubmit</code>
            </td>
            <td>Yes. A block ends the turn before the prompt reaches the model.</td>
            <td>Read in the shipped bundle; a hook cannot trigger the operator&apos;s own turn</td>
          </tr>
          <tr>
            <td>
              <code>PostToolUse</code>
            </td>
            <td>No. The command has already run.</td>
            <td>Live probe</td>
          </tr>
        </tbody>
      </table>
      <p>
        A blocking hook could also signal with exit code 2, but Claude Code prefixes stderr
        with the hook script&apos;s path, so the agent sees noise instead of a reason. We return
        structured JSON instead. A refusal from AgentFox reads like this:
      </p>
      <Code lang="json" title="PreToolUse deny" copy={false}>{`{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "AgentFox: This runs code fetched at the moment of execution, which nothing reviewed.; command pipes a downloaded script straight into a shell (action.remote_code_execution, remote-code-execution)"
  }
}`}</Code>
      <p>
        One design choice falls out of the hook model: when the policy says{" "}
        <em>escalate</em>, the hook renders it as a deny. In the middle of a tool call there is
        nobody to escalate to, and a hook that waits for an approval would hang the session.
      </p>

      <h2 id="posttooluse">The one that cannot: PostToolUse</h2>
      <p>
        The Claude Code documentation describes <code>decision: &quot;block&quot;</code> for{" "}
        <code>PostToolUse</code>, and it is easy to read that as containment. In our probe the
        command still ran and its output still came back. What the block does is put a reason
        in front of the model, telling it to treat the result as untrusted.
      </p>
      <p>
        That is still useful. <code>PostToolUse</code> is where an injection arriving inside a
        fetched page or a file&apos;s contents is caught, before the model acts on it. It is the
        right hook for detection. It is the wrong hook for anything you need to prevent, which
        is exactly the distinction our <Link href="/hooks">coding agents page</Link> is built
        around.
      </p>

      <InlineCTA
        title="Which hook does what, in one page"
        body="The evidence behind each row, the Claude Code version it was checked on, and what each hook can and cannot do."
        href="/hooks"
        label="Coding agent guardrails"
        secondary={{ href: "/docs/guides/coding-agents", label: "Setup guide" }}
      />

      <h2 id="install">Install a working baseline</h2>
      <p>Print the configuration first, then write it:</p>
      <Code>{`agentfox admin hooks install --agent claude-dev           # prints the config
agentfox admin hooks install --agent claude-dev --write   # merges into .claude/settings.json
agentfox admin hooks daemon                               # a warm process the hooks talk to`}</Code>
      <p>
        The hook config is merged into your existing <code>.claude/settings.json</code>. It
        refuses to overwrite a file that is not valid JSON and skips an event that is already
        installed. All three events run the same command:
      </p>
      <Code lang="json" title=".claude/settings.json (excerpt)" copy={false}>{`{
  "hooks": {
    "PreToolUse": [
      { "matcher": "*", "hooks": [{ "type": "command",
        "command": "agentfox hooks run --harness claude --agent claude-dev" }] }
    ],
    "PostToolUse": [
      { "matcher": "*", "hooks": [{ "type": "command",
        "command": "agentfox hooks run --harness claude --agent claude-dev" }] }
    ],
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command",
        "command": "agentfox hooks run --harness claude --agent claude-dev" }] }
    ]
  }
}`}</Code>
      <p>
        The <code>--write</code> also sets up a baseline, which matters more than it sounds.
        An earlier version installed the hooks and nothing else, and default deny then refused
        everything, <code>ls</code> included. Now it registers the agent in{" "}
        <code>development</code>, declares Claude Code&apos;s built-in tools with an impact (
        <code>Bash</code> is a write, <code>Read</code>, <code>Grep</code> and{" "}
        <code>WebFetch</code> are reads, <code>Task</code> is high impact), grants them, and
        binds the <code>coding-agent</code> pack to that agent in observe mode.
      </p>
      <p>
        Latency is the reason for the daemon. Starting the CLI cold for every call takes about
        3.9 seconds; a call to the warm daemon takes about 6 milliseconds. It listens on a Unix
        socket under the state directory rather than on HTTP, so only your user can reach it.
      </p>

      <h2 id="what-gets-stopped">What gets stopped</h2>
      <p>
        The shell rules come from the <code>tool-containment</code> pack, which ships enforcing
        and fails closed. These are real commands checked against it:
      </p>
      <table>
        <thead>
          <tr>
            <th>Command</th>
            <th>Rule</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          <tr><td><code>cat .env</code></td><td><code>secrets.credential_file</code></td><td>Blocked</td></tr>
          <tr><td><code>curl … | sh</code></td><td><code>action.remote_code_execution</code></td><td>Blocked</td></tr>
          <tr><td><code>rm -rf build</code></td><td><code>shell.destructive</code></td><td>Refused</td></tr>
          <tr><td><code>git push --force origin main</code></td><td><code>shell.destructive</code></td><td>Refused</td></tr>
          <tr><td><code>agentfox policy observe tool-containment</code></td><td><code>control_plane.tamper</code></td><td>Blocked</td></tr>
          <tr><td><code>git reset --hard HEAD~3</code></td><td><code>action.history_rewrite</code></td><td>Escalate, shown as deny</td></tr>
          <tr><td><code>terraform apply</code></td><td><code>action.infrastructure_mutation</code></td><td>Escalate, shown as deny</td></tr>
          <tr><td><code>npm publish</code></td><td><code>action.supply_chain_publish</code></td><td>Escalate, shown as deny</td></tr>
        </tbody>
      </table>
      <p>
        <code>control_plane.tamper</code> deserves a note. An agent that can switch its own
        guardrail to observe mode has no guardrail, so that rule is protected: a version of the
        pack without it will not load.
      </p>
      <p>
        The <code>coding-agent</code> pack adds detection tuned for a developer machine:
        injection in fetched content is blocked at a lower threshold than the baseline, secrets
        in fetched content are blocked, and an injection the model appears to adopt in its
        reasoning is escalated. It ships in observe mode, so read what it would have done
        before you run <code>agentfox policy enforce coding-agent</code>.
      </p>

      <h2 id="limits">Limits worth knowing</h2>
      <ul>
        <li>
          <strong>It fails open.</strong> If the daemon is down, the hook allows the call and
          warns on stderr that it was not checked. A developer&apos;s session keeps working;
          you should know that is the trade.
        </li>
        <li>
          <strong>Local only.</strong> Hooks cover the Claude Code harness on the machine they
          are installed on. Cloud sessions and other coding agents need the{" "}
          <Link href="/control-points">gateway or the SDK</Link>.
        </li>
        <li>
          <strong>Shell rules are narrow deny-lists.</strong> They are deliberate and readable,
          and they are not a shell parser. A plain <code>git push</code> is allowed; only a
          force push is caught.
        </li>
        <li>
          <strong>Shell fields only.</strong> Credential-file matching reads shell commands. We
          have not shown that the <code>Read</code> tool pointed at <code>.env</code> is
          refused, so do not assume it.
        </li>
        <li>
          <strong>MCP tools start refused.</strong> They have no grant, so default deny refuses
          them until you grant them. <code>agentfox policy proposals from-traffic</code>{" "}
          proposes grants from what you actually used. See{" "}
          <Link href="/blog/mcp-rug-pull-tool-poisoning">MCP rug pulls</Link> for why you want
          that.
        </li>
        <li>
          <strong>Version-bound.</strong> Every row above was checked on one Claude Code
          version. Hook semantics can change, and we re-probe when they do.
        </li>
      </ul>

      <InlineCTA
        title="Put guardrails on your coding agent in five minutes"
        body="Install, write the hooks, start the daemon, and run in observe mode for a day before you enforce."
        href="/docs/guides/coding-agents"
        label="Follow the guide"
        secondary={{ href: "/playground", label: "Try the playground" }}
      />
    </>
  );
}
