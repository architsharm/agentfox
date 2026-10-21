import Link from "next/link";
import { safeApi } from "@/lib/product/api";
import { Empty, href } from "@/components/kit";
import { ruleTitle } from "@/lib/product/vocab";

type Applied = {
  id: string;
  description: string;
  effect: string;
  varies: boolean;
  mode: "enforce" | "observe" | "mixed";
  all: boolean;
  agents: { slug: string; name: string }[];
  libraries: string[];
};

const DOES: Record<string, string> = { block: "Blocks", escalate: "Asks a person", redact: "Hides", mask: "Hides", tokenize: "Hides", allow: "Watches" };

/** "Blocks", or "Blocks · watching only" while its library only records. */
function does(r: Applied): { text: string; tone: string } {
  const text = DOES[r.effect] ?? r.effect;
  if (r.effect === "allow") return { text, tone: "watch" };
  if (r.mode === "observe") return { text: `${text} · watching only`, tone: "watch" };
  if (r.mode === "mixed") return { text: `${text} · on some, watching on others`, tone: "watch" };
  return { text, tone: "on" };
}

function where(r: Applied): string {
  if (r.all) return "Every agent here";
  const names = r.agents.map((a) => a.name);
  return names.length <= 2 ? names.join(", ") : `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
}

/**
 * Every rule in force right now: what it does, on which agents, from which library.
 * Filter by scope or by one agent; click a rule to change it.
 */
export async function AppliedRules({
  scope,
  agent,
  project,
  projectAgents,
}: {
  scope?: string;
  agent?: string;
  project: string | null;
  projectAgents: string[];
}) {
  const data = await safeApi<{ agents: number; rules: Applied[] }>("/api/policies/applied", { agents: 0, rules: [] });
  // Only this project's agents: a rule counts here where it reaches one of them, and
  // "all agents" means all of this project's.
  const mine = new Set(projectAgents);
  const scoped = data.rules
    .map((r) => {
      const here = r.agents.filter((a) => mine.has(a.slug));
      return { ...r, agents: here, all: here.length === mine.size };
    })
    .filter((r) => r.agents.length);
  const agents = Array.from(new Map(scoped.flatMap((r) => r.agents).map((a) => [a.slug, a])).values()).sort((a, b) => a.name.localeCompare(b.name));
  const rows = scoped.filter(
    (r) => (scope === "all" ? r.all : scope === "some" ? !r.all : true) && (!agent || r.agents.some((a) => a.slug === agent)),
  );
  const blocking = rows.filter((r) => r.mode === "enforce" && r.effect !== "allow").length;
  const link = (q: Record<string, string | undefined>) => href("/app/policies", { scope, agent, ...q });

  return (
    <section className="pol">
      <div className="pol-bar">
        <p className="pol-summary">
          <b>{rows.length}</b> rules on {agent ? agents.find((a) => a.slug === agent)?.name ?? agent : `${project ?? "this project"} (${mine.size === 1 ? "1 agent" : `${mine.size} agents`})`} ·{" "}
          <b className="pol-on">{blocking}</b> act now · <b className="pol-watch">{rows.length - blocking}</b> only watch
        </p>
        <div className="pol-filters">
          <div className="chipbar">
            {[
              ["", "All"],
              ["all", "On every agent here"],
              ["some", "On some agents"],
            ].map(([k, label]) => (
              <Link key={k} href={link({ scope: k || undefined })} className={(scope || "") === k ? "chip active" : "chip"} scroll={false}>
                {label}
              </Link>
            ))}
          </div>
          <form action="/app/policies" className="pol-agent">
            {scope ? <input type="hidden" name="scope" value={scope} /> : null}
            <select name="agent" defaultValue={agent || ""} aria-label="Show rules for one agent">
              <option value="">Every agent in {project ?? "the project"}</option>
              {agents.map((a) => (
                <option key={a.slug} value={a.slug}>
                  {a.name}
                </option>
              ))}
            </select>
            <button type="submit" className="k-btn">Show</button>
          </form>
        </div>
      </div>

      {rows.length ? (
        <ul className="pol-list">
          <li className="pol-head" aria-hidden>
            <span>Rule</span>
            <span>What it does</span>
            <span>Applies to</span>
            <span>From</span>
          </li>
          {rows.map((r) => {
            const d = does(r);
            return (
              <li key={r.id}>
                <Link href={`/app/policies/rules/${encodeURIComponent(r.id)}?tab=tune${agent ? `&agent=${encodeURIComponent(agent)}` : ""}`} className="pol-row">
                  <span className="pol-name">{ruleTitle(r.id, r.description)}</span>
                  <span className={`pol-does pol-${d.tone}`}>
                    {d.text}
                    {r.varies ? <em> · changed for some agents</em> : null}
                  </span>
                  <span className="pol-where" title={r.agents.map((a) => a.name).join(", ")}>
                    {where(r)}
                  </span>
                  <span className="pol-from">{r.libraries.join(", ")}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      ) : (
        <Empty>{project ? "No rules apply to this project yet. Apply a library or add a rule." : "Choose a project in the sidebar to see its rules."}</Empty>
      )}
    </section>
  );
}
