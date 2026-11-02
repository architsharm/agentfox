import { safeApi } from "@/lib/product/api";
import { Act } from "@/components/kit/Act";
import { SimulateThenBlock } from "@/components/product/policies/SimulateLibrary";
import { ApplyChoice, LibraryCard } from "@/components/product/policies/LibraryCard";
import { LibraryDetail, type LibraryView } from "@/components/product/policies/LibraryDetail";
import { libraryPath, libraryState, whereOn, type LibraryContents, type LibraryStatus as Status } from "@/lib/product/libraries";

const NONE: Status = { agents: [], blocking: false, workspace: false };
const STARTER = "Starter rules (watch only)";

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
    <SimulateThenBlock
      library={id}
      body={body}
      confirm={`Start blocking with ${title} on ${project}? Its rules will stop traffic, not just record it. It needs a simulation of these rules first, by anyone, and someone allowed to change production policy to start it.`}
    />
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

/** One library's card and drawer: what both show, and the actions both carry. */
type Library = LibraryView & { className?: string; state: { text: string; tone: string; title?: string } };

/**
 * Every library, as it stands on the project chosen in the sidebar: the basic
 * guardrails, the starter rules while any agent still has them, and each shipped
 * library. Shared by the cards (Policies → Libraries, Add rule → Libraries) and a
 * library's own page, so all three say and do the same.
 *
 * One scope model: Apply puts a library on the project's agents; "every agent" is the
 * second choice behind ▾. A library of business rules only (payments) can't be
 * limited to a project, and says so.
 */
async function libraries(project: string, agents: string[]): Promise<Library[]> {
  const scope = `agents=${encodeURIComponent(agents.join(","))}`;
  const [lib, status, applied] = await Promise.all([
    safeApi<any>("/api/library/packs", { packs: [] }),
    safeApi<Record<string, Status>>(`/api/policies/libraries/status?${scope}&project=${encodeURIComponent(project)}`, {}),
    safeApi<any>("/api/policies/applied", { rules: [] }),
  ]);
  const packs: any[] = lib.packs || [];
  const contents = await Promise.all(
    ["basic", ...packs.map((p) => p.id)].map((id) => safeApi<LibraryContents | null>(`/api/library/packs/${libraryPath(id)}/contents?${scope}`, null)),
  );
  const contentsOf = (id: string) => contents.find((c) => c?.id === id) ?? null;
  const total = agents.length;
  const mine = new Set(agents);
  const body = { agents, project };
  const everyBody = { agents: [] };
  const on = (st: Status) => (st.agents.length ? st.agents.join(", ") : st.workspace ? "Every agent (applied workspace-wide)" : "Not applied");
  const mode = (st: Status) => (st.agents.length || st.workspace ? (st.blocking ? "blocking" : "watching") : null);

  const basic = status.basic || NONE;
  const basicOn = basic.agents.length;
  const basicTitle = "the basic guardrails";
  const out: Library[] = [
    {
      id: "basic",
      title: "Basic guardrails",
      className: "lib-default",
      description:
        "The default set: prompt attacks and jailbreaks in what users send, and personal data and secrets in replies. Nothing on tools. Watches first, then blocks the attacks and hides the data.",
      rules: contentsOf("basic")?.rules.length || 3,
      on: on(basic),
      mode: mode(basic),
      contents: contentsOf("basic"),
      project,
      state: libraryState(basic, total),
      actions: (
        <>
          {basicOn < total ? (
            <ApplyChoice
              project={{
                url: "/api/policies/libraries/basic/apply",
                body,
                label: basicOn ? "Apply to the rest" : `Apply to ${project}`,
                confirm: `Apply the basic guardrails to ${project}? They start by watching: they record what they would block and hide, and stop nothing. They block once they have been simulated and someone allowed to change production policy starts them.`,
              }}
              every={{
                url: "/api/policies/libraries/basic/apply",
                body: everyBody,
                label: "Apply to every agent",
                confirm: "Apply the basic guardrails to every agent in the workspace, not just this project's? Each starts by watching.",
              }}
            />
          ) : null}
          <UpdateAction id="basic" title={basicTitle} st={basic} body={body} />
          <ModeActions id="basic" title={basicTitle} project={project} st={basic} body={body} />
        </>
      ),
    },
  ];

  const starter = (applied.rules || []).filter((r: any) => r.libraries.includes(STARTER));
  const starterOn = new Set(starter.flatMap((r: any) => r.agents.map((a: any) => a.slug)).filter((s: string) => mine.has(s)));
  if (starterOn.size) {
    const st = { agents: Array.from(starterOn) as string[], blocking: false, workspace: false };
    out.push({
      id: "starter",
      title: STARTER,
      description: "Watch-only rules earlier versions of agentfox init added to each agent. Basic guardrails replace them.",
      rules: starter.length,
      on: on(st),
      mode: "watching",
      contents: null,
      ruleRows: starter.map((r: any) => ({ id: r.id, description: r.description, surfaces: [], effect: r.effect })),
      project,
      state: { text: `On ${whereOn(starterOn.size, total)} · watching`, tone: "pol-watch" },
      actions: (
        <Act url="/api/policies/libraries/starter/remove" body={body} className="k-btn" done="Removed" confirm={`Remove the starter rules from ${project}? Anything else set for its agents stays.`}>
          Remove
        </Act>
      ),
    });
  }

  for (const p of packs) {
    const c = contentsOf(p.id);
    const st = status[p.id] || NONE;
    const n = st.agents.length;
    const id = libraryPath(p.id);
    const ladders = p.policies.length === 0;
    const state = libraryState(st, total);
    const ladderMode = p.installed ? (c?.rules.every((r) => r.mode === "enforce") ? "blocking" : "watching") : null;
    out.push({
      id: p.id,
      title: p.title,
      description: p.description,
      rules: p.policies.reduce((s: number, x: any) => s + x.rules, 0) + p.ladders.length,
      // A library of business rules is on every agent or none.
      on: ladders ? (p.installed ? "Every agent" : "Not applied") : on(st),
      mode: ladders ? ladderMode : mode(st),
      contents: c,
      note: ladders ? "Business rules apply to every agent: this library can't be limited to one project." : undefined,
      project,
      state: ladders
        ? { text: ladderMode ? `On every agent · ${ladderMode}` : "Not applied", tone: ladderMode ? (ladderMode === "blocking" ? "pol-on" : "pol-watch") : "" }
        : { ...state, title: st.workspace && !n ? "Applied before libraries were per project: it reaches every agent" : undefined },
      actions: ladders ? (
        !p.installed ? (
          <Act url={`/api/library/packs/${p.id}`} className="k-btn-primary" done="Applied" confirm="This library's rules apply to every agent, not one project.">
            Apply to every agent
          </Act>
        ) : null
      ) : (
        <>
          {n < total && !(st.workspace && !n) ? (
            <ApplyChoice
              project={{ url: `/api/policies/libraries/${id}/apply`, body, label: n ? "Apply to the rest" : `Apply to ${project}` }}
              every={{
                url: `/api/policies/libraries/${id}/apply`,
                body: everyBody,
                label: "Apply to every agent",
                confirm: `Apply ${p.title} to every agent in the workspace, not just ${project}'s? Each starts by watching.`,
              }}
            />
          ) : null}
          <UpdateAction id={id} title={p.title} st={st} body={body} />
          <ModeActions id={id} title={p.title} project={project} st={st} body={body} />
        </>
      ),
    });
  }
  return out;
}

const CHOOSE = <p className="pol-summary">Choose a project in the sidebar: libraries apply to one project&apos;s agents at a time.</p>;

/**
 * Libraries: sets of rules applied together, to the agents of the project chosen in
 * the sidebar and no others. Each card says what it covers, how many rules, and where
 * it stands for this project: not applied, watching (records what it would stop), or
 * blocking. Clicking a card opens its drawer: every rule in it, and its last simulation.
 */
export async function Libraries({ project, agents }: { project: string | null; agents: string[] }) {
  if (!project || !agents.length) return CHOOSE;
  const all = await libraries(project, agents);
  const total = agents.length;
  return (
    <section className="pol">
      <p className="pol-summary">
        A library is a set of rules you apply together. Applying one here applies it to <b>{project}</b>&apos;s {total === 1 ? "agent" : `${total} agents`} only, watching first: it
        records what it would stop, so you can check before it blocks. Click one to see its rules.
      </p>
      <div className="lib-grid">
        {all.map((l) => (
          <LibraryCard
            key={l.id}
            id={l.id}
            title={l.title}
            className={l.className}
            head={
              <>
                <div className="lib-head">
                  <strong>{l.title}</strong>
                  <span className="lib-n">{l.rules} rules</span>
                </div>
                <p>{l.description}</p>
              </>
            }
            state={
              <span className={`lib-state ${l.state.tone}`} title={l.state.title}>
                {l.state.text}
              </span>
            }
            actions={l.actions}
            drawer={<LibraryDetail v={l} />}
          />
        ))}
      </div>
    </section>
  );
}

/** A library's contents by its id, or by the key of a policy it ships; null when neither. */
export async function findLibrary(key: string, agents: string[]): Promise<LibraryContents | null> {
  return safeApi<LibraryContents | null>(`/api/library/packs/${libraryPath(key)}/contents?agents=${encodeURIComponent(agents.join(","))}`, null);
}

/**
 * One library as a page, for /app/policies/<library> when no policy has that key: the
 * drawer's body, with the same actions.
 */
export async function LibraryPage({ found, project, agents }: { found: LibraryContents; project: string | null; agents: string[] }) {
  const bare: LibraryView = { ...found, rules: found.rules.length, on: "—", mode: null, contents: found, project, actions: null };
  if (!project || !agents.length)
    return (
      <>
        <LibraryDetail v={bare} />
        {CHOOSE}
      </>
    );
  const l = (await libraries(project, agents)).find((x) => x.id === found.id);
  return <LibraryDetail v={l ?? bare} />;
}
