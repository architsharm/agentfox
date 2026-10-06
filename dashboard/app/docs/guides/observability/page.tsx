import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, Step, Steps, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Traces and integrations",
  description:
    "Send OpenTelemetry spans in, join AgentFox decisions to Langfuse and LangSmith runs, scrape Prometheus metrics, export to a SIEM, and receive signed finding webhooks.",
  path: "/docs/guides/observability",
});

const cli = (path: string) => `/docs/reference/cli#cmd-${path.replace(/\s+/g, "-")}`;
const api = (anchor: string) => `/docs/reference/api#${anchor}`;

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Guide</p>
      <h1>Traces and integrations</h1>
      <p className="docs-lede">
        Connect AgentFox to the tools your team already watches: OpenTelemetry spans in,
        Langfuse and LangSmith runs joined to governance decisions, Prometheus metrics,
        SIEM export, and signed webhooks when a finding is raised or resolved.
      </p>

      <h2>When to use this</h2>
      <ul>
        <li>
          Your agents already emit OpenTelemetry and you want them in the agent registry,
          with shadow-agent detection, without changing code.
        </li>
        <li>
          An engineer is looking at a Langfuse or LangSmith trace and needs to know which
          AgentFox decision shaped it.
        </li>
        <li>
          Your on-call alerts come from Prometheus, your security team works in a SIEM, or a
          ticketing system should open an issue when AgentFox finds something.
        </li>
      </ul>

      <TaskTable
        rows={[
          { task: "Send OpenTelemetry spans in", run: "POST /v1/traces (OTLP protobuf or JSON)", href: "#otlp" },
          { task: "Find the decision behind a Langfuse or LangSmith run", run: "GET /api/traces/resolve", href: "#correlation" },
          { task: "Scrape metrics", run: "GET /metrics", href: "#metrics" },
          { task: "Export decisions and findings to a SIEM", run: "GET /api/export/siem", href: "#siem" },
          { task: "Be told about findings", run: "AGENTFOX_WEBHOOK_URL", href: "#webhooks" },
        ]}
      />

      <h2>Before you start: the server and its authentication</h2>
      <p>
        Every integration here goes through the control-plane API. Start it with{" "}
        <Link href={cli("serve api")}>
          <code>agentfox serve api</code>
        </Link>{" "}
        (default <code>127.0.0.1:8080</code>; see{" "}
        <Link href="/docs/guides/gateway">the gateway guide</Link> and{" "}
        <Link href="/docs/self-host">Self-hosting</Link>), then check how it authenticates:
      </p>
      <Code>{`agentfox serve api --port 8080
agentfox admin auth status`}</Code>
      <Output>{`╭─ Authentication: development mode ───────────────────────────────────────────────╮
│ The X-Nometria-User header is accepted.                                          │
│                                                                                  │
│ environment = development · auth_mode = auto                                     │
│ Anyone who can reach this port is any user they name. That is fine for local     │
│ work and unacceptable anywhere else.                                             │
│                                                                                  │
│ Set NOMETRIA_ENVIRONMENT=production, or NOMETRIA_AUTH_MODE=token, to require API │
│ tokens.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────╯`}</Output>
      <p>
        In development mode, an <code>X-Nometria-User: you@example.com</code> header is
        enough for <code>/api/*</code>. With <code>AGENTFOX_AUTH_MODE=token</code> (or{" "}
        <code>AGENTFOX_ENVIRONMENT=production</code>) that header is refused and you send{" "}
        <code>Authorization: Bearer nom_api_…</code>, a token from{" "}
        <Link href={cli("admin auth issue")}>
          <code>agentfox admin auth issue</code>
        </Link>
        . The examples below show the header that worked in each case.
      </p>
      <Callout kind="warning" title="Credentials for metrics and trace ingest">
        <code>GET /metrics</code> is unauthenticated on purpose: it carries counts, not
        content. Keep it on a private network or behind a proxy only Prometheus can reach.{" "}
        <code>POST /v1/traces</code> needs a credential outside development: an agent key
        (<code>Authorization: Bearer nom_agt_…</code>) or an operator token whose role may
        write to the registry (<code>Bearer nom_api_…</code>). Without one it returns 401.
        In development it accepts spans without a credential, as before.
      </Callout>

      <h2 id="otlp">Send OpenTelemetry spans in</h2>
      <p>
        <code>POST /v1/traces</code> accepts an OTLP/HTTP trace export in{" "}
        <strong>JSON</strong>. Each span is stored on an AgentFox trace, and every agent it
        names goes into the registry. An agent nobody registered raises a{" "}
        <code>shadow_agent</code> finding.
      </p>
      <Code lang="json" title="span.json">{`{
  "resourceSpans": [{
    "resource": {"attributes": [
      {"key": "service.name", "value": {"stringValue": "research-bot"}},
      {"key": "deployment.environment", "value": {"stringValue": "staging"}}
    ]},
    "scopeSpans": [{
      "scope": {"name": "opentelemetry.instrumentation.langchain"},
      "spans": [
        {
          "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
          "spanId": "00f067aa0ba902b7",
          "name": "chat gpt-4o-mini",
          "startTimeUnixNano": "1791200000000000000",
          "endTimeUnixNano": "1791200000850000000",
          "attributes": [
            {"key": "gen_ai.system", "value": {"stringValue": "openai"}},
            {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o-mini"}}
          ]
        },
        {
          "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
          "spanId": "00f067aa0ba902b8",
          "name": "tool web.fetch",
          "startTimeUnixNano": "1791200000900000000",
          "endTimeUnixNano": "1791200001300000000",
          "attributes": [
            {"key": "gen_ai.tool.name", "value": {"stringValue": "web.fetch"}}
          ]
        }
      ]
    }]
  }]
}`}</Code>
      <Code>{`curl -s -X POST http://127.0.0.1:8080/v1/traces \\
  -H 'Content-Type: application/json' --data @span.json | python3 -m json.tool`}</Code>
      <Output>{`{
    "spans_ingested": 2,
    "traces": [
        "trc_01m469h1q532xt106f"
    ],
    "agents_seen": [
        "research-bot"
    ],
    "frameworks": {
        "research-bot": "langchain"
    },
    "shadow_agents": [
        …
        {
            "slug": "research-bot",
            "environment": "production",
            "first_seen": "2026-10-05T15:04:45.034507",
            "last_seen": "2026-10-05T15:04:45.038338",
            "calls": 1,
            "models": [
                "gpt-4o-mini"
            ],
            "providers": [
                "openai"
            ],
            "framework": "langchain",
            "suggested_registration": {
                …
            }
        }
    ]
}`}</Output>
      <p>How the span is read:</p>
      <ul>
        <li>
          <strong>Agent:</strong> the <code>agentfox.agent</code> attribute, else{" "}
          <code>service.name</code>, else <code>gen_ai.agent.name</code>, else{" "}
          <code>unknown</code>. Resource attributes and span attributes are merged.
        </li>
        <li>
          <strong>Trace:</strong> one AgentFox trace per agent and OTel trace id. The OTel
          trace id becomes its session id; <code>deployment.environment</code>,{" "}
          <code>gen_ai.request.model</code> and <code>gen_ai.system</code> fill in the
          environment, model and provider.
        </li>
        <li>
          <strong>Span kind:</strong> <code>tool</code> if it has{" "}
          <code>gen_ai.tool.name</code> or its name starts with <code>tool</code>;{" "}
          <code>llm</code> for other <code>gen_ai.*</code> spans; <code>retrieval</code> or{" "}
          <code>agent</code> from the span name. Status code 2 marks it an error.
        </li>
        <li>
          <strong>Framework:</strong> detected from attribute and scope names (LangGraph,
          LangChain, LlamaIndex, CrewAI, AutoGen, the Claude Agent SDK, Google ADK, the
          OpenAI Agents SDK, Semantic Kernel).
        </li>
      </ul>
      <InTheApp path="/app/traces">Traces → the trace, with each span and its attributes</InTheApp>

      <p>
        The route accepts both OTLP/HTTP encodings: protobuf (<code>application/x-protobuf</code>,
        what the OpenTelemetry exporters send by default) and JSON (
        <code>application/json</code>), either one gzip-compressed (
        <code>Content-Encoding: gzip</code>). A protobuf request gets the empty protobuf{" "}
        <code>ExportTraceServiceResponse</code> the OTLP spec asks for; a JSON request gets
        the summary above. So the stock exporter works as it is:
      </p>
      <Code lang="python" title="agent.py">{`from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

provider = TracerProvider(resource=Resource.create({"service.name": "research-bot"}))
provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(
            endpoint="http://127.0.0.1:8080/v1/traces",
            compression=Compression.Gzip,  # optional
        )
    )
)
trace.set_tracer_provider(provider)

tracer = trace.get_tracer("research-bot")
with tracer.start_as_current_span("tool db.query") as span:
    span.set_attribute("gen_ai.tool.name", "db.query")
provider.shutdown()`}</Code>
      <p>
        Run with OpenTelemetry SDK 1.44, the span arrives as a <code>tool</code> span named{" "}
        <code>tool db.query</code> on a <code>research-bot</code> trace, with or without gzip.
        An OpenTelemetry Collector&apos;s <code>otlphttp</code> exporter can point at the same
        URL. Decoding protobuf needs the <code>opentelemetry-proto</code> package (part of{" "}
        <code>agentfox[otel]</code>); a server without it answers a protobuf body with{" "}
        <code>415</code> and a message saying so, and JSON still works. With a token-mode
        server, add the <code>Authorization: Bearer</code> header through the exporter&apos;s{" "}
        <code>headers=</code> argument.
      </p>
      <p>
        What ingest does not do: it runs no policy and no detectors over the spans (the trace
        reads <code>verdict: allow</code> because nothing evaluated it), it does not keep the
        parent-child structure between spans, and the trace&apos;s start time is when it
        arrived, not the span&apos;s timestamp. To <em>enforce</em> on calls, route them
        through <Link href="/docs/guides/python-auto">agentfox.auto()</Link> or{" "}
        <Link href="/docs/guides/gateway">the gateway</Link>.
      </p>

      <h2>Sending AgentFox events out as OpenTelemetry</h2>
      <p>
        AgentFox has no exporter that pushes spans or logs to a collector. The OpenTelemetry
        output it has is a pull: <code>GET /api/export/siem?format=otlp</code> returns
        decisions and findings as OTLP/JSON <em>log records</em> (see{" "}
        <a href="#siem">SIEM export</a>). Fetch it on a schedule and forward it yourself.
      </p>

      <h2 id="correlation">Join decisions to Langfuse and LangSmith</h2>
      <p>
        When a model call goes through the AgentFox proxy (<code>/v1/chat/completions</code>{" "}
        or <code>/v1/messages</code>), AgentFox reads the join key off the request headers
        and stores it with its own trace. Nothing has to be installed and nothing leaves your
        network for this part. The headers it reads:
      </p>
      <table>
        <thead>
          <tr>
            <th>System</th>
            <th>Trace id header</th>
            <th>Run id header</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Langfuse</td>
            <td><code>langfuse-trace-id</code>, <code>x-langfuse-trace-id</code>, <code>x-nometria-langfuse-trace</code></td>
            <td><code>langfuse-observation-id</code>, <code>x-langfuse-observation-id</code></td>
          </tr>
          <tr>
            <td>LangSmith</td>
            <td><code>langsmith-trace-id</code>, <code>x-langsmith-trace-id</code>, <code>x-nometria-langsmith-trace</code></td>
            <td><code>langsmith-run-id</code>, <code>x-langsmith-run-id</code></td>
          </tr>
          <tr>
            <td>OpenTelemetry</td>
            <td colSpan={2}>
              <code>traceparent</code> (W3C): the trace id, with the parent span id as the run id
            </td>
          </tr>
        </tbody>
      </table>
      <p>
        When the LangSmith or Langfuse SDK is installed in the same process as an
        in-process AgentFox call, AgentFox also reads the current run from it.
      </p>
      <Steps>
        <Step title="Send a call with the join key">
          <Code>{`curl -s -X POST http://127.0.0.1:8080/v1/chat/completions \\
  -H 'Content-Type: application/json' \\
  -H 'X-Nometria-Agent: support-triage' \\
  -H 'langfuse-trace-id: lf-7d1c2e90' \\
  -H 'langfuse-observation-id: obs-55a1' \\
  -H 'traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01' \\
  -d '{"model":"echo-1","messages":[{"role":"user","content":"Summarise ticket 4182"}]}'`}</Code>
          <p>
            The response carries <code>x-nometria-trace: trc_01m469nhx6q4d17k22</code> and{" "}
            <code>x-nometria-verdict: allow</code>.
          </p>
        </Step>
        <Step title="Resolve their id to the decision">
          <p>
            <Link href={api("GET--api-traces-resolve")}>
              <code>GET /api/traces/resolve</code>
            </Link>{" "}
            takes <code>system</code> (<code>langfuse</code>, <code>langsmith</code> or{" "}
            <code>otel</code>) and <code>external_id</code>, which can be either the trace id
            or the run/observation id.
          </p>
          <Code>{`curl -s "http://127.0.0.1:8080/api/traces/resolve?system=langfuse&external_id=obs-55a1" \\
  -H 'X-Nometria-User: priya@example.com' | python3 -m json.tool`}</Code>
          <Output>{`{
    "matches": [
        {
            "trace_id": "trc_01m469nhx6q4d17k22",
            "agent": "support-triage",
            "verdict": "allow",
            "started_at": "2026-10-05T15:07:12.678900",
            "system": "langfuse",
            "external_trace_id": "lf-7d1c2e90",
            "external_run_id": "obs-55a1",
            "url": "https://cloud.langfuse.com/trace/lf-7d1c2e90",
            "detail": "/api/traces/trc_01m469nhx6q4d17k22"
        }
    ]
}`}</Output>
          <p>
            The same trace resolves from <code>system=otel</code> and the W3C trace id{" "}
            <code>0af7651916cd43dd8448eb211c80319c</code>. An id with no match returns{" "}
            <code>404</code> with{" "}
            <code>{`{"detail":"no governed trace correlates with that id"}`}</code>.{" "}
            <code>GET /api/traces/&#123;trace_id&#125;</code> lists the same links under{" "}
            <code>links</code>.
          </p>
        </Step>
      </Steps>
      <p>
        The <code>url</code> is a deep link built from <code>AGENTFOX_LANGFUSE_HOST</code>{" "}
        (default <code>https://cloud.langfuse.com</code>) or, for LangSmith,{" "}
        <code>AGENTFOX_LANGSMITH_UI_URL</code> and <code>AGENTFOX_LANGSMITH_PROJECT</code>.
        Set them for a self-hosted deployment, or the link points at the cloud service.
      </p>

      <h3>Write the verdict back onto their run (optional)</h3>
      <p>
        AgentFox can tag the external run with its decision, so the verdict shows up where
        the engineer is already looking. This is off by default and needs egress:
      </p>
      <Code>{`export AGENTFOX_ALLOW_EGRESS=true
export AGENTFOX_CORRELATION_PUSH=true
# Langfuse
export AGENTFOX_LANGFUSE_HOST=https://cloud.langfuse.com
export AGENTFOX_LANGFUSE_PUBLIC_KEY=pk-lf-…
export AGENTFOX_LANGFUSE_SECRET_KEY=sk-lf-…
# LangSmith
export AGENTFOX_LANGSMITH_API_KEY=lsv2-…
export AGENTFOX_LANGSMITH_PROJECT=support`}</Code>
      <p>
        Checked against a local stand-in for each service, after a call through the proxy:
      </p>
      <ul>
        <li>
          Langfuse: <code>POST /api/public/traces</code> with basic auth (public key, secret
          key) and the body{" "}
          <code>{`{"id":"lf-91b0aa12","metadata":{"agentfox_trace_id":"trc_01m469pg0nm74k2n2a","agentfox_verdict":"allow","agentfox_effective_verdict":"allow","agentfox_rules":[],"agentfox_agent":"support-triage"},"tags":["agentfox:allow"]}`}</code>
          .
        </li>
        <li>
          LangSmith: <code>PATCH /runs/&lt;run id&gt;</code> (the trace id when no run id was
          sent) with an <code>x-api-key</code> header and the same metadata under{" "}
          <code>extra.metadata</code>, tagged <code>agentfox:allow</code>.
        </li>
      </ul>
      <p>
        The push is best-effort with a 2-second timeout (
        <code>AGENTFOX_CORRELATION_TIMEOUT_SECONDS</code>). A failure is logged at debug level
        and never affects the request. It was not run against the real Langfuse or LangSmith
        services.
      </p>

      <h2 id="metrics">Prometheus metrics</h2>
      <p>
        <Link href={api("GET--metrics")}>
          <code>GET /metrics</code>
        </Link>{" "}
        serves the Prometheus text format. Point a scrape job at it; it needs no token.
      </p>
      <Code>{`curl -s http://127.0.0.1:8080/metrics`}</Code>
      <Output>{`# HELP agentfox_decisions_total Governance decisions by verdict and policy mode.
# TYPE agentfox_decisions_total counter
agentfox_decisions_total{mode="enforce",verdict="allow"} 11
agentfox_decisions_total{mode="observe",verdict="allow"} 4
agentfox_decisions_total{mode="enforce",verdict="block"} 8
agentfox_decisions_total{mode="enforce",verdict="escalate"} 1
agentfox_decisions_total{mode="observe",verdict="escalate"} 1
# HELP agentfox_decisions_by_mode_total Decisions split by whether the policy was enforcing.
# TYPE agentfox_decisions_by_mode_total counter
agentfox_decisions_by_mode_total{mode="observe"} 5
agentfox_decisions_by_mode_total{mode="enforce"} 20
# HELP agentfox_detector_runs_total Detector executions.
# TYPE agentfox_detector_runs_total counter
agentfox_detector_runs_total{detector="injection.heuristic"} 11
agentfox_detector_runs_total{detector="pii.native"} 25
…
# HELP agentfox_detector_duration_ms_max Slowest detector run in the window.
# TYPE agentfox_detector_duration_ms_max gauge
agentfox_detector_duration_ms_max{detector="injection.heuristic"} 0.56825
…
# HELP agentfox_detector_degraded_total Detector runs that timed out, errored or were shed for budget. A control that quietly stops running while reporting effective is the failure mode that makes compliance products worthless.
# TYPE agentfox_detector_degraded_total counter
agentfox_detector_degraded_total 0
# HELP agentfox_open_findings Open findings by type and severity.
# TYPE agentfox_open_findings gauge
agentfox_open_findings{severity="critical",type="containment"} 9
agentfox_open_findings{severity="high",type="containment"} 4
…
agentfox_open_findings{severity="high",type="shadow_agent"} 2
…
# HELP agentfox_missed_escalation_rate Share of qualifying conversations that never handed off. PRD target < 0.05.
# TYPE agentfox_missed_escalation_rate gauge
agentfox_missed_escalation_rate 0
# HELP agentfox_handoffs Hand-offs by status.
# TYPE agentfox_handoffs gauge
agentfox_handoffs{status="pending"} 1
# HELP agentfox_circuit_breaker_state Circuit breaker state per provider: 0 closed, 1 open, 2 half-open.
# TYPE agentfox_circuit_breaker_state gauge
# HELP agentfox_traces_total Governed traces in the window.
# TYPE agentfox_traces_total counter
agentfox_traces_total 6
…`}</Output>
      <Callout kind="warning" title="The _total series are 24-hour counts, not counters">
        Every series is computed from the last 24 hours of records at scrape time. Series
        typed <code>counter</code> (<code>agentfox_decisions_total</code>,{" "}
        <code>agentfox_detector_runs_total</code>, <code>agentfox_traces_total</code>, …) go
        down as old records leave the window, so <code>rate()</code> and{" "}
        <code>increase()</code> will misread them as resets. Alert on the value itself, for
        example <code>agentfox_detector_degraded_total &gt; 0</code> or{" "}
        <code>agentfox_open_findings&#123;severity=&quot;critical&quot;&#125; &gt; 0</code>.
      </Callout>
      <p>
        Worth alerting on: <code>agentfox_detector_degraded_total</code> (a detector timed
        out or errored, and in fail-open mode the request went through unchecked),{" "}
        <code>agentfox_detector_duration_ms_max</code>,{" "}
        <code>agentfox_open_findings</code> by severity,{" "}
        <code>agentfox_missed_escalation_rate</code>, and{" "}
        <code>agentfox_circuit_breaker_state</code> (1 means a provider&apos;s breaker is
        open). Observe-mode decisions are labelled <code>mode=&quot;observe&quot;</code>, so a
        dashboard can keep would-have-blocked apart from blocked.
      </p>

      <h2 id="siem">SIEM export</h2>
      <p>
        <Link href={api("GET--api-export-siem")}>
          <code>GET /api/export/siem</code>
        </Link>{" "}
        returns recent decisions and findings, oldest first, in the format your SIEM reads.
      </p>
      <table>
        <thead>
          <tr>
            <th>Parameter</th>
            <th>Values</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>format</code></td>
            <td><code>jsonl</code> (default), <code>cef</code> (ArcSight), <code>leef</code> (QRadar), <code>otlp</code> (OTLP/JSON log records)</td>
          </tr>
          <tr>
            <td><code>since_days</code></td>
            <td>How far back. Default 7.</td>
          </tr>
          <tr>
            <td><code>limit</code></td>
            <td>Default 1000. Applied to decisions and to findings separately, so you can get up to twice this many lines.</td>
          </tr>
        </tbody>
      </table>
      <p>With token authentication on, issue a token for the export job and use it:</p>
      <Code>{`agentfox admin auth issue aisha@example.com --name siem-export --days 1
curl -s "http://127.0.0.1:8080/api/export/siem?format=cef&since_days=1&limit=1" \\
  -H "Authorization: Bearer $AGENTFOX_TOKEN"`}</Code>
      <p>
        Without a token, the same request gets <code>401</code> and an{" "}
        <code>authentication required</code> message. The response is{" "}
        <code>text/plain</code> in every format. One line of each, from the same recorded
        block of a <code>payments.transfer</code> call:
      </p>
      <Output title="jsonl">{`{"event_type": "agent.decision", "event_id": "dec_01m469a9nrffpr535q", "timestamp": "2026-10-05T15:01:03.800641+00:00", "agent": null, "environment": null, "trace_id": null, "surface": "tool_args", "tool": "payments.transfer", "verdict": "block", "mode": "enforce", "policy_version_id": "pvr_01m4699d5spyd2ryxk", "rules_fired": ["eu.art14.human_oversight", "capability.constraint_violated"], "reasons": ["EU AI Act Art. 14 \\u2014 irreversible action by a high-risk system requires human oversight.", "agent:payments-ops holds a grant for 'payments.transfer', so this is not a missing permission. The grant allows amount below 1000, but this call passed 25000."], "controls": […], "entities": [], "taint": "none", "latency_ms": 5.023792036809027, "severity": 8}`}</Output>
      <Output title="cef">{`CEF:0|AgentFox|ControlPlane|0.1.0|agent.decision|block|8|rt=2026-10-05T15:01:03.800641+00:00 externalId=dec_01m469a9nrffpr535q act=block deviceCustomString1=payments.transfer deviceCustomString1Label=tool deviceCustomString2=eu.art14.human_oversight,capability.constraint_violated deviceCustomString2Label=rules … msg=EU AI Act Art. 14 — irreversible action by a high-risk system requires human oversight.; agent:payments-ops holds a grant for 'payments.transfer', so this is not a missing permission. The grant allows amount below 1000, but this call passed 25000.`}</Output>
      <Output title="leef">{`LEEF:2.0|AgentFox|ControlPlane|0.1.0|agent.decision|	devTime=2026-10-05T15:01:03.800641+00:00	cat=agent.decision	sev=8	tool=payments.transfer	verdict=block	rules=eu.art14.human_oversight,capability.constraint_violated	…`}</Output>
      <Output title="otlp">{`{
  "resourceLogs": [
    {
      "resource": {
        "attributes": [
          {
            "key": "service.name",
            "value": {
              "stringValue": "agentfox"
            }
          },
          …
      "scopeLogs": [
        {
          "scope": {
            "name": "agentfox.governance"
          },
          "logRecords": [
            {
              "timeUnixNano": "1791212464033230080",
              "severityNumber": 16,
              "severityText": "BLOCK",
              "body": {
                "stringValue": "agent.decision"
              },
              "attributes": [
                {
                  "key": "event_id",
                  …`}</Output>
      <p>
        Findings arrive as <code>governance.finding.&lt;type&gt;</code> events with a title,
        severity, status and the finding&apos;s evidence. Severity runs 0–10 in CEF and LEEF
        (block 8, escalate 6, a critical finding 10).
      </p>
      <Callout kind="note">
        A decision that was recorded without a trace (a tool call checked on its own, as in
        the example) exports with <code>agent: null</code>, and CEF then has no{" "}
        <code>duser</code>. The agent is still named in the reasons, but a SIEM rule keyed on
        the agent field will miss it. Decisions made through the proxy carry the agent.
      </Callout>

      <h2 id="webhooks">Webhooks for findings</h2>
      <p>
        AgentFox POSTs a JSON body to one URL whenever a finding at or above a severity is
        committed, and again when one changes status. Configure it with environment
        variables (see <Link href="/docs/reference/config">Configuration</Link>):
      </p>
      <Code>{`export AGENTFOX_ALLOW_EGRESS=true                 # nothing is sent without this
export AGENTFOX_WEBHOOK_URL=https://hooks.example.com/agentfox
export AGENTFOX_WEBHOOK_SECRET=whsec_…              # signs every request
export AGENTFOX_WEBHOOK_MIN_SEVERITY=high           # critical | high | medium | low; default high
export AGENTFOX_WEBHOOK_TIMEOUT_SECONDS=3`}</Code>
      <p>Events:</p>
      <ul>
        <li><code>finding.created</code>: a new finding was committed.</li>
        <li>
          <code>finding.resolved</code>, <code>finding.suppressed</code>,{" "}
          <code>finding.reopened</code>: a finding&apos;s status changed.
        </li>
        <li><code>webhook.test</code>: a test delivery you send yourself (below).</li>
      </ul>
      <p>
        Nothing is sent for work that was rolled back. Delivery runs on a background thread
        behind a 1,000-item queue, so it never slows or fails the code that raised the
        finding. A timeout, connection error or 5xx is retried once after half a second; a
        redirect counts as a failure. Failures are logged at <code>WARNING</code> and
        dropped: there is no persistent retry queue.
      </p>

      <h3>What a delivery looks like</h3>
      <p>The headers and body of a real delivery, as the receiving server saw them:</p>
      <Output>{`Accept-Encoding: identity
Content-Length: 107
Host: 127.0.0.1:18449
Content-Type: application/json
User-Agent: agentfox/0.3.1
X-Nometria-Event: webhook.test
X-Nometria-Delivery: 0b73737568964955a66901e87c890733
X-Nometria-Timestamp: 1791212816
X-Nometria-Signature: sha256=0f5cc905c3c7fea77d4dd355f611cebfa15c66a8f13f679260a92adddd6422b6
Connection: close

{"event":"webhook.test","finding":null,"org_id":"org_default","sent_at":"2026-10-05T15:06:56.357567+00:00"}`}</Output>
      <p>
        For finding events, <code>finding</code> has the same field names as{" "}
        <code>GET /api/findings/&#123;id&#125;</code>: <code>id</code>, <code>type</code>,{" "}
        <code>severity</code>, <code>status</code>, <code>title</code>,{" "}
        <code>subject_type</code>, <code>subject_id</code>, <code>evidence</code>,{" "}
        <code>occurrences</code>, the resolution and suppression fields, and timestamps.
      </p>
      <p>
        The signature is the hex HMAC-SHA256 of the raw body, keyed with your secret. You can
        check one by hand:
      </p>
      <Code>{`printf '%s' '{"event":"webhook.test","finding":null,"org_id":"org_default","sent_at":"2026-10-05T15:06:56.357567+00:00"}' \\
  | openssl dgst -sha256 -hmac whsec_test_7f3a9c`}</Code>
      <Output>{`SHA2-256(stdin)= 0f5cc905c3c7fea77d4dd355f611cebfa15c66a8f13f679260a92adddd6422b6`}</Output>

      <h3>Verify it in your receiver</h3>
      <p>
        Compute the HMAC over the bytes you received, before parsing them; compare in
        constant time; then reject stale and repeated deliveries. Check freshness with{" "}
        <code>sent_at</code> inside the body, which the signature covers. The{" "}
        <code>X-Nometria-Timestamp</code> header is not signed, so anyone replaying a captured
        request can change it. A retry reuses the same body, signature and{" "}
        <code>X-Nometria-Delivery</code> id, so de-duplicate on that id. This receiver uses
        only the standard library:
      </p>
      <Code lang="python" title="receiver.py">{`import datetime as dt
import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = os.environ["AGENTFOX_WEBHOOK_SECRET"]
MAX_AGE = dt.timedelta(minutes=5)
seen_deliveries = set()  # use a shared store (Redis, a table) in production


def verify(raw_body: bytes, headers) -> dict:
    """Return the event if the request is authentic and fresh; raise otherwise."""
    expected = "sha256=" + hmac.new(SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(headers.get("X-Nometria-Signature", ""), expected):
        raise ValueError("bad signature")
    event = json.loads(raw_body)
    # sent_at is inside the signed body; the X-Nometria-Timestamp header is not signed.
    sent_at = dt.datetime.fromisoformat(event["sent_at"])
    if abs(dt.datetime.now(dt.timezone.utc) - sent_at) > MAX_AGE:
        raise ValueError("stale delivery")
    delivery = headers.get("X-Nometria-Delivery")
    if delivery in seen_deliveries:
        raise ValueError("duplicate delivery")
    seen_deliveries.add(delivery)
    return event


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        try:
            event = verify(raw, self.headers)
        except ValueError as exc:
            print("rejected:", exc, flush=True)
            self.send_response(401)
            self.end_headers()
            return
        finding = event.get("finding") or {}
        print("accepted", event["event"], finding.get("severity"), finding.get("title"), flush=True)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", 18448), Handler).serve_forever()`}</Code>

      <h3>Test it end to end</h3>
      <Steps>
        <Step title="Start the receiver">
          <Code>{`AGENTFOX_WEBHOOK_SECRET=whsec_test_7f3a9c python3 receiver.py`}</Code>
        </Step>
        <Step title="Send a test event">
          <p>
            There is no CLI command for this yet; call the function the product uses, with the
            same environment the server runs with:
          </p>
          <Code>{`export AGENTFOX_ALLOW_EGRESS=true
export AGENTFOX_WEBHOOK_URL=http://127.0.0.1:18448/agentfox
export AGENTFOX_WEBHOOK_SECRET=whsec_test_7f3a9c
python -c "from agentfox.core.webhooks import send_test_event; print(send_test_event())"`}</Code>
          <Output>{`(True, 'HTTP 204')`}</Output>
        </Step>
        <Step title="Raise a real finding">
          <p>
            With <code>agentfox serve api</code> running under the same variables, an OTLP span
            from an agent nobody registered raises a high-severity <code>shadow_agent</code>{" "}
            finding (here, <code>span.json</code> from above with the service renamed to{" "}
            <code>triage-experimental</code>). The receiver prints:
          </p>
          <Output>{`accepted webhook.test None None
accepted finding.created high Ungoverned agent 'triage-experimental' observed in production`}</Output>
        </Step>
        <Step title="Check that a wrong secret is refused">
          <p>
            With <code>AGENTFOX_WEBHOOK_SECRET=wrong-secret</code> on the sending side,{" "}
            <code>send_test_event()</code> returns <code>(False, &apos;HTTP 401&apos;)</code>{" "}
            and the receiver prints <code>rejected: bad signature</code>.
          </p>
        </Step>
      </Steps>

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong>No webhook arrives.</strong> Egress is off. <code>send_test_event()</code>{" "}
          says so:{" "}
          <code>
            (False, &apos;egress is disabled (NOMETRIA_ALLOW_EGRESS=false); nothing sent&apos;)
          </code>
          . The message uses the older variable name; <code>AGENTFOX_ALLOW_EGRESS</code> is the
          one to set. Also check the finding&apos;s severity against{" "}
          <code>AGENTFOX_WEBHOOK_MIN_SEVERITY</code>, and the server log for{" "}
          <code>finding webhook: delivery of … failed</code>.
        </li>
        <li>
          <strong>
            <code>/v1/traces</code> returns 415 or 400.
          </strong>{" "}
          415: the body is neither protobuf nor JSON, it uses a compression other than gzip or
          deflate, or it is protobuf and the server lacks <code>opentelemetry-proto</code>{" "}
          (install <code>agentfox[otel]</code>, or set{" "}
          <code>OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/json</code>). 400: the body does not
          decode as what its headers say. The <code>detail</code> field names which.
        </li>
        <li>
          <strong>
            <code>/api/traces/resolve</code> returns 404.
          </strong>{" "}
          The call did not go through the proxy, or did not carry one of the headers in the
          table. OTLP ingest does not create these links.
        </li>
        <li>
          <strong>
            <code>/api/*</code> returns 401.
          </strong>{" "}
          Token mode is on and the request sent <code>X-Nometria-User</code>. Send{" "}
          <code>Authorization: Bearer nom_api_…</code>; check with{" "}
          <code>agentfox admin auth status</code>.
        </li>
        <li>
          <strong>A shadow agent shows the wrong environment.</strong> The trace records{" "}
          <code>deployment.environment</code>, but the registry entry and the finding say{" "}
          <code>production</code> regardless.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>OTLP ingest is JSON only and records spans; it does not enforce anything.</li>
        <li>There is no push exporter for OpenTelemetry or Prometheus; both are pull.</li>
        <li>Metrics cover a rolling 24-hour window and carry no per-agent labels.</li>
        <li>
          Webhooks go to one URL, with one retry and no persistent queue. A receiver that is
          down for longer than that misses events; the SIEM export is the way to backfill.
        </li>
        <li>
          Langfuse and LangSmith correlation needs the call to go through the proxy (or the
          vendor SDK to be in the same process). Pushing the verdict back needs egress and
          their API keys.
        </li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/guides/audit-evidence", label: "Prove it to an auditor", why: "the same records as a verifiable evidence package." },
          { href: "/docs/app/traces", label: "Traces in the web app", why: "one request, every check, and why it was blocked." },
          { href: "/docs/reference/api", label: "HTTP API reference", why: "every route on this page, with parameters." },
          { href: "/docs/reference/config", label: "Configuration", why: "every environment variable." },
        ]}
      />
    </article>
  );
}
