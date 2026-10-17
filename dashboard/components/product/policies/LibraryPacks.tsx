import { safeApi } from "@/lib/product/api";
import { Pill } from "@/components/kit";
import { Act } from "@/components/kit/Act";

/** The packs that ship with AgentFox, each installable (watching) in one click. */
export async function LibraryPacks() {
  const packs = await safeApi<any>("/api/library/packs", { packs: [] });
  return (
    <div className="k-grid k-grid-3">
      {(packs.packs || []).map((p: any) => {
        const rules = p.policies.reduce((n: number, x: any) => n + x.rules, 0) + p.ladders.length;
        return (
          <section key={p.id} className="k-card k-tile">
            <div className="k-card-body">
              <div className="k-tile-head">
                <strong>{p.title}</strong>
                {p.installed ? <Pill tone="ok">Installed</Pill> : null}
              </div>
              <p className="k-tile-text">{p.description}</p>
              <div className="k-tile-foot">
                <span className="k-muted">{rules} rules</span>
                {!p.installed && (
                  <Act url={`/api/library/packs/${p.id}`} className="k-btn-primary" done="Installed">
                    Install
                  </Act>
                )}
              </div>
            </div>
          </section>
        );
      })}
    </div>
  );
}
