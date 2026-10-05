import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, Step, Steps, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Prove it to an auditor",
  description:
    "The one-page report, evidence packages an auditor can verify without AgentFox, the tamper-evident chain, and control posture against draft framework mappings.",
  path: "/docs/guides/audit-evidence",
});

const cli = (path: string) => `/docs/reference/cli#cmd-${path.replace(/\s+/g, "-")}`;

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Guide</p>
      <h1>Prove it to an auditor</h1>
      <p className="docs-lede">
        Turn what AgentFox recorded into something another person can check: a one-page
        summary, an evidence package with a standard-library verifier, and control status
        computed from what your agents actually did.
      </p>

      <h2>When to use this</h2>
      <ul>
        <li>
          Someone asks what your agents did last week and what was stopped. Send them{" "}
          <Link href={cli("report summary")}>
            <code>agentfox report</code>
          </Link>
          .
        </li>
        <li>
          An auditor, a customer&apos;s security team or your own risk function wants
          records they can verify without trusting you. Build an{" "}
          <Link href={cli("report evidence")}>evidence package</Link>.
        </li>
        <li>
          You need to know where you stand against the EU AI Act, ISO/IEC 42001, NIST AI
          RMF, SOC 2, OWASP or MITRE ATLAS, and what a reviewer has to sign off before you
          can make that claim.
        </li>
      </ul>
      <p>
        Everything here reads what was recorded while your agents ran. If nothing was
        recorded, there is nothing to prove: start with{" "}
        <Link href="/docs/guides/python-auto">One line in Python</Link> or{" "}
        <Link href="/docs/guides/gateway">the gateway</Link>, and come back once traffic
        has flowed.
      </p>

      <Callout kind="warning" title="Every framework mapping is a draft">
        The mappings from AgentFox controls to framework clauses were written by engineers
        from the framework texts. Compliance counsel has not reviewed them and they are not
        legal advice. The CLI, the one-page summary and every evidence package label each
        unreviewed mapping <code>DRAFT — UNVERIFIED / NOT LEGAL ADVICE</code>. A mapping
        stops being a draft only when a named, qualified person signs it off (see{" "}
        <a href="#signoff">Sign off a mapping</a>). Nothing on this page is a
        certification.
      </Callout>

      <TaskTable
        rows={[
          { task: "One-page summary of what happened", run: "agentfox report", href: cli("report summary") },
          { task: "Evidence package for an auditor", run: "agentfox report evidence --agent payments-ops --since-days 30", href: cli("report evidence") },
          { task: "Check the audit chain", run: "agentfox report verify", href: cli("report verify") },
          { task: "Anchor the chain with a signed checkpoint", run: "agentfox admin checkpoint", href: cli("admin checkpoint") },
          { task: "Control posture for one framework", run: "agentfox report status --framework eu-ai-act", href: cli("report status") },
          { task: "Hand a reviewer what they must sign", run: "agentfox report review-packet --framework soc2 --out soc2-review.md", href: cli("report review-packet") },
        ]}
      />

      <h2>The one-page summary</h2>
      <p>
        <code>agentfox report</code> with no subcommand prints{" "}
        <Link href={cli("report summary")}>
          <code>report summary</code>
        </Link>
        : what is running, what was contained, what observe-mode rules would have stopped,
        and coverage against the OWASP agentic threat list. It is written for a person who
        has never opened AgentFox. Narrow it to one agent and a shorter window:
      </p>
      <Code>{`agentfox report summary --agent payments-ops --since 24h`}</Code>
      <Output>{`# AgentFox summary

*payments-ops, 2026-10-04 to 2026-10-05. Generated 2026-10-05T15:01:09+00:00.*

**In short:** 1 agent(s) under management; 2 risky action(s) stopped or held for approval; 3 more that observe-mode rules recorded but did not stop; 1 agent(s) with a risky combination.

## What is running

- **Agents:** 1
  - payments-ops — production, high risk, marcus@example.com, demo data
…
## What was contained

2 action(s) stopped or held for approval. By cause:

- Needs a person's sign-off: 1
- Data from an untrusted source: 1
- Outside the limits of its permission: 1

Examples:

- payments-ops tried to payments.transfer with data that came from another tool's output (held for approval)
- payments-ops tried to payments.transfer outside the limits of its permission (contained)
- payments-ops tried to payments.transfer, which needs a person's sign-off first (held for approval)

## Still in observe mode

These policies record what they would do without acting on it: Baseline runtime guardrails, EU AI Act — high-risk system controls.

3 action(s) would have been stopped or held. By cause:

- Needs a person's sign-off: 3
…
## Coverage against OWASP Agentic AI — Threats and Mitigations (T1–T15) — DRAFT — UNVERIFIED

> The mapping from these threats to our controls is an engineering draft. It has not been reviewed by compliance counsel or an auditor and is not a certification.

| Threat | Status |
| --- | --- |
| Memory Poisoning | Watching only — nothing blocked |
| Tool Misuse | Blocking |
…
Controls with working evidence: 35 of 43; 2 have no evidence yet.`}</Output>
      <p>
        One action can have more than one cause, so the cause counts can add up to more
        than the headline number.
      </p>
      <p>The options:</p>
      <ul>
        <li>
          <code>--agent</code> / <code>-a</code>: only this agent. Repeat it for several.
          Default: all agents.
        </li>
        <li>
          <code>--since</code>: how far back, as <code>24h</code>, <code>7d</code>,{" "}
          <code>2w</code> or <code>30d</code>. Default <code>7d</code>.
        </li>
        <li>
          <code>--format</code> / <code>-f</code>: <code>md</code> (default) or{" "}
          <code>html</code>. Anything else exits 2 with{" "}
          <code>unknown format &apos;pdf&apos; — use md or html</code>.
        </li>
        <li>
          <code>--out</code> / <code>-o</code>: write to a file instead of printing.
        </li>
      </ul>
      <Code>{`agentfox report summary --since 30d --format html --out summary.html`}</Code>
      <Output>{`wrote summary.html`}</Output>
      <p>
        The HTML file is self-contained (inline styles, light and dark), so you can attach
        it to an email or a ticket.
      </p>

      <h2>Build an evidence package</h2>
      <Steps>
        <Step title="Build it">
          <Code>{`agentfox report evidence --agent payments-ops --since-days 30 --requested-by auditor@example.com`}</Code>
          <Output>{`evidence package
…/var/evidence/evd_01m469avnz63xaz363.zip
  period                   2026-09-05 → 2026-10-05
  agents                   1
  traces                   0
  decisions                25
  audit entries            26
  checkpoints              1
  approvals                3
  eval runs                1
  findings                 26
  control statuses         86
  reviewed mappings        0
  draft mappings included  317
  chain verification       valid

Verify independently: unzip, then \`python3 verify_chain.py\``}</Output>
          <p>
            The zip lands in <code>var/evidence/</code> under your state directory (
            <code>AGENTFOX_STATE_DIR</code>; see{" "}
            <Link href="/docs/install">Install and configure</Link>). Building a package
            writes an <code>evidence.exported</code> entry to the audit chain, with{" "}
            <code>--requested-by</code> as the actor: who pulled the evidence is itself
            evidence.
          </p>
        </Step>
        <Step title="Look inside">
          <Code>{`unzip -l evd_01m469avnz63xaz363.zip`}</Code>
          <Output>{`Archive:  evd_01m469avnz63xaz363.zip
  Length      Date    Time    Name
---------  ---------- -----   ----
     2939  10-05-2026 20:31   SUMMARY.md
     4651  10-05-2026 20:31   SUMMARY.html
    34265  10-05-2026 20:31   audit_entries.json
      268  10-05-2026 20:31   audit_checkpoints.json
        2  10-05-2026 20:31   traces.json
    19176  10-05-2026 20:31   decisions.json
     7130  10-05-2026 20:31   policy_versions.json
      372  10-05-2026 20:31   agents.json
     1301  10-05-2026 20:31   approvals.json
     1956  10-05-2026 20:31   eval_runs.json
     8989  10-05-2026 20:31   findings.json
    29862  10-05-2026 20:31   control_status.json
    69441  10-05-2026 20:31   framework_mappings.json
      234  10-05-2026 20:31   risk_assessments.json
      176  10-05-2026 20:31   chain_verification.json
     3545  10-05-2026 20:31   verify_chain.py
     3565  10-05-2026 20:31   README.txt
     3225  10-05-2026 20:31   manifest.json
---------                     -------
   191097                     18 files`}</Output>
        </Step>
      </Steps>

      <table>
        <thead>
          <tr>
            <th>File</th>
            <th>What it holds</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>README.txt</code></td>
            <td>What each file is, how to verify, and the package&apos;s limitations. Start here.</td>
          </tr>
          <tr>
            <td><code>SUMMARY.md</code>, <code>SUMMARY.html</code></td>
            <td>The same one-page summary as <code>agentfox report</code>, for the package&apos;s scope and period.</td>
          </tr>
          <tr>
            <td><code>audit_entries.json</code>, <code>audit_checkpoints.json</code></td>
            <td>The hash-chained audit log for the period, and the signed checkpoints over it.</td>
          </tr>
          <tr>
            <td><code>decisions.json</code>, <code>policy_versions.json</code></td>
            <td>Every policy decision with the rules that fired, and the exact policy version in force. Policy versions are immutable.</td>
          </tr>
          <tr>
            <td><code>traces.json</code></td>
            <td>Full execution paths for the agents in scope. Content is redacted at capture.</td>
          </tr>
          <tr>
            <td><code>approvals.json</code>, <code>findings.json</code>, <code>eval_runs.json</code></td>
            <td>Who approved what, what the platform raised, and evaluation results.</td>
          </tr>
          <tr>
            <td><code>control_status.json</code>, <code>framework_mappings.json</code>, <code>risk_assessments.json</code></td>
            <td>Control status computed from telemetry, every control-to-clause mapping (each with a <code>chip</code> of <code>REVIEWED</code> or <code>DRAFT — UNVERIFIED / NOT LEGAL ADVICE</code>), and per-agent risk.</td>
          </tr>
          <tr>
            <td><code>chain_verification.json</code></td>
            <td>AgentFox&apos;s own verification result. The auditor should not rely on it; that is what the next file is for.</td>
          </tr>
          <tr>
            <td><code>verify_chain.py</code></td>
            <td>A standard-library verifier that re-derives every digest from <code>audit_entries.json</code>.</td>
          </tr>
          <tr>
            <td><code>manifest.json</code></td>
            <td>Scope, counts, code and catalog versions, and the SHA-256 of every other file.</td>
          </tr>
        </tbody>
      </table>
      <p>
        A draft mapping row in <code>framework_mappings.json</code> looks like this:
      </p>
      <Output title="framework_mappings.json (one row)">{`{
 "control_key": "…",
 "framework": "eu-ai-act",
 "reference": "Art. 11 — technical documentation",
 "review_status": "draft",
 "reviewed_by": null,
 "chip": "DRAFT — UNVERIFIED / NOT LEGAL ADVICE"
}`}</Output>

      <h2>How an auditor verifies it without AgentFox</h2>
      <p>
        The recipient needs the zip and any Python 3. They do not install AgentFox, and
        nothing calls your API. This was run with the system Python 3.9, in isolated mode
        and with an empty environment, where <code>import agentfox</code> fails:
      </p>
      <Code>{`unzip evd_01m469avnz63xaz363.zip -d evidence && cd evidence
env -i /usr/bin/python3 -I -c "import agentfox"
env -i /usr/bin/python3 -I verify_chain.py`}</Code>
      <Output>{`…
ModuleNotFoundError: No module named 'agentfox'
note: AGENTFOX_AUDIT_KEY not set - checkpoint signatures not verified
entries checked: 26 (seq 1..26)
CHAIN INTACT`}</Output>
      <p>
        The script exits 0 when the chain is intact and 1 otherwise. It recomputes each
        entry&apos;s payload digest and entry digest, checks every entry links to the one
        before it, and reports gaps in the sequence. Here is what an edit looks like. This
        changes a recorded block into an allow:
      </p>
      <Code lang="python" title="tamper.py">{`import json
rows = json.load(open("audit_entries.json"))
row = next(r for r in rows if r["seq"] == 8)
row["payload"]["verdict"] = "allow"          # pretend the block never happened
json.dump(rows, open("audit_entries.json", "w"), indent=2)`}</Code>
      <Code>{`python3 tamper.py && python3 -I verify_chain.py; echo "exit $?"`}</Code>
      <Output>{`note: AGENTFOX_AUDIT_KEY not set - checkpoint signatures not verified
entries checked: 26 (seq 1..26)
CHAIN INVALID - 1 break(s):
  seq 8  payload_mismatch: payload does not match its digest
exit 1`}</Output>

      <h3>Check the manifest too</h3>
      <p>
        <code>verify_chain.py</code> covers the audit log. To check that no other file in
        the package changed after it was built, compare each file against the SHA-256 in{" "}
        <code>manifest.json</code>:
      </p>
      <Code lang="python" title="check_manifest.py">{`import hashlib, json, sys

manifest = json.load(open("manifest.json"))
bad = [
    name for name, meta in manifest["files"].items()
    if hashlib.sha256(open(name, "rb").read()).hexdigest() != meta["sha256"]
]
print("manifest:", "all files match" if not bad else "changed: " + ", ".join(bad))
sys.exit(1 if bad else 0)`}</Code>
      <Output>{`manifest: all files match`}</Output>
      <p>
        After the edit above, the same script prints{" "}
        <code>manifest: changed: audit_entries.json</code> and exits 1.
      </p>

      <h3>Checkpoint signatures: the part that needs a key</h3>
      <p>
        Someone who can rewrite the whole package can also recompute every digest and the
        manifest. What they cannot forge without the signing key is a checkpoint: an HMAC
        over the chain head at a point in time. Give the auditor the key through a separate
        channel and they verify the checkpoints as well:
      </p>
      <Code>{`AGENTFOX_AUDIT_KEY="$KEY_FROM_YOUR_OPERATOR" python3 -I verify_chain.py`}</Code>
      <p>With the right key the output is the same as above, without the note. With the wrong key:</p>
      <Output>{`entries checked: 26 (seq 1..26)
CHAIN INVALID - 1 break(s):
  seq 25  checkpoint_signature: checkpoint signature mismatch`}</Output>

      <Callout kind="warning" title="Set your own signing key before the first checkpoint">
        Out of the box, checkpoints are signed with a built-in development key, and{" "}
        <code>agentfox doctor</code> does not warn about it. Anyone who knows that default
        can forge a checkpoint. Set <code>AGENTFOX_AUDIT_SIGNING_KEY</code> from your secret
        store before you write checkpoints you intend to show anyone. Checkpoints signed
        under an earlier key stop verifying once you change it; there is no key rotation.
      </Callout>

      <h2>Check the chain in place</h2>
      <p>
        On the machine that runs AgentFox,{" "}
        <Link href={cli("report verify")}>
          <code>agentfox report verify</code>
        </Link>{" "}
        re-derives the live chain from the database and checks every checkpoint with the
        configured key. Use <code>--start</code> and <code>--end</code> for a range of
        sequence numbers.
      </p>
      <Code>{`agentfox report verify
agentfox report verify --start 5 --end 12`}</Code>
      <Output>{`chain: 28 entries, head seq 28, 1 checkpoints
CHAIN INTACT — 28 entries verified (seq 1..28)
chain: 28 entries, head seq 28, 1 checkpoints
CHAIN INTACT — 8 entries verified (seq 5..12)`}</Output>
      <p>
        After someone edits a row directly in the database (here, the same change from block
        to allow on sequence 8), it exits 1:
      </p>
      <Output>{`chain: 28 entries, head seq 28, 2 checkpoints
CHAIN TAMPERED — 1 break(s)
  seq 8 payload_mismatch: payload does not match its recorded digest`}</Output>
      <p>
        If the signing key changed since a checkpoint was written, it reports{" "}
        <code>checkpoint seq 25 signature mismatch — checkpoint forged or key changed</code>{" "}
        and also exits 1. Run it in CI or on a schedule and alert on a non-zero exit.
      </p>

      <h3>Write a checkpoint</h3>
      <p>
        AgentFox writes a checkpoint automatically every{" "}
        <code>AGENTFOX_AUDIT_CHECKPOINT_INTERVAL</code> entries (100 by default).{" "}
        <Link href={cli("admin checkpoint")}>
          <code>agentfox admin checkpoint</code>
        </Link>{" "}
        writes one now, over the current head. Do it right before you build a package, so the
        package ends on a signed anchor:
      </p>
      <Code>{`agentfox admin checkpoint`}</Code>
      <Output>{`checkpoint seq 28 digest a69d2a0f38be35e3…`}</Output>

      <h2>Control posture and frameworks</h2>
      <p>
        AgentFox ships a catalog of 43 controls and maps them to seven frameworks. A
        control&apos;s status comes from recorded activity, not from a form: whether the
        evidence it needs exists, whether its rule passed, and whether the chain is intact. A
        control whose evidence source produced nothing reads <code>not_implemented</code>.
      </p>
      <Steps>
        <Step title="Recompute status from telemetry">
          <Code>{`agentfox admin catalog compute`}</Code>
          <Output>{`computed 43 controls over 30 days
  35 effective · 3 degraded · 2 failing · 2 not implemented`}</Output>
          <p>
            <code>--window-days</code> changes the window (default 30). The remaining
            control in this example is <code>not_applicable</code>: its capability was never
            used.
          </p>
        </Step>
        <Step title="Read the posture">
          <Code>{`agentfox report status
agentfox report status --framework eu-ai-act`}</Code>
          <Output>{`all frameworks — 43 controls
  35 effective · 3 degraded · 2 failing · 2 not implemented
  effectiveness 88%`}</Output>
          <p>
            <code>--verbose</code> adds one row per control with the rationale behind its
            status, for example{" "}
            <code>owned_agents / total_agents = 2/4 = 50.0% (effective at 100%)</code>, and,
            with <code>--framework</code>, the gaps the product declares it does not cover
            (for the EU AI Act: conformity assessment, registration in the EU database, and
            the fundamental rights impact assessment filing).
          </p>
          <p>
            Framework keys: <code>eu-ai-act</code>, <code>iso-42001</code>,{" "}
            <code>nist-ai-rmf</code>, <code>soc2</code>, <code>owasp-llm</code>,{" "}
            <code>owasp-agentic</code>, <code>mitre-atlas</code>. A misspelled key is not an
            error: it prints <code>0 controls</code> and exits 0.
          </p>
        </Step>
        <Step title="See coverage and review status per framework">
          <Code>{`agentfox report frameworks`}</Code>
          <Output>{`framework              controls mapped  mappings  reviewed  status
EU AI Act              43/43            70        0         draft
NIST AI RMF            43/43            74        0         draft
ISO/IEC 42001          43/43            51        0         draft
SOC 2                  43/43            64        0         draft
OWASP LLM Top 10       22/43            26        0         draft
OWASP Agentic Threats  19/43            22        0         draft
MITRE ATLAS            9/43             10        0         draft

All mappings are engineering drafts. They are not legal advice and ship inside evidence packages tagged DRAFT
— UNVERIFIED / NOT LEGAL ADVICE until reviewed.`}</Output>
        </Step>
      </Steps>

      <h3>Risk, obligations and the board view</h3>
      <Code>{`agentfox report risk`}</Code>
      <Output>{`agent               risk tier  EU class  residual  assessed  review
support-triage      limited    —         —         no        —
payments-ops        high       high      medium    yes       2027-09-30
hr-screening        limited    —         —         no        —
marketing-copy-bot  limited    —         —         no        —         `}</Output>
      <Code>{`agentfox report obligations`}</Code>
      <Output>{`date        framework  obligation                                   status     agents  build by
2025-02-02  eu-ai-act  Prohibited AI practices                      live       4       —
2026-08-02  eu-ai-act  Transparency obligations                     live       3       —
2026-12-02  eu-ai-act  General-purpose AI model obligations         upcoming   4       2025-12-02
…
2027-12-02  eu-ai-act  Standalone high-risk AI systems              upcoming   1       2026-12-02
2028-08-02  eu-ai-act  High-risk AI embedded in regulated products  upcoming   1       2027-08-03`}</Output>
      <p>
        The obligation calendar is part of the same draft catalog. A row is a date to plan
        for, not a record that the duty was met, and its dates are not legal advice: check
        them against the regulation&apos;s current text.
      </p>
      <Code>{`agentfox report board`}</Code>
      <Output>{`╭─────────────────╮
│ AI risk posture │
╰─────────────────╯
  agents under management  4 (1 shadow, 2 unowned)
  high-risk agents         1 ['payments-ops']
  unassessed agents        3 ['support-triage', 'hr-screening', 'marketing-copy-bot']
  open findings            26 {'high': 7, 'critical': 9, 'medium': 10}
  controls with evidence   35 of 43 effective (40 assessed, 2 with no evidence yet)
  live obligations         2
  upcoming (24mo)          5

Control statuses are computed from telemetry over the stated window. Framework mappings are DRAFT and have not
been reviewed by compliance counsel — see the coverage and gap declarations per framework.`}</Output>

      <h2 id="signoff">Sign off a mapping</h2>
      <p>
        A draft mapping becomes reviewed when the person accountable for the claim signs it
        off. Give them the review packet first: one section per control, with what it is
        meant to achieve, what evidence it produces, and every clause it is mapped to.
      </p>
      <Code>{`agentfox report review-packet --framework soc2 --out soc2-review.md`}</Code>
      <Output>{`wrote soc2-review.md  64 mapping(s), 64 draft`}</Output>
      <Output title="soc2-review.md (top)">{`# Compliance mapping review packet — soc2

64 mapping(s), 64 awaiting review.

For each row: does this control, as implemented, support the clause claimed? Approve with
\`agentfox report signoff <control> --framework soc2 --reviewer "<your name>"\`, optionally \`--reference\` for a single clause.
…`}</Output>
      <p>
        The reviewer records their decision with{" "}
        <Link href={cli("report signoff")}>
          <code>agentfox report signoff</code>
        </Link>
        , using the control key from the packet&apos;s section heading.{" "}
        <code>--reference</code> signs off one clause only; without it, every clause for that
        control in that framework is marked reviewed.
      </p>
      <Code>{`agentfox report signoff <control> --framework soc2 --reviewer "Dana Reyes, external auditor" --reference CC7.2`}</Code>
      <p>
        It prints how many mappings it marked reviewed. Afterwards{" "}
        <code>agentfox report frameworks</code> shows SOC 2 with <code>1</code> under
        reviewed, the packet says <code>63 awaiting review</code>, and the next evidence
        package carries that row with the <code>REVIEWED</code> chip and the reviewer&apos;s
        name.
      </p>
      <Callout kind="note">
        Signing off from the CLI updates the mapping but does not add an entry to the audit
        chain. Signing off in the web app (Compliance → Frameworks → Review mappings) does
        record a <code>compliance.mapping_reviewed</code> entry with the signed-in user as
        the actor. If you need the attestation in the chain, use the web app.
      </Callout>
      <InTheApp path="/app/compliance?tab=frameworks">Compliance → Frameworks → Review mappings</InTheApp>

      <h2>Retention and legal hold</h2>
      <p>
        What exists today is a record, not an enforcement mechanism. Be precise about this
        with an auditor.
      </p>
      <ul>
        <li>
          <strong>Retention policies</strong> are rows (data class, days to keep, fields to
          redact) that you read with <code>GET /api/retention</code> or on the Retention tab.
          A seeded environment has four. There is no command, route or screen to add or change
          one, and nothing in AgentFox deletes or redacts data when a period runs out.
        </li>
        <li>
          <strong>Legal holds</strong> are placed with <code>POST /api/legal-holds</code>{" "}
          (role <code>compliance</code>) or from the Retention tab. Placing one writes a{" "}
          <code>legal_hold.placed</code> entry to the audit chain. There is no route to
          release a hold, and because nothing purges data on a schedule, a hold does not
          change what is kept.
        </li>
        <li>
          <strong>Redaction at capture</strong> is on by default (
          <code>AGENTFOX_REDACT_AT_CAPTURE</code>). In the words of every package&apos;s
          README: content in traces is redacted at capture, and detector findings record
          entity type, location and a masked sample rather than the sensitive value.
        </li>
      </ul>
      <p>
        Placing a hold over the API, with a token issued by{" "}
        <Link href={cli("admin auth issue")}>
          <code>agentfox admin auth issue</code>
        </Link>{" "}
        for a user with the compliance role:
      </p>
      <Code>{`curl -s -X POST http://127.0.0.1:8080/api/legal-holds \\
  -H "Authorization: Bearer $AGENTFOX_TOKEN" \\
  -H 'Content-Type: application/json' \\
  -d '{"scope":{"agents":["payments-ops"],"from":"2026-09-01"},"reason":"Preservation request, matter 2026-114"}'`}</Code>
      <Output>{`{"id":"hld_01m469qszk6fk4h23b","placed_at":"2026-10-05T15:08:26.483424+00:00"}`}</Output>
      <Code>{`curl -s http://127.0.0.1:8080/api/retention -H "Authorization: Bearer $AGENTFOX_TOKEN" | python3 -m json.tool`}</Code>
      <Output>{`{
    "policies": [
        {
            "data_class": "prompt_content",
            "retain_days": 90,
            "redact_fields": [
                "content",
                "messages"
            ]
        },
…
        {
            "data_class": "audit",
            "retain_days": 2555,
            "redact_fields": []
        },
…
    ],
    "legal_holds": [
        {
            "id": "hld_01m469qszk6fk4h23b",
            "scope": {
                "agents": [
                    "payments-ops"
                ],
                "from": "2026-09-01"
            },
            "reason": "Preservation request, matter 2026-114",
            "placed_by": "dana@example.com",
            "placed_at": "2026-10-05T15:08:26.483424+00:00",
            "released_at": null
        }
    ]
}`}</Output>
      <InTheApp path="/app/compliance?tab=retention">Compliance → Retention &amp; legal hold</InTheApp>

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong>The package is nearly empty.</strong> Nothing was recorded in the period.
          Check <code>--since-days</code>, or <code>--from</code> and <code>--to</code>{" "}
          (<code>YYYY-MM-DD</code> or ISO-8601; a bare <code>--to</code> date includes the
          whole day), and that your agents run through AgentFox.
        </li>
        <li>
          <strong>
            <code>--agent</code> did not narrow everything.
          </strong>{" "}
          It narrows the agent inventory, traces and summary. The audit chain is exported in
          full for the period (it has to be, to verify), and decisions and findings can
          include other agents&apos; rows. In the example above, the package for{" "}
          <code>payments-ops</code> has 25 decisions, all of the decisions recorded in that
          period, for every agent. Tell the recipient.
        </li>
        <li>
          <strong>
            <code>verify_chain.py</code> says <code>checkpoint_signature</code>.
          </strong>{" "}
          The key you passed is not the one the checkpoints were signed with, or the key was
          changed after they were written.
        </li>
        <li>
          <strong>
            <code>report status --framework</code> shows <code>0 controls</code>.
          </strong>{" "}
          The framework key is misspelled. Use one of the keys listed above.
        </li>
        <li>
          <strong>A control reads <code>not_implemented</code>.</strong> Its capability was
          never exercised in the window. Run <code>agentfox report status --verbose</code>{" "}
          to see which records it looked for.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>
          A package shows what was recorded. It cannot show what never passed through
          AgentFox, and it does not establish that the controls in scope were the right
          ones.
        </li>
        <li>
          <code>effective</code> means a control&apos;s evidence was present and its rule
          passed over this scope and window, not that the control is effective in general.
        </li>
        <li>
          Framework mappings, the threat coverage table and the obligation calendar are
          drafts until signed off. They are a starting point for a reviewer, not a legal
          conclusion.
        </li>
        <li>
          Without the signing key, an auditor can detect accidental damage and partial edits,
          but not a complete, consistent rewrite of the package.
        </li>
      </ul>
      <p>
        More on what AgentFox cannot see: <Link href="/docs/limits">Limits</Link>.
      </p>

      <NextSteps
        items={[
          { href: "/docs/guides/observability", label: "Traces and integrations", why: "send the same decisions and findings to your SIEM, Prometheus or a webhook." },
          { href: "/docs/app/compliance", label: "Compliance in the web app", why: "controls, frameworks, evidence and the board snapshot on screen." },
          { href: "/docs/guides/approvals", label: "Approvals and the kill switch", why: "the human sign-offs that appear in approvals.json." },
          { href: "/docs/reference/cli#cmd-report", label: "report in the CLI reference", why: "every subcommand and option." },
        ]}
      />
    </article>
  );
}
