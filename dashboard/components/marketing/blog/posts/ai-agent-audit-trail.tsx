import Link from "next/link";

import type { TocItem } from "@/components/marketing/blog/article";
import { Diagram, Figure, InlineCTA, Takeaways, type FaqItem } from "@/components/marketing/blog/blocks";
import { Code, Output } from "@/components/docs/blocks";

export const toc: TocItem[] = [
  { id: "logs-are-not-evidence", label: "A log is not evidence" },
  { id: "what-to-record", label: "What to record per decision" },
  { id: "the-chain", label: "How the hash chain works" },
  { id: "tamper-demo", label: "Watch it catch an edit" },
  { id: "evidence-package", label: "The evidence package" },
  { id: "eu-ai-act", label: "Where the EU AI Act comes in" },
  { id: "limits", label: "What the chain does not prove" },
];

export const faq: FaqItem[] = [
  {
    q: "What should an AI agent audit trail record?",
    a: "Every decision, allowed as well as blocked: which agent, which tool and arguments, the verdict, every rule that fired and why, the policy version in force, where the inputs came from, and who approved anything that needed a person. Recording only the blocks hides the calls that should have been blocked and were not.",
  },
  {
    q: "What is a tamper-evident log?",
    a: "A log where each entry includes a hash of the entry before it, so changing, deleting or reordering any record breaks every hash after it. It does not stop someone editing the log; it makes the edit detectable by anyone who re-runs the verification.",
  },
  {
    q: "Can an auditor verify the AgentFox audit trail without AgentFox?",
    a: "Yes. Every evidence package contains verify_chain.py, a script that uses only the Python standard library. It re-computes every digest from the exported entries and exits 0 if the chain is intact and 1 if it is not.",
  },
  {
    q: "Does the EU AI Act require AI audit logs?",
    a: "Article 12 of the EU AI Act requires high-risk AI systems to allow automatic recording of events over their lifetime, and Article 19 covers keeping those automatically generated logs. AgentFox maps its audit controls to those articles, but the mappings are drafts written by engineers, not reviewed by counsel, and are not legal advice.",
  },
  {
    q: "Is a hash-chained log enough on its own?",
    a: "No. Someone who controls the whole export can recompute every hash. Signed checkpoints held with a key outside the database close that gap, and they only help if the key stays secret. The chain also proves a record was not changed after it was written, not that it was true when written.",
  },
];

export function Body() {
  return (
    <>
      <Takeaways
        items={[
          "A log the vendor or an insider can quietly rewrite is a record of what someone wants you to believe. It is not evidence.",
          "Chain each entry to the hash of the one before, sign checkpoints with a key kept outside the database, and ship a verifier that runs without the product.",
          "Record the allowed calls as well as the blocked ones, with the rule and policy version behind each, or the trail cannot answer the question an auditor actually asks.",
        ]}
      />

      <h2 id="logs-are-not-evidence">A log is not evidence</h2>
      <p>
        When an agent does something it should not have, three people need the same answer:
        the engineer debugging it, the security team deciding whether it was an attack, and,
        increasingly, an auditor or regulator asking whether your controls were on. All three
        will be shown a log, and all three should ask the same question about it:{" "}
        <em>how do I know nobody edited this?</em>
      </p>
      <p>
        For most AI observability tools the honest answer is that you trust the vendor and
        whoever has database access. That is fine for debugging. It is not fine for evidence,
        because the people with the strongest motive to change a record are the ones who can.
        An <strong>AI agent audit trail</strong> worth the name has to be checkable by someone
        who trusts neither.
      </p>

      <h2 id="what-to-record">What to record for each decision</h2>
      <p>
        Every allowed call, not only every blocked one. An audit that only shows refusals cannot
        show the call that should have been refused and was not. For each decision AgentFox
        records:
      </p>
      <ul>
        <li>The agent, the surface (prompt, tool arguments, tool result…) and the tool.</li>
        <li>The verdict, and the effective verdict after the policy&apos;s mode is applied.</li>
        <li>
          Every rule that fired, with its effect, its reason in plain language and the controls
          it maps to.
        </li>
        <li>The policy version in force, so the decision can be replayed against it.</li>
        <li>Where the inputs came from, and the latency of the check.</li>
      </ul>
      <p>Here is one real entry from a demo run: a transfer above the agent&apos;s limit.</p>
      <Code lang="json" title="One audit entry's payload (abridged)" copy={false}>{`{
  "surface": "tool_args",
  "tool": "payments.transfer",
  "verdict": "block",
  "mode": "enforce",
  "policy_version_id": "pvr_01m48yhvhzfh7n96nt",
  "rules_fired": [{
    "rule_id": "capability.constraint_violated",
    "effect": "block",
    "reason": "agent:payments-ops holds a grant for 'payments.transfer', so this is not a missing permission. The grant allows amount below 1000, but this call passed 25000.",
    "controls": ["NOM-IAM-02"]
  }],
  "taint": "none",
  "latency_ms": 4.6
}`}</Code>
      <p>
        Sensitive values are redacted at capture by default: anything under a key like{" "}
        <code>password</code>, <code>token</code> or <code>api_key</code> is written as{" "}
        <code>&lt;redacted&gt;</code> before it reaches the chain, because an audit trail full of
        secrets is a liability of its own.
      </p>

      <h2 id="the-chain">How the hash chain works</h2>
      <Diagram
        label="A hash chain of audit entries with a signed checkpoint"
        caption="Each digest covers the entry's sequence number, time, action, payload digest and the previous entry's digest. Change entry 8 and its digest no longer matches, and nor does anything that points at it."
      >
        <svg className="dg" viewBox="0 0 780 220" xmlns="http://www.w3.org/2000/svg">
          {[
            { x: 10, s: "seq 7", a: "decision.escalate", c: "dg-box" },
            { x: 205, s: "seq 8", a: "decision.block", c: "dg-box-accent" },
            { x: 400, s: "seq 9", a: "decision.allow", c: "dg-box" },
            { x: 595, s: "seq 10", a: "decision.allow", c: "dg-box" },
          ].map((e, i) => (
            <g key={e.s}>
              <rect x={e.x} y="30" width="175" height="110" rx="10" className={e.c} />
              <text x={e.x + 14} y="54" className="dg-strong">{e.s}</text>
              <text x={e.x + 14} y="74" className="dg-mono">{e.a}</text>
              <text x={e.x + 14} y="98" className="dg-small">payload_digest</text>
              <text x={e.x + 14} y="114" className="dg-small">prev_digest ←</text>
              <text x={e.x + 14} y="130" className="dg-small dg-strong">digest</text>
              {i < 3 && <path d={`M${e.x + 175} 85 L${e.x + 195} 85`} className="dg-line-accent" />}
            </g>
          ))}
          <rect x="400" y="160" width="370" height="50" rx="10" className="dg-box-good" />
          <text x="585" y="182" textAnchor="middle" className="dg-strong">Signed checkpoint</text>
          <text x="585" y="200" textAnchor="middle" className="dg-small">HMAC-SHA256 over the head digest, key held outside the DB</text>
          <path d="M680 140 L680 160" className="dg-line" />
        </svg>
      </Diagram>
      <ol>
        <li>
          Each entry&apos;s payload is serialised as canonical JSON (sorted keys, compact
          separators) and hashed with SHA-256.
        </li>
        <li>
          The entry&apos;s own digest is SHA-256 over its sequence number, timestamp, action,
          payload digest and the previous entry&apos;s digest. The first entry points at a
          genesis value of 64 zeros.
        </li>
        <li>
          There is no update or delete path for an audit entry in the code. Appending is the
          only way in.
        </li>
        <li>
          Every 100 entries, and on demand with <code>agentfox admin checkpoint</code>, a
          checkpoint signs the current head digest with HMAC-SHA256 using a key that is not in
          the database.
        </li>
      </ol>
      <p>
        The verifier walks the chain and reports four kinds of break: a gap in sequence numbers
        (a deletion), a payload or entry digest that does not match its contents (an edit), a
        previous-digest that does not match (an insertion or reordering), and a checkpoint whose
        signature or anchored digest is wrong (rewritten history).
      </p>

      <h2 id="tamper-demo">Watch it catch an edit</h2>
      <p>
        We ran the offline demo, which writes fifteen entries, and verified the chain:
      </p>
      <Output title="agentfox report verify">{`chain: 15 entries, head seq 15, 1 checkpoints
CHAIN INTACT — 15 entries verified (seq 1..15)`}</Output>
      <p>
        Then we did what an insider covering for an incident would do: opened the database and
        changed entry 8, the blocked transfer above, so that it read <code>allow</code>.
      </p>
      <Output title="agentfox report verify, after editing one row">{`chain: 15 entries, head seq 15, 1 checkpoints
CHAIN TAMPERED — 2 break(s)
  seq 8 payload_mismatch: payload does not match its recorded digest
  seq 8 digest_mismatch: entry digest does not match its contents`}</Output>
      <p>
        The command exits 1, so the same check can run on a schedule and page someone. The
        walkthrough, including how to try it on your own data, is in{" "}
        <Link href="/docs/guides/audit-evidence">Prove it to an auditor</Link>.
      </p>

      <InlineCTA
        title="An audit trail you can check without us"
        body="Every allowed and blocked call, chained and signed, with a verifier that needs nothing but Python."
        href="/evidence"
        label="Evidence and audit"
        secondary={{ href: "/docs/guides/audit-evidence", label: "Read the guide" }}
      />

      <h2 id="evidence-package">The evidence package</h2>
      <p>
        An auditor should not need an account on your control plane. The evidence package is a
        zip they can take away:
      </p>
      <Code>{`agentfox report evidence --agent payments-ops --from 2026-08-01 --to 2026-08-31 \\
  --requested-by auditor@example.com
unzip <id>.zip && python3 verify_chain.py`}</Code>
      <p>It contains, among other files:</p>
      <ul>
        <li>
          <code>audit_entries.json</code> and <code>audit_checkpoints.json</code>, the chain
          itself.
        </li>
        <li>
          <code>decisions.json</code> and <code>policy_versions.json</code>, so every verdict can
          be traced to the exact policy text that produced it.
        </li>
        <li>Agents, approvals, findings, evaluation runs and control status for the period.</li>
        <li>
          <code>verify_chain.py</code>, which uses only the Python standard library and exits 0
          on <code>CHAIN INTACT</code> and 1 on <code>CHAIN INVALID</code>. Set{" "}
          <code>AGENTFOX_AUDIT_KEY</code> and it checks the checkpoint signatures too.
        </li>
        <li>
          <code>manifest.json</code> with a SHA-256 for every file, and a human-readable
          summary.
        </li>
      </ul>
      <p>
        A package scoped to one agent still ships every audit entry in the period, so the chain
        stays verifiable end to end. Entries about other agents are included with their payload
        withheld: the digests still prove the links, without disclosing what those agents did.
        Exporting a package is itself written to the chain.
      </p>

      <h2 id="eu-ai-act">Where the EU AI Act comes in</h2>
      <p>
        The <strong>EU AI Act</strong> asks high-risk systems to log events automatically over
        their lifetime (Article 12, record-keeping) and to keep those logs (Article 19). Our
        audit controls are mapped to those articles: recording the full execution path, keeping
        the log tamper-evident, and producing exportable, verifiable evidence. The same controls
        are mapped across NIST AI RMF, ISO 42001, SOC 2, the OWASP lists for LLMs and agents, and
        MITRE ATLAS, 43 controls in all, on the <Link href="/frameworks">compliance page</Link>.
      </p>
      <p>
        Two things set this apart from a questionnaire. Control status is computed from what the
        runtime actually decided over a period, not attested. And every mapping ships labelled{" "}
        <strong>DRAFT, UNVERIFIED, NOT LEGAL ADVICE</strong> until someone signs it off, because
        engineers wrote them and counsel has not reviewed them. A sign-off is recorded in the
        chain like everything else.
      </p>
      <Figure
        src="/blog/frameworks-page.png"
        alt="The AgentFox compliance page: frameworks mapped to controls, each mapping marked as a draft."
        caption="Seven frameworks mapped to the same controls. Every mapping is a draft until someone with the authority to sign it off does."
        width={1600}
        height={900}
      />

      <h2 id="limits">What the chain does not prove</h2>
      <ul>
        <li>
          <strong>That a record was true when written.</strong> Only that it has not changed
          since.
        </li>
        <li>
          <strong>Anything, if the key leaks.</strong> Someone who can rewrite the whole export
          can recompute every digest and the manifest. Only the checkpoints resist that, and only
          while the key stays secret and outside the database.
        </li>
        <li>
          <strong>Who handed over the key.</strong> Checkpoints use HMAC, a shared secret, so
          the auditor has to trust whoever gave them the key. There is no public-key signing,
          external timestamping or key rotation yet.
        </li>
        <li>
          <strong>Every field.</strong> The entry digest covers the sequence, time, action and
          payload, not the actor and subject columns.
        </li>
        <li>
          <strong>Withheld payloads.</strong> In a scoped package their links are proven, their
          contents are not checkable.
        </li>
        <li>
          <strong>Production without a real key.</strong> The development default key is
          forgeable. Outside development the gateway refuses to start with it and{" "}
          <code>agentfox doctor</code> reports it.
        </li>
      </ul>
      <p>
        We would rather you read these here than discover them in an audit. The rest of what
        nobody outside this project has checked is on the <Link href="/security">security page</Link>.
      </p>
    </>
  );
}
