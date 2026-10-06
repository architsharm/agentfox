import type { Metadata } from "next";
import Link from "next/link";
import { Callout, Code, InTheApp, NextSteps, Output, Step, Steps, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Retrieval and answers",
  description:
    "Filter retrieved documents to what the person asking may see, tier your sources, and make the agent abstain when a question is outside what it knows.",
  path: "/docs/guides/rag",
});

const CLI = "/docs/reference/cli#cmd-";

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Guide</p>
      <h1>Retrieval and answers</h1>
      <p className="docs-lede">
        Filter what retrieval returns down to what the person asking may see, tell AgentFox
        which sources it can trust, and make the agent say it does not know instead of
        guessing.
      </p>

      <h2>When to use this</h2>
      <p>
        Use it when an agent answers people from documents or records it reaches with its own
        service identity. That identity can usually read far more than any one caller is
        entitled to, so every permission check passes and the answer still contains something
        the caller should not see. The same agent will also answer from a stale wiki page as
        confidently as from the system of record, and will invent a number for a question its
        data does not cover.
      </p>
      <p>Three controls address those three failures. You can adopt them one at a time:</p>
      <TaskTable
        rows={[
          { task: "Register the human the agent acts for", run: "agentfox declare principal", href: `${CLI}declare-principal` },
          { task: "Say which groups may read which resources", run: "agentfox permit user", href: `${CLI}permit-user` },
          { task: "See how much the agent reaches beyond its callers", run: "agentfox report entitlement", href: `${CLI}report-entitlement` },
          { task: "Tier a source and give it a freshness SLA", run: "agentfox declare source", href: `${CLI}declare-source` },
          { task: "Tier many sources from a file", run: "agentfox declare import-sources", href: `${CLI}declare-import-sources` },
          { task: "Declare what an agent may answer from", run: "agentfox declare boundary", href: `${CLI}declare-boundary` },
          { task: "Ask whether a question would be refused", run: "agentfox test boundary", href: `${CLI}test-boundary` },
        ]}
      />
      <p>
        The examples below were run in order against one fresh state directory. The agent is{" "}
        <code>support-triage</code>; it answers from a support knowledge base, and its index
        also happens to contain finance and HR documents.
      </p>

      <h2>Who may see what</h2>
      <p>
        Entitlement is decided per request, for the person asking, not for the agent. You
        register that person as a <em>principal</em>, grant groups (or single subjects) access
        to resource patterns, and pass retrieved chunks through a filter before the model sees
        them. Anything without a matching grant is withheld: the native engine is
        default-deny.
      </p>

      <Steps>
        <Step title="Register the people the agent acts for">
          <p>
            The subject is whatever stable identifier your identity provider gives you, such as
            an OIDC <code>sub</code> or an employee id. Groups are what grants refer to.
          </p>
          <Code>{`agentfox declare principal ana@example.com --groups support --display "Ana Ruiz"
agentfox declare principal raj@example.com --groups finance,hr`}</Code>
          <Output>{`✓ principal ana@example.com
  groups: support
✓ principal raj@example.com
  groups: finance,hr`}</Output>
          <p>
            <code>--clearances</code> lists the restricted classes a person may see (below).
            Running the command again for the same subject updates it.
          </p>
        </Step>

        <Step title="Grant resource patterns">
          <p>
            A resource is matched against each chunk&apos;s <code>source</code> (or its{" "}
            <code>id</code> when there is no source). Patterns are shell-style globs. A grant
            is for a group unless you pass <code>--kind subject</code>.
          </p>
          <Code>{`agentfox permit user "kb/support/*" support
agentfox permit user "finance/*" finance
agentfox permit user "finance/board/*" finance --classes mnpi
agentfox permit user "hr/*" hr --purposes payroll`}</Code>
          <Output>{`✓ support → kb/support/*
✓ finance → finance/*
✓ finance → finance/board/*
  carries mnpi — needs a matching clearance
✓ hr → hr/*`}</Output>
          <ul>
            <li>
              <code>--classes</code> marks the resources as a restricted class. The restricted
              classes are <code>mnpi</code>, <code>legal_hold</code>, <code>blackout</code>,{" "}
              <code>insider</code> and <code>pii_sensitive</code>. A grant alone never discloses
              them; the principal also needs that class in <code>--clearances</code>. The class
              applies to every grant pattern that matches, so the broader{" "}
              <code>finance/*</code> grant does not open up board minutes.
            </li>
            <li>
              <code>--purposes</code> limits a resource to the purposes you list. A request
              that states a different purpose is refused. A request that states no purpose is
              not checked for it.
            </li>
          </ul>
        </Step>

        <Step title="Filter retrieval before the model sees it">
          <p>
            <code>POST /api/entitlement/filter</code> takes the subject, the candidate chunks
            and, optionally, the purpose, agent and trace id. It returns the chunks this person
            may see and records what it withheld. Call it between retrieval and generation:
            once the answer is written, the only option left is to refuse to send it.
          </p>
          <Code title="ana.json" lang="json">{`{
  "subject": "ana@example.com",
  "agent": "support-triage",
  "chunks": [
    {"source": "kb/support/password-reset.md", "text": "To reset a password, open Settings > Security."},
    {"source": "finance/board/q3-minutes.md", "text": "The board approved the acquisition of Northwind."},
    {"source": "hr/salaries.csv", "text": "employee,band,salary"}
  ]
}`}</Code>
          <Code>{`curl -s -X POST http://127.0.0.1:8080/api/entitlement/filter \\
  -H "Authorization: Bearer $AGENTFOX_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d @ana.json`}</Code>
          <Output>{`{
    "chunks": [
        {
            "source": "kb/support/password-reset.md",
            "text": "To reset a password, open Settings > Security."
        }
    ],
    "principal": "ana@example.com",
    "candidates": 3,
    "visible": 1,
    "withheld": 2,
    "reasons": {
        "not_entitled": 2
    },
    "over_permission": 0.6667,
    "withheld_sources": [
        "finance/board/q3-minutes.md",
        "hr/salaries.csv"
    ]
}`}</Output>
          <p>
            The same three chunks for Raj, who is in <code>finance</code> and <code>hr</code>{" "}
            but has no <code>mnpi</code> clearance, with <code>&quot;purpose&quot;: &quot;support&quot;</code>{" "}
            added to the body:
          </p>
          <Output>{`{
    "chunks": [],
    "principal": "raj@example.com",
    "candidates": 3,
    "visible": 0,
    "withheld": 3,
    "reasons": {
        "not_entitled": 1,
        "restricted:mnpi": 1,
        "purpose_limitation": 1
    },
    "over_permission": 1.0,
    …
}`}</Output>
          <p>
            Use the <code>chunks</code> field as your model context. The other fields say why
            each chunk was removed. The token is an operator token; see{" "}
            <Link href="/docs/guides/gateway">the gateway guide</Link> for how to start the
            server and mint one.
          </p>
        </Step>

        <Step title="Check the answer as well (Python)">
          <p>
            If you use <Link href="/docs/guides/python-auto"><code>agentfox.auto()</code></Link>,
            pass the caller and the retrieved chunks on the model call. These keyword arguments
            are removed before the provider sees them. After the model answers, AgentFox runs the
            same filter and raises a critical finding if the answer quotes a chunk the caller
            was not entitled to. When the decision enforces, the answer is also withheld. This
            is the safety net for a retriever that skipped the pre-filter.
          </p>
          <Code lang="python" title="answer.py">{`import agentfox
import mock  # an offline stand-in for the OpenAI client

agentfox.auto(agent="support-triage", mode="observe")
client = mock.client()  # in your code: OpenAI()

chunks = [
    {"source": "kb/support/password-reset.md", "text": "To reset a password, open Settings > Security."},
    {"source": "finance/board/q3-minutes.md", "text": "The board approved the acquisition of Northwind."},
]
reply = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Any news about Northwind?"}],
    agentfox_principal="ana@example.com",  # who is asking
    agentfox_chunks=chunks,                # what retrieval returned
)
print(reply.choices[0].message.content)`}</Code>
          <Code>{`agentfox findings`}</Code>
          <Output>{` id         severity  type                    what
 …yq8rmjpd  critical  entitlement_disclosure  the answer contains content from
                                              'finance/board/q3-minutes.md', which
                                              'ana@example.com' is not entitled to see

  1 open finding(s).`}</Output>
          <Callout kind="warning" title="In observe mode this check records; in enforce mode it withholds">
            The answer above was returned to the caller, because the example runs in{" "}
            <code>mode=&quot;observe&quot;</code>. With <code>mode=&quot;enforce&quot;</code>, or
            when the gateway decision enforces, the same answer is refused under the rule{" "}
            <code>entitlement.disclosure</code> (in Python, <code>agentfox.Blocked</code> is
            raised). The check matches an answer that quotes a withheld chunk; a paraphrase gets
            past it, so filter before generation with <code>/api/entitlement/filter</code> as well.
          </Callout>
        </Step>

        <Step title="Read the over-permission number">
          <Code>{`agentfox report entitlement`}</Code>
          <Output>{`3 request(s) checked · 3 withheld something · 2 principal(s) · 75.0% of retrieved content was withheld
  not_entitled          4
  restricted:mnpi       1
  purpose_limitation    1

  That share is what the agent could reach and the caller could not. It is the oversharing number,
not an error rate.`}</Output>
          <p>
            This is the share of what retrieval returned that the caller could not see. Only
            requests where something was withheld are recorded, so a filter call that removed
            nothing does not appear in the count or the ratio. <code>--days</code> sets the
            window (default 7). With no decisions recorded yet, the command says so and points
            you at <code>agentfox declare principal</code>.
          </p>
        </Step>
      </Steps>

      <InTheApp path="/app/entitlement">Access control: principals, grants and withheld content</InTheApp>

      <h2>Which sources to trust</h2>
      <p>
        A source tier says how far an answer from that source can be trusted. Tiers, from most
        to least authoritative: <code>system_of_record</code>, <code>approved</code>,{" "}
        <code>unverified</code>, <code>external</code>. A source you have not registered is
        treated as <code>unverified</code>, never as approved. The key must be exactly what
        your retriever emits as a chunk&apos;s <code>source</code>. Keys are matched exactly,
        not as globs.
      </p>

      <Steps>
        <Step title="Register sources one at a time">
          <Code>{`agentfox declare source kb/support/password-reset.md --tier system_of_record \\
  --owner support-ops --domain support --sla-hours 720 --updated now
agentfox declare source wiki/notes/reset-tips.md --tier unverified --domain support`}</Code>
          <Output>{`✓ kb/support/password-reset.md → system_of_record
✓ wiki/notes/reset-tips.md → unverified`}</Output>
          <p>
            <code>--sla-hours</code> is a freshness SLA. <code>--updated</code> records when the
            source last changed, as an ISO date or <code>now</code>. A source with an SLA and no
            update time counts as stale on purpose, because its age is unknown.{" "}
            <code>--domain</code> names the corpus it belongs to; an agent answering from
            another domain&apos;s source is flagged.
          </p>
        </Step>

        <Step title="Register many from a JSON file">
          <p>
            The file is either a list of objects or an object with a <code>sources</code> list.
            Each entry takes <code>key</code> (required), <code>title</code>,{" "}
            <code>tier</code> (default <code>unverified</code>), <code>owner</code>,{" "}
            <code>domain</code>, <code>freshness_sla_hours</code> and{" "}
            <code>deprecated</code>.
          </p>
          <Code title="sources.json" lang="json">{`{
  "sources": [
    {"key": "kb/support/billing-faq.md", "title": "Billing FAQ", "tier": "approved", "owner": "support-ops", "domain": "support"},
    {"key": "https://status.example.com", "tier": "external", "domain": "support"},
    {"key": "kb/support/legacy-billing.md", "tier": "approved", "domain": "support", "deprecated": true},
    {"key": "finance/pricing.md", "tier": "approved", "owner": "finance", "domain": "finance", "freshness_sla_hours": 24}
  ]
}`}</Code>
          <Code>{`agentfox declare import-sources sources.json
agentfox declare list sources`}</Code>
          <Output>{`✓ registered 4 source(s) from sources.json
  tier                source                          owner          domain     state
  external            https://status.example.com      —              support    ok
  unverified          wiki/notes/reset-tips.md        —              support    ok
  approved            finance/pricing.md              finance        finance    age unknown
  approved            kb/support/billing-faq.md       support-ops    support    ok
  approved            kb/support/legacy-billing.md    —              support    deprecated
  system_of_record    kb/support/password-reset.md    support-ops    support    ok`}</Output>
          <p>
            The import does not read an update time, so <code>finance/pricing.md</code> reads{" "}
            <code>age unknown</code>. Set it with a single <code>declare source</code>:
          </p>
          <Code>{`agentfox declare source finance/pricing.md --tier approved --owner finance \\
  --domain finance --sla-hours 24 --updated now`}</Code>
          <Output>{`✓ finance/pricing.md → approved`}</Output>
          <p>
            <code>GET /api/sources/health</code> lists what is stale, deprecated or unowned.
            Before that fix it returned:
          </p>
          <Output>{`{
    "registered": 6,
    "stale": [
        {
            "source": "finance/pricing.md",
            "reason": "source has a freshness SLA but no recorded update time"
        }
    ],
    "deprecated": [
        "kb/support/legacy-billing.md"
    ],
    "unowned": [
        "wiki/notes/reset-tips.md",
        "https://status.example.com",
        "kb/support/legacy-billing.md"
    ],
    "healthy": 4
}`}</Output>
        </Step>

        <Step title="Dry-run an answer against its sources">
          <p>
            <code>POST /api/sources/assess</code> takes an answer, the chunks it was built from,
            and optionally the agent&apos;s domain. It changes nothing. It reports the weakest
            tier used, deprecated, stale or off-domain sources, and citations to documents that
            were not retrieved.
          </p>
          <Code title="assess.json" lang="json">{`{
  "answer": "Open Settings > Security to reset it [kb/support/legacy-billing.md]. Billing moved to a new provider in 2024 [kb/support/billing-v2.md].",
  "chunks": [
    {"source": "kb/support/legacy-billing.md", "text": "Open Settings > Security to reset it."},
    {"source": "wiki/notes/reset-tips.md", "text": "Try clearing cookies first."}
  ],
  "agent_domain": "support"
}`}</Code>
          <Code>{`curl -s -X POST http://127.0.0.1:8080/api/sources/assess \\
  -H "Authorization: Bearer $AGENTFOX_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d @assess.json`}</Code>
          <Output>{`{
    "weakest_tier": "unverified",
    "breaches": [
        {
            "kind": "deprecated_source",
            "source": "kb/support/legacy-billing.md",
            "reason": "'kb/support/legacy-billing.md' is marked deprecated and should not be answered from"
        }
    ],
    "fabricated_citations": [
        {
            "citation": "kb/support/billing-v2.md",
            "kind": "unknown_source",
            "reason": "'kb/support/billing-v2.md' was not among the retrieved sources"
        }
    ],
    "conflicts": [],
    "uncited_claims": [],
    "sources": [ … ],
    "clean": false
}`}</Output>
          <p>
            At run time the same checks run on the model&apos;s answer when{" "}
            <code>agentfox.auto()</code> is given <code>agentfox_chunks</code> together with{" "}
            <code>agentfox_principal</code>. An answer grounded in the deprecated page above
            produced:
          </p>
          <Output>{` …qdjh27k7  high      source_authority        'kb/support/legacy-billing.md' is marked deprecated
                                              and should not be answered from`}</Output>
        </Step>

        <Step title="Check a document before it enters the index">
          <p>
            <code>POST /api/sources/context-check</code> is a dry run of the ingestion and
            chunking quality gate. Send <code>text</code> (one extracted document),{" "}
            <code>chunks</code> (a list of strings as they will be indexed), or both.
          </p>
          <Code title="chunks.json" lang="json">{`{
  "source_key": "kb/support/password-reset.md",
  "chunks": [
    "To reset a password, open Settings > Security and choose Reset.",
    "and the account stays locked for thirty",
    "minutes after five failed attempts."
  ]
}`}</Code>
          <Code>{`curl -s -X POST http://127.0.0.1:8080/api/sources/context-check \\
  -H "Authorization: Bearer $AGENTFOX_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d @chunks.json`}</Code>
          <Output>{`{
    "chunks": {
        "count": 3,
        "findings": [
            {
                "code": "orphan-chunk",
                "detail": "chunk 1 is 39 characters \\u2014 too short to answer anything on its own, and it will still be retrieved",
                "severity": "warn",
                …
            },
            {
                "code": "split-sentence-start",
                "detail": "chunk 1 opens mid-sentence; the subject of the clause is in the previous chunk and will not be retrieved with it",
                "severity": "degraded",
                …
                "verdict": "abstain"
            },
            …
        ]
    }
}`}</Output>
          <p>
            It reports; it does not repair. Re-chunking or dropping the document is your call.
          </p>
        </Step>
      </Steps>

      <InTheApp path="/app/sources">Verified sources: tiers, owners and freshness</InTheApp>

      <h2>When to say &quot;I don&apos;t know&quot;</h2>
      <p>
        A knowledge boundary says which systems an agent answers from, how far back its data
        goes, which kinds of question it answers, and which topics are out of scope. The check
        runs on the question, before the model is called, so an unanswerable question never
        produces an invented answer.
      </p>

      <Steps>
        <Step title="Declare the boundary">
          <p>
            Question types are <code>fact</code>, <code>aggregate</code>,{" "}
            <code>prediction</code>, <code>opinion</code> and <code>procedure</code>.{" "}
            <code>--answerable</code> defaults to <code>fact,aggregate,procedure</code>. A
            boundary starts in observe mode.
          </p>
          <Code>{`agentfox declare boundary support-triage --systems help-center,tickets \\
  --coverage-months 12 --answerable fact,procedure \\
  --out-of-scope "legal advice,medical advice"`}</Code>
          <Output>{`✓ boundary declared for support-triage
  answerable: fact, procedure
  coverage:   last 12 months
  observe mode — refusals are recorded, not applied. Re-run with --mode enforce when the dry runs
look right.`}</Output>
        </Step>

        <Step title="Try real questions against it">
          <p>
            <code>agentfox test boundary</code> runs nothing and changes nothing. It shows the
            refusal a person would get. Replay real questions through it before you enforce: a
            false positive here is a customer being told no.
          </p>
          <Code>{`agentfox test boundary support-triage "How do I reset my password?"
agentfox test boundary support-triage "Will ticket volume go up next quarter?"
agentfox test boundary support-triage "What caused the outage in 2019?"
agentfox test boundary support-triage "Can you give me legal advice about my contract?"
agentfox test boundary support-triage "How many tickets were closed last week?"`}</Code>
          <Output>{`answerable  (procedure)
╭─ would abstain — unknowable ─────────────────────────────────────────────────────────────────────╮
│ That asks for a projection rather than a recorded fact. I can only report what is in             │
│ help-center, tickets, so I don't have an answer for it.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
  recorded only (observe mode)
╭─ would abstain — out_of_coverage ────────────────────────────────────────────────────────────────╮
│ I hold data from 2025-10-10 onwards, and that question is about 2019. Data not available for     │
│ that period.                                                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
  recorded only (observe mode)
╭─ would abstain — out_of_domain ──────────────────────────────────────────────────────────────────╮
│ That topic is outside what this agent is set up to cover (legal advice).                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
  recorded only (observe mode)
╭─ would abstain — unsupported_question_type ──────────────────────────────────────────────────────╮
│ That's an aggregate question, and this agent is set up to answer fact or procedure questions     │
│ from help-center, tickets.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
  recorded only (observe mode)`}</Output>
          <p>
            The title of each panel is the abstention kind. The fifth kind,{" "}
            <code>out_of_scope_entity</code>, only applies when the caller supplies the
            identifiers it holds (<code>known_entities</code> on the HTTP check, below) and the
            question names an identifier-shaped token, such as <code>TKT-991</code>, that is
            not among them. Without that list, entity scope is never guessed.
          </p>
        </Step>

        <Step title="Enforce, and handle the abstention">
          <Code>{`agentfox declare boundary support-triage --systems help-center,tickets \\
  --coverage-months 12 --answerable fact,procedure \\
  --out-of-scope "legal advice,medical advice" --mode enforce`}</Code>
          <p>
            Re-declare with every option, not only <code>--mode</code>: the command writes the
            whole boundary. In <code>agentfox.auto()</code>&apos;s default{" "}
            <code>&quot;policy&quot;</code> mode, an enforced abstention raises{" "}
            <code>agentfox.Blocked</code> before the provider is called. The verdict is{" "}
            <code>abstain</code>, and <code>result.content</code> is the sentence to show the
            user.
          </p>
          <Code lang="python" title="ask.py">{`import agentfox
import mock

agentfox.auto(agent="support-triage", quiet=True)  # mode="policy", the default
client = mock.client()

try:
    client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Will ticket volume go up next quarter?"}],
    )
except agentfox.Blocked as exc:
    print("verdict:", exc.result.verdict)
    print("rule:   ", exc.result.rules_fired[0]["rule_id"])
    print("say:    ", exc.result.content)`}</Code>
          <Output>{`verdict: abstain
rule:    answerability.unknowable
say:     That asks for a projection rather than a recorded fact. I can only report what is in help-center, tickets, so I don't have an answer for it.`}</Output>
          <p>
            Over HTTP, <code>POST /api/answerability/check</code> gives the same verdict as
            JSON, and <code>GET /api/answerability/report</code> puts abstentions next to
            over-refusals:
          </p>
          <Code>{`curl -s -X POST http://127.0.0.1:8080/api/answerability/check \\
  -H "Authorization: Bearer $AGENTFOX_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"agent": "support-triage", "question": "What caused the outage in 2019?"}'`}</Code>
          <Output>{`{
    "agent": "support-triage",
    "question_type": "fact",
    "boundary_declared": true,
    "answerable": false,
    "abstention_kind": "out_of_coverage",
    "reasons": [
        {
            "check": "temporal",
            "in_scope": false,
            "asked_about": "2019",
            "earliest": "2025-10-10",
            "reason": "asked about 2019; coverage starts 2025-10-10"
        }
    ],
    "response": "I hold data from 2025-10-10 onwards, and that question is about 2019. Data not available for that period.",
    "mode": "enforce",
    "should_abstain": true
}`}</Output>
          <p>With the identifiers the caller holds:</p>
          <Code>{`curl -s -X POST http://127.0.0.1:8080/api/answerability/check \\
  -H "Authorization: Bearer $AGENTFOX_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"agent": "support-triage", "question": "What is the status of ticket TKT-991?", "known_entities": ["TKT-100", "TKT-200"]}'`}</Code>
          <Output>{`{
    …
    "answerable": false,
    "abstention_kind": "out_of_scope_entity",
    …
    "response": "I can't find TKT-991 in help-center, tickets. Rather than guess, I'd rather tell you it isn't there.",
    "mode": "enforce",
    "should_abstain": true
}`}</Output>
        </Step>
      </Steps>

      <InTheApp path="/app/agents">Agents → an agent → Knowledge boundary</InTheApp>

      <h2>Where these show up</h2>
      <p>
        AgentFox checks content per surface (see{" "}
        <Link href="/docs/reference/detectors">Detectors and findings</Link>). Retrieved
        content enters on the <code>retrieved</code> surface and is tainted, so text from a
        document cannot authorise a tool call however it is phrased. The controls on this page
        attach at these points:
      </p>
      <ul>
        <li>
          <strong>Before generation (input):</strong> the knowledge boundary. An abstention is
          the <code>abstain</code> verdict, with rule id <code>answerability.&lt;kind&gt;</code>.
        </li>
        <li>
          <strong>Between retrieval and generation:</strong> the entitlement filter, which you
          call. Withheld chunks are recorded for <code>report entitlement</code>.
        </li>
        <li>
          <strong>After generation (output):</strong> <code>entitlement_disclosure</code>{" "}
          (critical) when the answer quotes a withheld chunk; <code>source_authority</code> for
          deprecated, stale or off-domain sources; <code>boundary_breach</code> when an answer
          goes outside the declared boundary anyway.
        </li>
      </ul>

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong><code>unknown principal &apos;zoe@example.com&apos;. Register it first</code>.</strong>{" "}
          The HTTP filter refuses a subject it does not know. Register every caller with{" "}
          <code>declare principal</code>, or from your sign-in path with{" "}
          <code>PUT /api/entitlement/principals</code>.
        </li>
        <li>
          <strong>
            <code>unknown user &apos;admin@example.com&apos;. Send X-Nometria-User or a nom_api_ bearer token.</code>
          </strong>{" "}
          The request had no operator token. See{" "}
          <Link href="/docs/guides/gateway">the gateway guide</Link>.
        </li>
        <li>
          <strong>No finding from <code>auto()</code>.</strong> An{" "}
          <code>agentfox_principal</code> that is not registered is skipped silently, with
          nothing recorded. <code>agentfox_chunks</code> without{" "}
          <code>agentfox_principal</code> runs neither the entitlement check nor the source
          checks.
        </li>
        <li>
          <strong>A source reads <code>age unknown</code> or stale right after import.</strong>{" "}
          It has an SLA and no update time. Run <code>declare source … --updated now</code>{" "}
          when it changes.
        </li>
        <li>
          <strong><code>tier must be one of: system_of_record, approved, unverified, external</code>.</strong>{" "}
          No other tier names exist.
        </li>
        <li>
          <strong><code>unknown question type(s): [&apos;rumour&apos;]</code>.</strong> Use{" "}
          <code>fact</code>, <code>aggregate</code>, <code>prediction</code>,{" "}
          <code>opinion</code> or <code>procedure</code>.
        </li>
        <li>
          <strong><code>unknown agent &apos;research-bot&apos;</code>.</strong> The boundary
          commands need a registered agent. An agent is registered the first time it runs
          under <code>agentfox.auto(agent=…)</code>.
        </li>
        <li>
          <strong>A question you expected to be refused is answerable.</strong> Question
          typing is lexical: <code>&quot;Which plan is better for me?&quot;</code> was read as{" "}
          <code>fact</code>, not <code>opinion</code>. It is precise when it fires and misses
          many questions. Test with your own traffic, and see{" "}
          <Link href="/docs/benchmarks">Benchmarks</Link>.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>
          <strong>You register principals yourself.</strong> There is no Okta, Entra or other
          IdP integration. Principals and their groups are whatever you send.
        </li>
        <li>
          <strong>Only the native engine works.</strong> The OpenFGA adapter is a declared seam,
          not an implementation; configured, it raises instead of filtering. Grants live in
          AgentFox.
        </li>
        <li>
          <strong>No catalog ingestion.</strong> Sources are not read from DataHub,
          OpenMetadata or Unity Catalog. You tier them with the commands above.
        </li>
        <li>
          <strong>Context integrity is partial.</strong> The ingestion and chunk checks report
          problems. They do not repair chunk boundaries or re-extract a corrupt document.
        </li>
        <li>
          <strong>The output-side entitlement check matches quotes, not paraphrases.</strong> In
          enforce mode it withholds an answer that quotes a withheld chunk; an answer that
          restates it in other words is not caught. The pre-filter is what prevents the
          disclosure.
        </li>
        <li>
          Current status for each area is in <Link href="/docs/limits">Limits</Link>.
        </li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/guides/gateway", label: "Any language: the gateway", why: "Start the server these HTTP calls go to, and mint a token." },
          { href: "/docs/guides/langgraph", label: "LangGraph", why: "Guard a retrieval node and a model node in a graph." },
          { href: "/docs/guides/business-rules", label: "Business rules", why: "Turn a written policy into thresholds and approvals." },
          { href: "/docs/app/access-and-sources", label: "Access control and sources in the app", why: "The same principals, grants and tiers, in the web app." },
          { href: "/docs/reference/api", label: "HTTP API reference", why: "Every entitlement, sources and answerability route." },
        ]}
      />
    </article>
  );
}
