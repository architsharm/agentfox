import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, Step, Steps, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Policies and tuning",
  description:
    "The Rules tab, the policy editor with validate, simulate and promote, hierarchy placement, canary rollouts, guardrail tuning, judgment posture and change proposals.",
  path: "/docs/app/policies",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Web app</p>
      <h1>Policies and tuning</h1>
      <p className="docs-lede">
        Policies has three tabs: Rules (what each policy checks and whether it observes or
        enforces), Guardrail tuning (whether the detectors behind those rules are right, fast
        and not silenced), and Judgment posture (whether any text may leave the deployment to
        be judged).
      </p>
      <InTheApp path="/app/policies">Policies</InTheApp>

      <h2>When to use this</h2>
      <ul>
        <li>To promote a policy from observe to enforce, after checking what it would block.</li>
        <li>To add or change a rule, for everyone or for one agent.</li>
        <li>To act on a false positive: suppress it for a while, or propose a threshold change.</li>
      </ul>

      <h2>Rules tab</h2>
      <p>
        <code>/app/policies</code> (filter with <code>?agent=</code>). From top to bottom:
      </p>
      <ul>
        <li>
          <strong>Pending review</strong>: policies a scan proposed. They are already bound in
          observe, so they block nothing. <strong>Approve</strong> acknowledges one;{" "}
          <strong>Reject</strong> discards it.
        </li>
        <li>
          <strong>All policies</strong>: name and key, description, latest version, mode (
          <code>observe</code>, <code>enforce</code>, or <code>unbound</code>), rule count, and{" "}
          <strong>Review &amp; edit →</strong>. One policy usually covers many agents by name
          pattern, so filtering by agent shows every policy whose scope matches it. From{" "}
          <code>GET /api/policies</code>.
        </li>
        <li>
          <strong>Detectors</strong>: turned on, available but off, and not installed. Under it,{" "}
          <strong>Every check available</strong> (the detector catalogue) lists each check, the
          surfaces it reads, its state, its average time on your traffic, and what turns it on:
          <code> add &lt;key&gt; to enabled_detectors</code> for an installed one, or the{" "}
          <code>pip install</code> line for one that is not. Checks wrapped from Guardrails AI
          Hub carry their own licences and none ships enabled.
        </li>
        <li>
          <strong>Judgment tiers</strong>: a read-only summary of the judgment posture (see the
          third tab).
        </li>
        <li>
          <strong>Attack simulations</strong>: the built-in probe library (22 probes in this
          build) with category, surface, severity, OWASP and ATLAS ids, and a button to run
          them on <Link href="/docs/app/evals#redteam">Evaluation</Link>.
        </li>
        <li>
          <strong>Change proposals</strong>: there is no screen for proposals. This section is a
          table of the commands and HTTP routes (below).
        </li>
      </ul>
      <Output title="agentfox policy list (excerpt)">{`policy                 version  mode     rules
baseline               v1       observe  13
eu-ai-act-high-risk    v1       observe  7
tool-containment       v1       enforce  25`}</Output>

      <h2 id="editor">A policy: rules, editor, versions, canary</h2>
      <InTheApp path="/app/policies/baseline">Policies → a policy → Review &amp; edit</InTheApp>
      <p>
        <code>/app/policies/&lt;key&gt;</code> loads <code>GET /api/policies/&#123;key&#125;</code>.
        It shows the current mode and rule count, then <strong>Rules in this policy</strong>: each
        rule&apos;s description and id, <strong>when it fires</strong> in words (&quot;on input ·
        INJECTION detected, score ≥ 0.85&quot;), effect and severity. Rules are checked in
        order; the first whose conditions match decides.
      </p>
      <p>
        <strong>Edit these rules — builder or YAML</strong> opens the editor. A policy that has
        no rules yet (a new one, or a scan proposal) opens with one real example rule and a
        &quot;Nothing is saved yet&quot; banner.
      </p>
      <ul>
        <li>
          <strong>Rule builder</strong>: When this happens (injection, personal data, secrets,
          unsafe content, wrong output format), how confident (0.85, 0.7 or 0.5), where to
          check (input, output, retrieved, tool arguments, tool results), then do this (block,
          redact, mask, ask a human, decline to answer, just log), severity, and a note.{" "}
          <strong>Add this rule</strong> writes YAML into the editor below; nothing is saved.
        </li>
        <li>
          <strong>The YAML</strong>: every builder choice compiles to it, and you can edit it
          directly. The schema is in <Link href="/docs/reference/policies">Policy language</Link>.
        </li>
        <li>
          <strong>Where does this apply?</strong> Level (<code>org</code>, <code>team</code>,{" "}
          <code>agent</code>, <code>user</code>), a scope id or glob such as{" "}
          <code>payments-*</code> (not used at org level), and compose:{" "}
          <code>extend</code> adds to broader rules, <code>restrict</code> may only tighten,{" "}
          <code>override</code> may loosen rules the broader level marked overridable. The
          narrowest level wins on ties.
        </li>
        <li>
          <strong>Validate</strong> runs the same check the engine runs at enforcement time (
          <code>POST /api/policies/validate</code>) and reports the rule count and controls. It
          also runs the lint, so a rule that can never fire, or an unknown value such as{" "}
          <code>surface: [toolargs]</code>, is reported as invalid.
        </li>
        <li>
          <strong>Save new version</strong> stores an immutable new version (
          <code>POST /api/policies</code>) and reloads. It never changes what is in force:
          the live version and its mode stay as they are, whatever <code>mode:</code> the YAML
          says, and the header shows the new one as saved, not live. A policy saved for the
          first time goes live in observe, which records and blocks nothing.
        </li>
        <li>
          <strong>Simulate against recent traffic</strong> replays recorded decisions against
          the YAML in the editor (<code>POST /api/policies/simulate</code>) and says how many
          would be newly blocked, newly escalated, newly allowed, or unchanged.
        </li>
        <li>
          <strong>Promote to enforce</strong> makes the newest saved version live in enforce;{" "}
          <strong>Make vN live in observe</strong> (shown when a saved version is not live) makes
          it live in observe; <strong>Set observe</strong> demotes the live version (
          <code>POST /api/policies/&#123;key&#125;/mode</code>, with <code>version</code> when a
          saved version is being made live).
        </li>
      </ul>
      <Callout kind="note" title="The simulate gate">
        <p>
          <strong>Promote to enforce</strong> refuses to act until you have run Simulate on the
          exact text in the editor; change one character and you must simulate again. Then it
          asks for confirmation, quoting what the simulation found.
        </p>
        <p>
          The server enforces the same rule: <code>POST /api/policies/&#123;key&#125;/mode</code>{" "}
          with <code>mode: enforce</code> answers 409 unless a simulation of exactly that
          version&apos;s rules has been recorded. Saving cannot enforce or demote anything, so
          promotion is the only way a policy&apos;s mode changes. Demoting to observe never
          needs a simulation.
        </p>
      </Callout>

      <h3>Worked example: an agent-level redaction rule</h3>
      <Steps>
        <Step title="Write or build the rule">
          <Code lang="yaml" title="support-triage-pii.yaml">{`key: support-triage-pii
name: Support triage PII
description: Redact personal data in what support-triage sends back.
version: 1
mode: observe
default_effect: allow
fail_mode: open
scope:
  agents: ["support-triage"]

rules:
  - id: support.pii.output
    description: "The content contains personal information (names, emails, SSNs, phone numbers…)"
    when:
      surface: [output]
      detection: {entity_prefix: PII, min_score: 0.7}
    effect: redact
    severity: high
    reason: "Personal data in a support reply."`}</Code>
        </Step>
        <Step title="Validate, then simulate">
          <p>In the editor, or with the same checks from the CLI:</p>
          <Code>{`agentfox policy validate support-triage-pii.yaml
agentfox policy simulate -f support-triage-pii.yaml --agent support-triage`}</Code>
          <Output>{`valid — support-triage-pii v1, 1 rules, mode=observe
  controls: []
  compiles to 33 lines of Rego
support-triage-pii simulated against 7 decisions
  unchanged        7
  newly blocked    0
  newly escalated  0
  newly allowed    0

No production traffic would newly block.`}</Output>
          <p>
            The editor shows the same result as &quot;Safe to promote — replayed 7 recent
            decision(s): 0 newly blocked, 0 newly escalated, 0 newly allowed, 7 unchanged.&quot;
            Each recorded decision is replayed with the candidate in place of its own pack
            (whichever version of it was in force then); rules that fired from other packs
            still count, so a change in the counts is a change in the whole outcome. Newly
            blocked, escalated and allowed decisions are each listed.{" "}
            <code>policy simulate</code> exits non-zero when anything would be newly blocked, so
            it can gate a pull request.
          </p>
        </Step>
        <Step title="Save at agent level, then promote">
          <p>
            Set <strong>Where does this apply?</strong> to <code>agent</code> /{" "}
            <code>support-triage</code> / <code>extend</code>, press{" "}
            <strong>Save new version</strong>, then <strong>Simulate</strong> and{" "}
            <strong>Promote to enforce</strong>. From the CLI, promoting the live version is:
          </p>
          <Code>{`agentfox policy enforce support-triage-pii`}</Code>
        </Step>
      </Steps>

      <h3>Version history</h3>
      <p>Every saved version, newest first: author, notes (&quot;edited from the dashboard&quot;), rule count, when.</p>

      <h3 id="canary">Canary rollout</h3>
      <p>
        Shown once a policy has two or more versions. Pick a version and{" "}
        <strong>Start canary rollout</strong> (<code>POST /api/policies/&#123;key&#125;/canary/start</code>).
        The candidate takes a share of traffic in steps of 10%, 25%, 50% and 100%, against the
        stable version. The panel shows decisions and block rate for each side.
      </p>
      <ul>
        <li>
          <strong>Check health &amp; advance</strong> (<code>/canary/advance</code>) moves to the
          next step only when both sides have at least 20 decisions and at least an hour has
          passed at this step; if the candidate&apos;s block rate exceeds stable&apos;s by more than
          15 points, it rolls back automatically. Until then it reports what it is waiting for.
        </li>
        <li>
          <strong>Roll back now</strong> (<code>/canary/rollback</code>) ends it, recording
          &quot;manual rollback by &lt;you&gt;&quot;.
        </li>
      </ul>
      <Output title="POST /api/policies/support-triage-pii/canary/start (excerpt)">{`{"id":"cny_01m469s5s681tc1gyb","status":"rolling","percent":10,"step_index":0,"steps":[10,25,50,100],
"stable_version":1,"candidate_version":2,"max_block_rate_delta":0.15,…,"min_dwell_seconds":3600,
…,"min_sample":20,"started_by":"admin@example.com",…}`}</Output>
      <p>There is no CLI command for canaries; use the page or the routes above.</p>

      <h2 id="tuning">Guardrail tuning tab</h2>
      <InTheApp path="/app/policies?tab=advanced&sec=tuning">Policies → Guardrail tuning</InTheApp>
      <p>
        Are the checks catching real problems, slowing agents down, or silenced? Filter by
        agent. Warning tiles appear only when something needs a person: checks that ran late
        or were skipped above 1%, and suppressions expiring this week. Then a strip: checks on,
        checks run in the last 7 days, the late-or-skipped rate, active suppressions.
      </p>
      <ul>
        <li>
          <strong>Suppressions</strong>: detector, scope (an agent or all agents, and an entity
          type), reason, hits (with a <code>never used</code> tag at zero), expiry countdown, and{" "}
          <strong>revoke</strong> (<code>DELETE /api/guardrails/suppressions/&#123;id&#125;</code>).
          Every suppression expires; a permanent exception looks exactly like a detector that
          stopped working.
        </li>
        <li>
          <strong>Feedback log</strong>: the last 20 labels filed from traces: detector, entity,
          label, note, who, status, a link to the trace. An open false positive has{" "}
          <strong>suppress 30d</strong>, which creates a suppression for that detector, agent and
          entity for 30 days (<code>POST /api/guardrails/suppressions</code>) and marks the
          feedback applied. Creating and revoking suppressions needs owner, admin or security.
        </li>
        <li>
          <strong>How often each check is actually right</strong> (collapsed): labelled count
          (<code>too few</code> below five), false positives, precision, and a recommendation
          such as <code>raise threshold</code> or <code>insufficient data</code>, with its
          rationale.
        </li>
        <li>
          <strong>How much each check slows things down</strong> (collapsed): per detector,
          version, runs, p50, p95 and worst case, with availability, against the budget (300 ms
          per call and 40 ms per detector by default).
        </li>
      </ul>
      <Output title="Suppressions table, page text, after suppress 30d">{`detector             scope                                         reason                                          hits         expires
injection.heuristic  support-triage  INJECTION.INSTRUCTION_OVERRIDE  quoted text in a ticket, not an instruction  0 never used  2026-11-04  revoke`}</Output>

      <h2 id="judgment">Judgment posture tab</h2>
      <InTheApp path="/app/policies?tab=advanced&sec=judges">Policies → Judgment posture</InTheApp>
      <p>
        Whether optional evaluators may judge what code cannot, and whether a customer&apos;s
        text may leave the deployment for that. Loads and saves{" "}
        <code>GET</code>/<code>PUT /api/judgment/posture</code>.
      </p>
      <ul>
        <li>
          A banner says either &quot;Nothing leaves this deployment&quot; or &quot;This tenant
          sends payloads to a third party&quot;. With egress off at deployment level (
          <code>allow_egress = false</code>, the default), tiers that send data cannot be
          selected here.
        </li>
        <li>
          <strong>Tiers</strong>: <code>deterministic</code>, <code>local_model</code>,{" "}
          <code>local_llm</code>, <code>jev</code>, <code>llm</code>. Tiers that send data off the
          machine are marked; a disabled tier says why.
        </li>
        <li>
          <strong>Personal data on the way out</strong>: <code>block</code>, <code>redact</code>{" "}
          or <code>allow</code>. Options looser than the deployment&apos;s floor are disabled.
        </li>
        <li><strong>Backend</strong> and <strong>Fail closed</strong> (a tier&apos;s outage denies the request instead of passing it unjudged).</li>
        <li><strong>Why</strong> is required and goes to the audit chain with the before and after.</li>
        <li>
          <strong>I am turning on a tier that sends data off this machine…</strong> must be ticked
          for any change in that direction. Tightening needs no confirmation.
        </li>
        <li>
          <strong>What each decision kind would use</strong>: for each kind of decision, which
          tiers decide it and which are refused, with the reason.
        </li>
      </ul>
      <p>
        Only owner, admin and security can save; other roles see the form read-only. An
        unticked <strong>Fail closed</strong> saves as fail open.
      </p>

      <h2 id="proposals">Change proposals</h2>
      <p>
        AgentFox proposes changes to its own configuration rather than making them: threshold
        changes from your labels, and grants and tool declarations learned from traffic. A
        loosening is never applied automatically. There is no screen for proposals; the Rules
        tab lists the commands, which are:
      </p>
      <TaskTable
        rows={[
          { task: "Draft grants and declarations from recorded tool calls", run: "agentfox policy proposals from-traffic --since 7d" },
          { task: "Draft threshold changes from false-positive labels", run: "agentfox policy proposals from-labels --days 30" },
          { task: "See what is waiting", run: "agentfox policy proposals list --status proposed" },
          { task: "Read one in full", run: "agentfox policy proposals show PROPOSAL_ID" },
          { task: "Approve one", run: "agentfox policy proposals approve PROPOSAL_ID --actor you@example.com --note \"…\"" },
          { task: "Put it into effect", run: "agentfox policy proposals apply PROPOSAL_ID --actor you@example.com" },
          { task: "Undo it", run: "agentfox policy proposals rollback PROPOSAL_ID --actor you@example.com --reason \"…\"" },
          { task: "Record whether it worked", run: "agentfox policy proposals verify PROPOSAL_ID --actor you@example.com --note \"…\"" },
        ]}
      />
      <p>
        Apply, rollback and verify need the <code>policy_production</code> permission (owner,
        admin, security). The CLI asks for <code>--actor</code> on every decision; over
        HTTP the actor is whoever the token belongs to. The in-app table shows the commands under their older{" "}
        <code>proposals</code> name; the current names are above. The full loop is in{" "}
        <Link href="/docs/guides/contain-tool-calls">Contain tool calls</Link>.
      </p>

      <h2>Common tasks</h2>
      <TaskTable
        rows={[
          { task: "List policies and modes", run: "agentfox policy list" },
          { task: "Validate a policy file", run: "agentfox policy validate support-triage-pii.yaml" },
          { task: "Replay traffic against a candidate", run: "agentfox policy simulate -f support-triage-pii.yaml" },
          { task: "Promote / demote", run: "agentfox policy enforce baseline" },
          { task: "Demote", run: "agentfox policy observe baseline" },
          { task: "What applies to one agent", run: "agentfox policy effective --agent payments-ops" },
        ]}
      />

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong>&quot;Run Simulate against the currently saved rules first&quot;</strong> on
          Promote: the editor text changed since the last simulation. Simulate again.
        </li>
        <li>
          <strong>A policy went back to observe after you saved.</strong> The YAML said{" "}
          <code>mode: observe</code>. Promote it again, or save with the mode you want.
        </li>
        <li>
          <strong>The mode column says <code>unbound</code> after a canary.</strong> In this
          build the list reads the latest version&apos;s binding, which a canary start or rollback
          replaces. <code>agentfox policy effective --agent …</code> shows what is actually in
          force.
        </li>
        <li>
          <strong>&quot;Change these on Settings → Judgment posture&quot;</strong> under Judgment
          tiers leads to a missing page; the setting is the Judgment posture tab.
        </li>
        <li>
          <strong>Tool containment blocks with no detector involved.</strong> It reads no text;
          it checks grants, provenance and blast radius. Tune it with grants, not suppressions.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>No screen for proposals, grants or tool declarations.</li>
        <li>Simulation replays recorded decisions; it cannot predict traffic you have not seen.</li>
        <li>Suppression length from the web app is fixed at 30 days.</li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/reference/policies", label: "Policy language", why: "every field the editor writes" },
          { href: "/docs/guides/tuning", label: "Tune detectors", why: "the feedback loop end to end" },
          { href: "/docs/app/traces", label: "Traces", why: "where feedback is filed" },
        ]}
      />
    </article>
  );
}
