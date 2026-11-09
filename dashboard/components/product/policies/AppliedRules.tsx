import Link from "next/link";
import { safeApi } from "@/lib/product/api";
import { Empty, href } from "@/components/kit";
import { InstantForm } from "@/components/product/InstantForm";
import { ruleTitle, wouldDo } from "@/lib/product/vocab";
import { groupApplied, type AppliedMode } from "@/lib/product/libraries";

type Applied = {
  id: string;
  description: string;
  effect: string;
  varies: boolean;
  mode: "enforce" | "observe" | "mixed";
  all: boolean;
  agents: { slug: string; name: string }[];
  libraries: string[];
  /** Applied by the enforcer itself (Tool containment's missing-grant and composed-escalation checks): no rule page to open. */
  builtIn?: boolean;
};

const DOES: Record<string, string> = { block: "Blocks", escalate: "Asks a person", redact: "Hides", mask: "Hides", tokenize: "Hides", allow: "Watches" };

/**
 * "Blocks", or "Would block · watching" while its library only records. Blocking
 * reads red, holding amber, hiding blue; watching and allowing are quiet.
 */
function does(r: Applied): { text: string; tone: string } {
  const text = DOES[r.effect] ?? r.effect;
  if (r.effect === "allow") return { text, tone: "quiet" };
  if (r.mode === "observe") return { text: `${wouldDo(text)} · watching`, tone: "quiet" };
  const tone = r.effect === "block" ? "block" : r.effect === "escalate" ? "held" : "hide";
  if (r.mode === "mixed") return { text: `${text} · on some, watching on others`, tone };
  return { text, tone };
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
  mode,
  project,
  projectAgents,
}: {
  scope?: string;
  agent?: string;
  /** "enforce": only the rules that act now; "observe": only the ones watching. */
  mode?: string;
  project: string | null;
  projectAgents: string[];
}) {
  const data = await safeApi<{ agents: number; rules: Applied[] } | null>("/api/policies/applied", null);
  // A failed read is not "0 rules": saying so beside a library that blocks is the
  // contradiction this page must never show.
  if (!data) return <Empty>Couldn&apos;t load the rules in force right now. Reload the page to try again.</Empty>;
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
  const inScope = scoped.filter(
    (r) => (scope === "all" ? r.all : scope === "some" ? !r.all : true) && (!agent || r.agents.some((a) => a.slug === agent)),
  );
  const acts = (r: Applied) => r.mode !== "observe" && r.effect !== "allow";
  const blocking = inScope.filter(acts).length;
  const want = (mode === "enforce" || mode === "observe" ? mode : "") as AppliedMode;
  const rows = inScope.filter((r) => (want === "enforce" ? acts(r) : want === "observe" ? !acts(r) : true));
  const groups = groupApplied(rows);
  const link = (q: Record<string, string | undefined>) => href("/app/policies", { scope, agent, mode, ...q });

  return (
    <section className="pol">
      <div className="pol-bar">
        <p className="pol-summary">
          <b>{inScope.length}</b> rules on {agent ? agents.find((a) => a.slug === agent)?.name ?? agent : `${project ?? "this project"} (${mine.size === 1 ? "1 agent" : `${mine.size} agents`})`} ·{" "}
          <b className="pol-on">{blocking}</b> act now · <b className="pol-watch">{inScope.length - blocking}</b> only watch
        </p>
        <div className="pol-filters">
          <div className="chipbar" role="group" aria-label="Blocking or watching" style={{ marginRight: 8 }}>
            {[
              ["", "Any mode"],
              ["enforce", "Blocking"],
              ["observe", "Watching"],
            ].map(([k, label]) => (
              <Link key={k} href={link({ mode: k || undefined })} className={(want || "") === k ? "chip active" : "chip"} scroll={false}>
                {label}
              </Link>
            ))}
          </div>
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
          <InstantForm action="/app/policies" className="pol-agent">
            {scope ? <input type="hidden" name="scope" value={scope} /> : null}
            <select name="agent" defaultValue={agent || ""} aria-label="Show rules for one agent">
              <option value="">Every agent in {project ?? "the project"}</option>
              {agents.map((a) => (
                <option key={a.slug} value={a.slug}>
                  {a.name}
                </option>
              ))}
            </select>
          </InstantForm>
        </div>
      </div>

      {rows.length ? (
        <div className="pol-groups">
          {groups.map((g) => (
            <section key={g.library} className="pol-list pol-group" aria-label={g.library}>
              <div className="pol-group-head">
                <strong>{g.library}</strong>
                <span>
                  {g.rules.length} {g.rules.length === 1 ? "rule" : "rules"} · {g.blocking ? `${g.blocking} act now` : "watching"}
                  {g.blocking && g.blocking < g.rules.length ? ` · ${g.rules.length - g.blocking} watching` : ""}
                </span>
              </div>
              <ul className="pol-list-plain">
                {g.rules.map((r) => {
                  const d = does(r);
                  return (
                    <li key={r.id}>
                      <Link
                        href={r.builtIn ? "/app/policies?tab=libraries" : `/app/policies/rules/${encodeURIComponent(r.id)}?tab=tune${agent ? `&agent=${encodeURIComponent(agent)}` : ""}`}
                        className="pol-row"
                        title={r.builtIn ? "Built into Tool containment: it blocks where that library blocks" : undefined}
                      >
                        <span className="pol-name">{ruleTitle(r.id, r.description)}</span>
                        <span className={`pol-does pol-${d.tone}`}>
                          {d.text}
                          {r.varies ? <em> · changed for some agents</em> : null}
                        </span>
                        {/* Only said when it is not every agent here: the group says the rest once. */}
                        <span className="pol-where" title={r.agents.map((a) => a.name).join(", ")}>
                          {r.all ? "" : where(r)}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      ) : (
        <Empty>{project ? "No rules apply to this project yet. Apply a library or add a rule." : "Choose a project in the sidebar to see its rules."}</Empty>
      )}
    </section>
  );
}
