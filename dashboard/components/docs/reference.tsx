/**
 * Renders the reference generated from the code by scripts/gen/docs_reference.py.
 * Nothing here is typed by hand: regenerate the JSON, and the page follows.
 */
import api from "@/lib/generated/reference/api.json";
import cli from "@/lib/generated/reference/cli.json";

type Param = {
  kind: string;
  name: string;
  opts: string[];
  type: string;
  choices: string[];
  required: boolean;
  multiple: boolean;
  default: unknown;
  help: string;
};

export type CliNode = {
  path: string;
  name: string;
  summary: string;
  help: string;
  panel: string | null;
  params: Param[];
  default_subcommand: string | null;
  commands: CliNode[];
};

type Route = {
  method: string;
  path: string;
  section: string;
  audience: string;
  summary: string;
  description: string;
  params: { name: string; in: string; required: boolean; type: string | null }[];
  body: { model: string; fields: { name: string; type: string; required: boolean; description: string }[] } | null;
};

const ROOT = cli.root as CliNode;

export function anchorFor(path: string): string {
  return `cmd-${path.replace(/\s+/g, "-")}`;
}

function usage(node: CliNode): string {
  const args = node.params
    .filter((p) => p.kind === "argument")
    .map((p) => (p.required ? p.name.toUpperCase() : `[${p.name.toUpperCase()}]`));
  const hasOptions = node.params.some((p) => p.kind === "option");
  const sub = node.commands.length ? (node.default_subcommand ? "[COMMAND]" : "COMMAND") : "";
  return ["agentfox", node.path, sub, ...args, hasOptions ? "[OPTIONS]" : ""]
    .filter(Boolean)
    .join(" ");
}

function ParamTable({ params }: { params: Param[] }) {
  if (!params.length) return null;
  return (
    <table className="docs-params">
      <thead>
        <tr>
          <th>Argument / option</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        {params.map((p) => (
          <tr key={p.name}>
            <td>
              <code>{p.kind === "argument" ? p.name.toUpperCase() : p.opts.join(", ")}</code>
              {p.type !== "flag" && p.kind === "option" && (
                <span className="docs-type"> {p.choices.length ? p.choices.join(" | ") : p.type}</span>
              )}
              {p.required && <span className="docs-req"> required</span>}
            </td>
            <td>
              {p.help || <span className="docs-muted">—</span>}
              {p.multiple && <span className="docs-muted"> Repeatable.</span>}
              {p.default !== null && p.default !== undefined && p.default !== "" && (
                <span className="docs-muted"> Default: {String(p.default)}.</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CommandBlock({ node, depth }: { node: CliNode; depth: number }) {
  const Heading = depth <= 1 ? "h2" : "h3";
  return (
    <section className="docs-cmd" id={anchorFor(node.path)}>
      <Heading>
        <code>agentfox {node.path}</code>
      </Heading>
      {node.help && <p className="docs-cmd-help">{node.help}</p>}
      <pre className="docs-usage">
        <code>{usage(node)}</code>
      </pre>
      {node.default_subcommand && (
        <p className="docs-muted">
          Run with no subcommand, it does <code>{`${node.path} ${node.default_subcommand}`}</code>.
        </p>
      )}
      <ParamTable params={node.params} />
      {node.commands.map((child) => (
        <CommandBlock key={child.path} node={child} depth={depth + 1} />
      ))}
    </section>
  );
}

/** One top-level command and everything under it, or the whole CLI. */
export function CliReference({ only }: { only?: string[] }) {
  const nodes = ROOT.commands.filter((n) => !only || only.includes(n.name));
  return (
    <>
      {nodes.map((node) => (
        <CommandBlock key={node.path} node={node} depth={1} />
      ))}
    </>
  );
}

/** The top-level commands grouped by their help panel, linking into the reference. */
export function CliIndex() {
  const panels = new Map<string, CliNode[]>();
  for (const node of ROOT.commands) {
    const key = node.panel ?? "Other";
    panels.set(key, [...(panels.get(key) ?? []), node]);
  }
  return (
    <table className="docs-params">
      <thead>
        <tr>
          <th>Stage</th>
          <th>Command</th>
          <th>What it is for</th>
        </tr>
      </thead>
      <tbody>
        {[...panels.entries()].flatMap(([panel, nodes]) =>
          nodes.map((node, i) => (
            <tr key={node.path}>
              <td>{i === 0 ? panel : ""}</td>
              <td>
                <a href={`#${anchorFor(node.path)}`}>
                  <code>{node.path}</code>
                </a>
              </td>
              <td>{node.summary}</td>
            </tr>
          )),
        )}
      </tbody>
    </table>
  );
}

/** Old command names that still work, and what they are called now. */
const AUDIENCE_LABEL: Record<string, string> = {
  public: "Agent traffic (agent credential)",
  operator: "Operator API (bearer token)",
  "public-unauthenticated": "Public, unauthenticated",
  internal: "Internal",
};

function RouteBlock({ route }: { route: Route }) {
  return (
    <section className="docs-route" id={`${route.method}-${route.path}`.replace(/[^\w-]+/g, "-")}>
      <h3>
        <span className={`docs-method docs-method-${route.method.toLowerCase()}`}>{route.method}</span>{" "}
        <code>{route.path}</code>
      </h3>
      {route.summary && <p>{route.summary}</p>}
      {route.params.filter((p) => p.in !== "header").length > 0 && (
        <p className="docs-muted">
          Parameters:{" "}
          {route.params
            .filter((p) => p.in !== "header")
            .map((p) => `${p.name} (${p.in}${p.required ? ", required" : ""})`)
            .join(", ")}
        </p>
      )}
      {route.body && route.body.fields.length > 0 && (
        <table className="docs-params">
          <thead>
            <tr>
              <th>Body field</th>
              <th>Type</th>
            </tr>
          </thead>
          <tbody>
            {route.body.fields.map((f) => (
              <tr key={f.name}>
                <td>
                  <code>{f.name}</code>
                  {f.required && <span className="docs-req"> required</span>}
                </td>
                <td>
                  {f.type}
                  {f.description && <span className="docs-muted"> — {f.description}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

/** Routes for one audience, grouped by section. */
export function ApiReference({ audience, sections }: { audience?: string; sections?: string[] }) {
  const routes = (api.routes as Route[]).filter(
    (r) => (!audience || r.audience === audience) && (!sections || sections.includes(r.section)),
  );
  const groups = new Map<string, Route[]>();
  for (const r of routes) groups.set(r.section, [...(groups.get(r.section) ?? []), r]);
  return (
    <>
      {[...groups.entries()].map(([section, rs]) => (
        <section key={section} className="docs-route-group">
          <h2 id={`api-${section.replace(/[^\w-]+/g, "-")}`}>
            <code>{section.startsWith("v1") ? `/${section}` : `/api/${section}`}</code>
            <span className="docs-muted"> · {AUDIENCE_LABEL[rs[0].audience] ?? rs[0].audience}</span>
          </h2>
          {rs.map((r) => (
            <RouteBlock key={`${r.method} ${r.path}`} route={r} />
          ))}
        </section>
      ))}
    </>
  );
}

export const API_COUNT = api.count as number;
