import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import { api, safeApi, ApiError, apiErrorProps } from "@/lib/product/api";
import { ApiDown, Panel, ts } from "@/components/ui";
import { PolicyEditor } from "@/components/product/PolicyEditor";
import { Header, ModePill } from "@/components/kit";
import { Act } from "@/components/kit/Act";
import { PackMode } from "@/components/product/policies/PackMode";
import { CanaryPanel } from "@/components/product/CanaryPanel";
import { LibraryPage, findLibrary } from "@/components/product/policies/Libraries";
import { observeScope } from "@/lib/product/observeScope";
import { notFound } from "next/navigation";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata("Policy");

export const dynamic = "force-dynamic";

const EXAMPLE_RULE = `  - id: injection.direct
    description: Block high-confidence prompt injection or jailbreak in user input.
    when:
      surface: [input]
      detection: {entity_prefix: INJECTION, min_score: 0.85}
    effect: block
    severity: high
    reason: "Prompt-injection or jailbreak attempt detected in user input."
    controls: [NOM-RTG-01]`;

function starterTemplate(key: string, name: string, description: string, scopeAgent?: string): string {
  return `# ${name || key} — starts empty; here's a real rule to build from.
key: ${key}
name: ${name || key}
description: ${description || ""}
version: 1
mode: observe
default_effect: allow
fail_mode: open
scope:
  agents: ["${scopeAgent || "*"}"]

rules:
${EXAMPLE_RULE}
`;
}

/** A scan-proposed policy already has a saved body — just with `rules: []` — so
 * the blank-body starter template above never triggers for it. This fills the
 * SAME gap for that case: swap the empty rules line (yaml.safe_dump's flow-style
 * rendering of an empty list) for one real example rule, keeping everything else
 * (key, name, description) exactly as scanned. */
function withExampleRuleIfEmpty(body: string): string {
  return /^rules:\s*\[\s*\]\s*$/m.test(body)
    ? body.replace(/^rules:\s*\[\s*\]\s*$/m, `rules:\n${EXAMPLE_RULE}`)
    : body;
}

/**
 * A rule's `when` clause, as a sentence fragment rather than an object.
 *
 * The compiled form carries every condition the engine understands and sets all
 * but a few to null — twenty-odd keys per rule, of which two or three are
 * populated. Printed raw it is unreadable; dropped entirely it takes with it the
 * only answer to "why would this fire?". So: the populated ones, in the order a
 * person would ask them, and nothing else.
 */
function RuleWhen({ when }: { when: any }) {
  if (!when) return <span className="muted">every request</span>;

  const bits: string[] = [];
  const surfaces = when.surface;
  if (surfaces?.length) bits.push(`on ${surfaces.map((x: string) => SURFACE_WORDS[x] || x.replace(/_/g, " ")).join(", ")}`);
  if (when.detection) {
    const d = when.detection;
    // `CUSTOM.IMP_…` is the id of a text pattern an import saved: say what it is.
    const raw = String(d.entity || d.entity_prefix || "");
    const what = raw.toUpperCase().startsWith("CUSTOM.") ? "its text pattern" : raw;
    const parts: string[] = [];
    if (what) parts.push(`${what} detected`);
    if (d.min_score != null) parts.push(`score \u2265 ${d.min_score}`);
    if (d.min_count != null && d.min_count > 1) parts.push(`at least ${d.min_count}`);
    if (parts.length) bits.push(parts.join(", "));
  }
  if (when.tool) bits.push(`tool ${when.tool}`);
  if (when.tool_impact) bits.push(`tool impact ${[].concat(when.tool_impact).join(" or ")}`);
  if (when.taint_exceeds) bits.push(`arguments more tainted than ${when.taint_exceeds}`);
  if (when.capability) bits.push(`capability ${when.capability}`);
  if (when.action_operation) bits.push(`operation ${[].concat(when.action_operation).join(" or ")}`);
  if (when.action_reversible === false) bits.push("irreversible action");
  if (when.blast_radius_at_least != null) bits.push(`blast radius \u2265 ${when.blast_radius_at_least}`);
  if (when.intent_declared === false) bits.push("no declared intent");
  if (when.budget_exceeded) bits.push("budget exceeded");
  if (when.loop_detected) bits.push("loop detected");
  if (when.detector_degraded) bits.push("a detector is degraded");
  if (when.risk_tier) bits.push(`risk tier ${[].concat(when.risk_tier).join(" or ")}`);
  if (when.agent) bits.push(`agent ${[].concat(when.agent).join(", ")}`);
  if (when.environment) bits.push(`in ${[].concat(when.environment).join(", ")}`);
  if (when.expr) bits.push("a custom expression matches");

  if (!bits.length) return <span className="muted">every request</span>;
  return <>{bits.join(" \u00b7 ")}</>;
}

const SURFACE_WORDS: Record<string, string> = {
  input: "user messages",
  output: "agent replies",
  tool_args: "tool calls",
  tool_result: "tool results",
  retrieved: "retrieved documents",
};

/** A route segment as the library id it may name: `payments%2Frefunds` is `payments/refunds`. */
function decodeKey(key: string): string {
  try {
    return decodeURIComponent(key);
  } catch {
    return key;
  }
}

export default async function PolicyDetail({
  params,
  searchParams,
}: {
  params: Promise<{ key: string }>;
  searchParams: Promise<{ level?: string; scope_id?: string; name?: string }>;
}) {
  const { key } = await params;
  const { level: qsLevel, scope_id: qsScopeId, name: qsName } = await searchParams;
  let policy: any, bindings: any, canaryData: any;
  let isNew = false;
  try {
    [policy, bindings, canaryData] = await Promise.all([
      api(`/api/policies/${key}`),
      safeApi("/api/policies", { policies: [] }),
      safeApi(`/api/policies/${key}/canary`, { canary: null }),
    ]);
  } catch (e: any) {
    // A key with no policy behind it yet is how a scope-specific policy gets
    // created — the editor below starts from a blank starter template, pre-scoped
    // to whatever level/scope_id got us here (e.g. an agent detail page's
    // "customize for this agent" link), rather than a 404 dead end.
    //
    // Only for a key that is meant to be created, though: one scoped by the URL, or an
    // agent's own layer (agent.<slug>, the protection wizard's link). Any other key
    // with no policy behind it is a library not applied yet, shown as the library,
    // or nothing: not an empty editor offering to save a stray policy by that name.
    const creating = Boolean(qsLevel || qsScopeId || qsName) || /^agent\.[^.]+$/.test(key);
    if (e instanceof ApiError && e.status === 404 && !creating) {
      const { project, agents } = await observeScope();
      const found = await findLibrary(decodeKey(key), agents);
      if (!found) notFound();
      return (
        <>
          <Header back={{ href: "/app/policies?tab=libraries", label: "Libraries" }} title={found.title} />
          <LibraryPage found={found} project={project} agents={agents} />
        </>
      );
    }
    if (e instanceof ApiError && e.status === 404) {
      isNew = true;
      policy = { key, name: qsName || key, description: "", versions: [] };
      bindings = { policies: [] };
      canaryData = { canary: null };
    } else {
      return (
        <>
          <h1>Policy</h1>
          <ApiDown {...apiErrorProps(e)} />
        </>
      );
    }
  }

  const binding = bindings.policies?.find((p: any) => p.key === key);
  const savedBody = policy.body?.trim() || "";
  const initialLevel = qsLevel || policy.level;
  const initialScopeId = qsScopeId || policy.scope_id;
  const scopeAgent = initialLevel === "agent" && initialScopeId && initialScopeId !== "*" ? initialScopeId : undefined;
  const body = savedBody
    ? withExampleRuleIfEmpty(savedBody)
    : starterTemplate(key, policy.name, policy.description, scopeAgent);
  const isTemplate = body !== savedBody;
  const rules: any[] = policy.compiled?.rules || [];

  return (
    <>
      <Header back={{ href: "/app/policies", label: "Policies" }} title={policy.name || key} />
      <p className="sub">
        {isNew
          ? `New policy — nothing saved yet. Save below to create it${initialScopeId && initialScopeId !== "*" ? ` scoped to ${initialScopeId}` : ""}.`
          : policy.description || "No description."}
      </p>

      <div className="row small" style={{ gap: 16, marginBottom: 16, alignItems: "center", flexWrap: "wrap" }}>
        <ModePill mode={binding?.mode} />
        {binding?.bound_version != null && (
          <span>
            <span className="muted">live </span>
            <span className="mono">v{binding.bound_version}</span>
            {binding.latest_version != null && binding.latest_version !== binding.bound_version && (
              <span className="muted"> (v{binding.latest_version} saved, not live)</span>
            )}
          </span>
        )}
        <span>
          <span className="muted">rules </span>
          <span className="mono">{binding?.rules ?? 0}</span>
        </span>
        {/* Watching → blocking goes through the same replay-then-confirm gate as a library. */}
        {binding?.mode && policy.live_body && (
          <PackMode packKey={key} mode={binding.mode} body={policy.live_body} version={policy.bound_version ?? null} />
        )}
        {binding?.mode && key.startsWith("imported-") && (
          <Act
            url={`/api/policies/${encodeURIComponent(key)}`}
            method="DELETE"
            className="k-btn-danger"
            done="Removed"
            confirm={`Remove ${policy.name || key}? Its rules stop applying now; its versions stay in the history.`}
          >
            Remove
          </Act>
        )}
      </div>

      {/* This page is reached from "Review & edit" on a policy with, in this
          case, twelve rules — and it never showed them. It opened on a
          create-a-rule form (five dropdowns and a checkbox row) under the
          heading "Rules — authored as YAML, enforced at runtime", which is
          engineering's voice describing a form written in plain language, above
          a YAML blob. Someone arriving to review a policy met a blank form.

          The rules come first now, as what they are. The editor is still one
          click away and unchanged. */}
      {rules.length > 0 && (
        <>
          <h2>Rules in this policy</h2>
          <p className="sub">
            Each one is checked on every request this policy covers. When several
            match, the strongest effect wins: a block beats an approval, which beats
            an allow.
          </p>
          <div className="panel scroll-x">
            <table>
              <thead>
                <tr>
                  <th>rule</th>
                  <th>when it fires</th>
                  <th>effect</th>
                  <th>severity</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r: any) => (
                  <tr key={r.id}>
                    <td className="small wrap" style={{ maxWidth: 300 }}>
                      {r.description || r.id}
                      <div className="mono small muted">{r.id}</div>
                    </td>
                    <td className="small wrap" style={{ maxWidth: 340 }}>
                      <RuleWhen when={r.when} />
                    </td>
                    <td>
                      <span className={`tag ${r.effect === "block" ? "bad" : r.effect === "allow" ? "" : "warn"}`}>
                        {r.effect}
                      </span>
                    </td>
                    <td className="small muted">{r.severity || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <details className="rt-more" style={{ marginTop: 22 }}>
        <summary>
          {rules.length > 0 ? "Edit these rules" : "Add the first rule"} — builder or YAML
        </summary>
        <p className="sub">
          Validation runs the exact same check the engine applies at enforcement
          time, so an error here is an error there. Saving creates a new immutable
          version; nothing currently in force changes, whatever <code>mode</code> the
          file says, until you simulate it and promote it. A new policy is saved live
          in observe, which records and blocks nothing.
        </p>
        <PolicyEditor
          policyKey={key}
          initialBody={body}
          canEnforce={true}
          isTemplate={isTemplate}
          initialLevel={initialLevel}
          initialScopeId={initialScopeId}
          initialCompose={policy.compose}
          latestVersion={policy.latest_version ?? null}
          liveVersion={policy.bound_version ?? null}
          liveMode={policy.mode ?? null}
        />
      </details>

      {policy.versions?.length > 0 && (
        <>
          <h2>Version history</h2>
          <div className="panel scroll-x">
            <table>
              <thead>
                <tr><th className="num">version</th><th>author</th><th>notes</th><th className="num">rules</th><th>when</th></tr>
              </thead>
              <tbody>
                {[...policy.versions].reverse().map((v: any) => (
                  <tr key={v.id}>
                    <td className="num small">{v.version}</td>
                    <td className="small muted">{v.author}</td>
                    <td className="small wrap muted" style={{ maxWidth: 320 }}>{v.notes || "—"}</td>
                    <td className="num small">{v.rules}</td>
                    <td className="small muted">{ts(v.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {policy.versions?.length > 1 && (
        <>
          <h2>Canary rollout</h2>
          <CanaryPanel
            policyKey={key}
            initialCanary={canaryData?.canary ?? null}
            latestVersion={policy.versions[policy.versions.length - 1]?.version ?? 1}
          />
        </>
      )}

      {/* The table at the top of the page is this data, read. This is the same
          data unread — every field the engine checks, most of them null because
          most rules use a few. A debugging view, so it stays one control deep
          rather than being its own section with its own heading and preamble. */}
      {rules.length > 0 && (
        <details className="rt-more" style={{ marginTop: 22 }}>
          <summary>The compiled rule objects, in full ({rules.length})</summary>
          <pre className="rule-json">{JSON.stringify(rules, null, 2)}</pre>
        </details>
      )}
    </>
  );
}
