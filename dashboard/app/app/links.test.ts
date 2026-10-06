/**
 * Every link inside the signed-in app lands somewhere, and every call it makes to
 * the gateway names a route the gateway has.
 *
 * Both of these broke without anything noticing. The notification bell's "N more on
 * Overview", the top-bar counts, the Board snapshot and the glossary all linked to
 * "/" after Overview moved to "/app", so a signed-in user clicking "Overview" was
 * dropped on the marketing page. The judgment-posture panel linked to a settings
 * page that was never built, and the agents strip linked to a Policies tab that does
 * not exist. A route renamed or pruned on the gateway side breaks the same way: the
 * page renders "the control plane returned an error" and nothing at build time says
 * why. So both are checked against the filesystem and the generated API reference,
 * not against another hand-kept list.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = process.cwd();
const APP = join(ROOT, "app");

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name.startsWith(".next")) continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

/** Route patterns for every page under app/, as regexes over a pathname. */
function pageRoutes(): RegExp[] {
  return walk(APP)
    .filter((f) => f.endsWith(`${sep}page.tsx`))
    .map((f) => {
      const segs = relative(APP, f)
        .split(sep)
        .slice(0, -1)
        .filter((s) => !(s.startsWith("(") && s.endsWith(")")));
      const body = segs
        .map((s) =>
          s.startsWith("[[...") ? "(?:/.*)?" : s.startsWith("[...") ? "/.+" : s.startsWith("[") ? "/[^/]+" : `/${s}`,
        )
        .join("");
      return new RegExp(`^${body || "/"}$`);
    });
}

/** Source files that render the signed-in app. Tests and the public site excluded. */
function appSources(): string[] {
  return [...walk(join(APP, "app")), ...walk(join(ROOT, "components"))].filter(
    (f) => /\.tsx?$/.test(f) && !f.includes(".test.") && !f.includes(`${sep}marketing${sep}`),
  );
}

/** `href="/app/…"`, `href: "/app/…"` and `href={\`/app/…\`}` literals. */
function appHrefs(src: string): string[] {
  const out: string[] = [];
  for (const m of src.matchAll(/href(?:=\{?|:\s*)["'`](\/[^"'`]*)["'`]/g)) out.push(m[1]);
  return out;
}

describe("in-app links", () => {
  const routes = pageRoutes();
  const files = appSources();

  it("every /app link resolves to a page that exists", () => {
    const broken: string[] = [];
    for (const f of files) {
      for (const href of appHrefs(readFileSync(f, "utf8"))) {
        if (!href.startsWith("/app")) continue;
        const path = href.replace(/\$\{[^}]+\}/g, "x").split(/[?#]/)[0];
        if (!routes.some((r) => r.test(path))) broken.push(`${relative(ROOT, f)}: ${href}`);
      }
    }
    expect(broken).toEqual([]);
  });

  it("every /app/policies?tab= link names a tab the page has", () => {
    const page = readFileSync(join(APP, "app", "policies", "page.tsx"), "utf8");
    const tabs = new Set([...page.matchAll(/\{ key: "([a-z_-]+)", label:/g)].map((m) => m[1]));
    expect(tabs.size).toBeGreaterThan(0);
    const broken: string[] = [];
    for (const f of files) {
      for (const href of appHrefs(readFileSync(f, "utf8"))) {
        const m = href.match(/^\/app\/policies\?(?:.*&)?tab=([a-z_-]+)/);
        if (m && !tabs.has(m[1])) broken.push(`${relative(ROOT, f)}: ${href}`);
      }
    }
    expect(broken).toEqual([]);
  });

  it("nothing in the app sends a signed-in user to the marketing page by accident", () => {
    // "/" is the public landing page. The one link that should go there says so.
    const offenders: string[] = [];
    for (const f of files) {
      const src = readFileSync(f, "utf8");
      for (const m of src.matchAll(/href(?:=\{?|:\s*)["'`]\/["'`]/g)) {
        const after = src.slice(m.index!, m.index! + 160);
        if (/Public site/.test(after)) continue;
        offenders.push(`${relative(ROOT, f)}: ${after.split("\n")[0]}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("gateway calls", () => {
  const spec = JSON.parse(readFileSync(join(ROOT, "lib", "reference", "api.json"), "utf8")) as {
    routes: { method: string; path: string }[];
  };
  // Compared a segment at a time: a `{param}` on the gateway side and a `${hole}`
  // on ours each stand for any one segment, so `/api/agents/${slug}/${action}`
  // is known as long as some route has that shape.
  const HOLE = "\u0000";
  const gateway = spec.routes.map((r) => r.path.split("/").map((s) => (/^\{.+\}$/.test(s) ? HOLE : s)));
  const known = (path: string) => {
    const ours = path.split("/");
    return gateway.some(
      (g) => g.length === ours.length && g.every((s, i) => s === HOLE || ours[i] === HOLE || s === ours[i]),
    );
  };

  /** First-argument paths of api()/safeApi()/post() and of the lib/proxy helpers. */
  function gatewayCalls(src: string): string[] {
    const out: string[] = [];
    const re =
      /\b(?:api|safeApi|post|proxy[A-Za-z]*)(?:<[^>()]*>)?\(\s*(?:req,\s*)?(?:"[A-Z]+",\s*)?[`"](\/(?:api|v1)\/[^`"]*)[`"]/g;
    for (const m of src.matchAll(re)) out.push(m[1]);
    for (const m of src.matchAll(/fetch\(\s*`\$\{(?:API_BASE|BASE)\}(\/[^`]*)`/g)) out.push(m[1]);
    return out;
  }

  it("every path the dashboard calls exists in the generated gateway reference", () => {
    const files = [
      ...walk(join(APP, "app")),
      ...walk(join(APP, "api")),
      ...walk(join(ROOT, "components")),
      ...walk(join(ROOT, "lib")),
    ].filter((f) => /\.tsx?$/.test(f) && !f.includes(".test."));
    let seen = 0;
    const missing: string[] = [];
    for (const f of files) {
      for (const raw of gatewayCalls(readFileSync(f, "utf8"))) {
        seen += 1;
        // A hole after a "/" is a path segment; one glued to the end of a segment
        // (`/handoffs${agentQs}`) is a query string being appended.
        const path = raw
          .split("?")[0]
          .replace(/([^/])\$\{[^}]*\}$/, "$1")
          .replace(/\$\{[^}]+\}/g, HOLE)
          .replace(/(.)\/$/, "$1");
        if (!known(path)) missing.push(`${relative(ROOT, f)}: ${raw}`);
      }
    }
    // Guard against the scan silently matching nothing after a refactor.
    expect(seen).toBeGreaterThan(60);
    expect(missing).toEqual([]);
  });

  it("the threat coverage page calls a route the gateway serves", () => {
    const src = readFileSync(join(APP, "app", "coverage", "page.tsx"), "utf8");
    const calls = gatewayCalls(src);
    expect(calls.length).toBeGreaterThan(0);
    for (const raw of calls) expect(known(raw.split("?")[0])).toBe(true);
  });
});

describe("command names", () => {
  const cli = JSON.parse(readFileSync(join(ROOT, "lib", "reference", "cli.json"), "utf8")) as {
    renamed: Record<string, string>;
    root: { commands: { name: string }[] };
  };
  const current = new Set(cli.root.commands.map((c) => c.name));
  // Old top-level names the CLI no longer has, from the generated reference itself.
  const retired = Object.keys(cli.renamed).filter((name) => !current.has(name));

  it("the app never tells anyone to run a command that was renamed", () => {
    const re = new RegExp(`\\bagentfox (${retired.map((n) => n.replace(/-/g, "\\-")).join("|")})\\b`, "g");
    const offenders: string[] = [];
    // The whole site, docs included: a docs page is where a renamed command is
    // most likely to be copied from.
    for (const f of [...walk(APP), ...walk(join(ROOT, "components"))]) {
      if (!/\.tsx?$/.test(f) || f.includes(".test.")) continue;
      const src = readFileSync(f, "utf8");
      for (const m of src.matchAll(re)) {
        const line = src.slice(0, m.index).split("\n").length;
        offenders.push(`${relative(ROOT, f)}:${line}: ${m[0]} → ${cli.renamed[m[1]]}`);
      }
    }
    expect(retired.length).toBeGreaterThan(5);
    expect(offenders).toEqual([]);
  });
});
