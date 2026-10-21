import Link from "next/link";
import { safeApi } from "@/lib/product/api";
import { Act } from "@/components/kit/Act";

/**
 * Libraries: ready-made sets of rules, applied together. Each says what it covers,
 * how many rules it has, and whether it's applied: not yet, watching (records what it
 * would do), or blocking.
 */
export async function Libraries() {
  const [lib, policies, applied] = await Promise.all([
    safeApi<any>("/api/library/packs", { packs: [] }),
    safeApi<any>("/api/policies", { policies: [] }),
    safeApi<any>("/api/policies/applied", { agents: 0, perAgent: {} }),
  ]);
  const total: number = applied.agents || 0;
  const basic = applied.perAgent?.["Basic guardrails"] || { agents: 0, rules: 0 };
  const starter = applied.perAgent?.["Starter rules (watch only)"] || { agents: 0, rules: 0 };
  const live: Record<string, any> = Object.fromEntries((policies.policies || []).map((p: any) => [p.key, p]));

  return (
    <section className="pol">
      <p className="pol-summary">A library is a set of rules you apply together. Applying one starts it watching: it records what it would stop, so you can check before it blocks.</p>
      <div className="lib-grid">
        <article className="lib-card lib-default">
          <div className="lib-head">
            <strong>Basic guardrails</strong>
            <span className="lib-n">3 rules</span>
          </div>
          <p>The default set. Blocks prompt attacks and jailbreaks in what users send; hides personal data and secrets in replies. Nothing on tools.</p>
          <div className="lib-foot">
            <span className={`lib-state ${basic.agents ? "pol-on" : ""}`}>
              {basic.agents ? `On ${basic.agents === total ? "all" : `${basic.agents} of ${total}`} agents · blocking` : "Not applied"}
            </span>
            {basic.agents < total ? (
              <Act url="/api/policies/libraries/basic/apply" className="k-btn-primary" done="Applied" confirm="Apply the basic guardrails to every agent? They block from the start.">
                Apply to all agents
              </Act>
            ) : null}
          </div>
        </article>
        {starter.agents ? (
          <article className="lib-card">
            <div className="lib-head">
              <strong>Starter rules (watch only)</strong>
              <span className="lib-n">{starter.rules} rules</span>
            </div>
            <p>Watch-only rules earlier versions of agentfox init added to each agent. Basic guardrails replace them.</p>
            <div className="lib-foot">
              <span className="lib-state pol-watch">On {starter.agents} agents · watching</span>
              <Act url="/api/policies/libraries/starter/remove" className="k-btn" done="Removed" confirm="Remove the starter rules from every agent? Anything else set for an agent stays.">
                Remove
              </Act>
            </div>
          </article>
        ) : null}
        {(lib.packs || []).map((p: any) => {
          const rules = p.policies.reduce((n: number, x: any) => n + x.rules, 0) + p.ladders.length;
          const keys: string[] = p.policies.map((x: any) => x.key);
          const bound = keys.map((k) => live[k]).filter(Boolean);
          const blocking = bound.length > 0 && bound.every((x: any) => x.mode === "enforce");
          const scope = bound.some((x: any) => x.level === "agent") ? "some agents" : "all agents";
          return (
            <article key={p.id} className="lib-card">
              <div className="lib-head">
                <strong>{p.title}</strong>
                <span className="lib-n">{rules} rules</span>
              </div>
              <p>{p.description}</p>
              <div className="lib-foot">
                {!p.installed ? (
                  <>
                    <span className="lib-state">Not applied</span>
                    <Act url={`/api/library/packs/${p.id}`} className="k-btn-primary" done="Applied">
                      Apply to all agents
                    </Act>
                  </>
                ) : (
                  <>
                    <span className={`lib-state ${blocking ? "pol-on" : "pol-watch"}`}>
                      On {scope} · {blocking ? "blocking" : "watching"}
                    </span>
                    {keys[0] ? (
                      <span className="lib-actions">
                        <Link href={`/app/policies/${encodeURIComponent(keys[0])}`} className="k-btn">
                          See rules
                        </Link>
                        {blocking ? (
                          <Act url={`/api/policies/${encodeURIComponent(keys[0])}/mode`} body={{ mode: "observe" }} className="k-btn" done="Watching">
                            Back to watching
                          </Act>
                        ) : (
                          <Act
                            url={`/api/policies/${encodeURIComponent(keys[0])}/mode`}
                            body={{ mode: "enforce" }}
                            className="k-btn-primary"
                            done="Blocking"
                            confirm={`Start blocking with ${p.title}? Its rules will stop traffic, not just record it.`}
                          >
                            Start blocking
                          </Act>
                        )}
                      </span>
                    ) : null}
                  </>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
