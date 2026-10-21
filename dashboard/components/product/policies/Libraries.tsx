import Link from "next/link";
import { safeApi } from "@/lib/product/api";
import { Act } from "@/components/kit/Act";

/**
 * Libraries: ready-made sets of rules, applied together. Each says what it covers,
 * how many rules it has, and whether it's applied: not yet, watching (records what it
 * would do), or blocking.
 */
export async function Libraries() {
  const [lib, policies] = await Promise.all([
    safeApi<any>("/api/library/packs", { packs: [] }),
    safeApi<any>("/api/policies", { policies: [] }),
  ]);
  const live: Record<string, any> = Object.fromEntries((policies.policies || []).map((p: any) => [p.key, p]));

  return (
    <section className="pol">
      <p className="pol-summary">A library is a set of rules you apply together. Applying one starts it watching: it records what it would stop, so you can check before it blocks.</p>
      <div className="lib-grid">
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
