import { safeApi } from "@/lib/product/api";
import { Act } from "@/components/kit/Act";
import { SimulateLibrary } from "@/components/product/policies/SimulateLibrary";

type Status = { agents: string[]; blocking: boolean; workspace: boolean; outdated?: boolean; outdatedAgents?: string[] };
const NONE: Status = { agents: [], blocking: false, workspace: false };

/**
 * Watching or blocking with a library on this project's agents. Blocking goes through
 * the same gate as any policy: simulate first (it records what the rules would have
 * done), then someone allowed to change production policy starts it. The server's
 * refusal, if any, shows beside the button.
 */
function ModeActions({ id, title, project, st, body }: { id: string; title: string; project: string; st: Status; body: object }) {
  if (!st.agents.length) return null;
  if (st.blocking)
    return (
      <Act url={`/api/policies/libraries/${id}/mode`} body={{ ...body, mode: "observe" }} className="k-btn" done="Watching" confirm={`Switch ${title} on ${project} back to watching? It records what it would do and stops nothing.`}>
        Back to watching
      </Act>
    );
  return (
    <>
      <SimulateLibrary library={id} body={body} />
      <Act
        url={`/api/policies/libraries/${id}/mode`}
        body={{ ...body, mode: "enforce" }}
        className="k-btn"
        done="Blocking"
        confirm={`Start blocking with ${title} on ${project}? Its rules will stop traffic, not just record it. It needs a simulation of these rules first, by anyone, and someone allowed to change production policy to start it.`}
      >
        Start blocking
      </Act>
    </>
  );
}

/** "Update", when the library has changed since it was applied to some of these agents. */
function UpdateAction({ id, title, st, body }: { id: string; title: string; st: Status; body: object }) {
  const n = st.outdatedAgents?.length ?? 0;
  if (!st.outdated || !n) return null;
  return (
    <Act url={`/api/policies/libraries/${id}/apply`} body={body} className="k-btn" done="Updated" confirm={`Update ${title} on ${n === 1 ? "1 agent" : `${n} agents`} to the latest version? Each keeps watching or blocking as it is; a blocking one is simulated on the way in.`}>
      Update
    </Act>
  );
}

/**
 * Libraries: sets of rules applied together, to the agents of the project chosen in
 * the sidebar and no others. Each says what it covers, how many rules, and where it
 * stands for this project: not applied, watching (records what it would stop), or
 * blocking.
 */
export async function Libraries({ project, agents }: { project: string | null; agents: string[] }) {
  if (!project || !agents.length) {
    return <p className="pol-summary">Choose a project in the sidebar: libraries apply to one project&apos;s agents at a time.</p>;
  }
  const [lib, status, applied] = await Promise.all([
    safeApi<any>("/api/library/packs", { packs: [] }),
    safeApi<Record<string, Status>>(`/api/policies/libraries/status?agents=${encodeURIComponent(agents.join(","))}&project=${encodeURIComponent(project)}`, {}),
    safeApi<any>("/api/policies/applied", { rules: [] }),
  ]);
  const total = agents.length;
  const mine = new Set(agents);
  const onIn = (library: string) =>
    new Set((applied.rules || []).filter((r: any) => r.libraries.includes(library)).flatMap((r: any) => r.agents.map((a: any) => a.slug)).filter((s: string) => mine.has(s)));
  const basic = status.basic || NONE;
  const basicOn = basic.agents.length;
  const starterOn = onIn("Starter rules (watch only)").size;
  const body = { agents, project };
  const where = (n: number) => (n === total ? `all ${total === 1 ? "" : `${total} `}agents` : `${n} of ${total} agents`).replace("all agents", "the agent");

  return (
    <section className="pol">
      <p className="pol-summary">
        A library is a set of rules you apply together. Applying one here applies it to <b>{project}</b>&apos;s {total === 1 ? "agent" : `${total} agents`} only, watching first: it
        records what it would stop, so you can check before it blocks.
      </p>
      <div className="lib-grid">
        <article className="lib-card lib-default">
          <div className="lib-head">
            <strong>Basic guardrails</strong>
            <span className="lib-n">3 rules</span>
          </div>
          <p>The default set: prompt attacks and jailbreaks in what users send, and personal data and secrets in replies. Nothing on tools. Watches first, then blocks the attacks and hides the data.</p>
          <div className="lib-foot">
            <span className={`lib-state ${basicOn ? (basic.blocking ? "pol-on" : "pol-watch") : ""}`}>
              {basicOn ? `On ${where(basicOn)} · ${basic.blocking ? "blocking" : "watching"}${basic.outdated ? " · update available" : ""}` : "Not applied"}
            </span>
            <span className="lib-actions">
              {basicOn < total ? (
                <Act
                  url="/api/policies/libraries/basic/apply"
                  body={body}
                  className="k-btn-primary"
                  done="Applied"
                  confirm={`Apply the basic guardrails to ${project}? They start by watching: they record what they would block and hide, and stop nothing. They block once they have been simulated and someone allowed to change production policy starts them.`}
                >
                  {basicOn ? "Apply to the rest" : `Apply to ${project}`}
                </Act>
              ) : null}
              <UpdateAction id="basic" title="the basic guardrails" st={basic} body={body} />
              <ModeActions id="basic" title="the basic guardrails" project={project} st={basic} body={body} />
            </span>
          </div>
        </article>
        {starterOn ? (
          <article className="lib-card">
            <div className="lib-head">
              <strong>Starter rules (watch only)</strong>
              <span className="lib-n">11 rules</span>
            </div>
            <p>Watch-only rules earlier versions of agentfox init added to each agent. Basic guardrails replace them.</p>
            <div className="lib-foot">
              <span className="lib-state pol-watch">On {where(starterOn)} · watching</span>
              <Act url="/api/policies/libraries/starter/remove" body={body} className="k-btn" done="Removed" confirm={`Remove the starter rules from ${project}? Anything else set for its agents stays.`}>
                Remove
              </Act>
            </div>
          </article>
        ) : null}
        {(lib.packs || []).map((p: any) => {
          const rules = p.policies.reduce((n: number, x: any) => n + x.rules, 0) + p.ladders.length;
          const st = status[p.id] || NONE;
          const on = st.agents.length;
          const id = encodeURIComponent(p.id).replace(/%2F/g, "/");
          const onlyLadders = p.policies.length === 0;
          return (
            <article key={p.id} className="lib-card">
              <div className="lib-head">
                <strong>{p.title}</strong>
                <span className="lib-n">{rules} rules</span>
              </div>
              <p>{p.description}</p>
              <div className="lib-foot">
                {on ? (
                  <span className={`lib-state ${st.blocking ? "pol-on" : "pol-watch"}`}>
                    On {where(on)} · {st.blocking ? "blocking" : "watching"}
                    {st.outdated ? " · update available" : ""}
                  </span>
                ) : st.workspace ? (
                  <span className={`lib-state ${st.blocking ? "pol-on" : "pol-watch"}`} title="Applied before libraries were per project: it reaches every agent">
                    On every agent (workspace) · {st.blocking ? "blocking" : "watching"}
                  </span>
                ) : (
                  <span className="lib-state">Not applied</span>
                )}
                <span className="lib-actions">
                  {onlyLadders ? (
                    !p.installed ? (
                      <Act url={`/api/library/packs/${p.id}`} className="k-btn" done="Applied" confirm="This library's rules apply to every agent, not one project.">
                        Apply to every agent
                      </Act>
                    ) : null
                  ) : on < total && !(st.workspace && !on) ? (
                    <Act url={`/api/policies/libraries/${id}/apply`} body={body} className="k-btn-primary" done="Applied">
                      {on ? "Apply to the rest" : `Apply to ${project}`}
                    </Act>
                  ) : null}
                  <UpdateAction id={id} title={p.title} st={st} body={body} />
                  <ModeActions id={id} title={p.title} project={project} st={st} body={body} />
                </span>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
