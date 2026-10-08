import { safeApi } from "@/lib/product/api";
import { Card, Pill } from "@/components/kit";
import { Act } from "@/components/kit/Act";
import { SURFACES, detectorName } from "@/lib/product/vocab";

type Detector = {
  key: string;
  label: string | null;
  surfaces: string[];
  available: boolean;
  enabled: boolean;
  always_on: boolean;
  unavailable_reason: string | null;
  install: string | null;
  stats: { runs?: number; avg_ms?: number };
};

const name = (d: Detector) => (detectorName(d.key) !== d.key ? detectorName(d.key) : d.label || d.key);
const checks = (d: Detector) => {
  const all = Array.from(new Set(d.surfaces.map((s) => SURFACES[s] || s)));
  return all.length > 3 ? `${all.slice(0, 2).join(" · ")} +${all.length - 2}` : all.join(" · ");
};

/** What finds problems in traffic. One switch per detector, for the whole workspace. */
export async function Detectors() {
  const data = await safeApi<any>("/api/detectors", { detectors: [] });
  const all: Detector[] = data.detectors || [];
  const installed = all.filter((d) => d.available);
  const missing = all.filter((d) => !d.available);

  return (
    <>
      <Card flush>
        <table className="k-table">
          <tbody>
            {installed.map((d) => (
              <tr key={d.key}>
                <td>
                  <span className="k-name">{name(d)}</span>
                  <span className="sub">{checks(d)}</span>
                </td>
                <td className="tight muted">{d.stats.avg_ms ? `${d.stats.avg_ms < 1 ? "<1" : Math.round(d.stats.avg_ms)} ms` : ""}</td>
                <td className="tight">
                  {d.always_on ? (
                    <Pill tone="outline">Always on</Pill>
                  ) : (
                    <Act url={`/api/detectors/${encodeURIComponent(d.key)}`} body={{ enabled: !d.enabled }} className={d.enabled ? "k-btn" : "k-btn-primary"}>
                      {d.enabled ? "Turn off" : "Turn on"}
                    </Act>
                  )}
                </td>
                <td className="tight">{d.enabled ? <Pill tone="ok">On</Pill> : <Pill tone="outline">Off</Pill>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {missing.length > 0 && (
        <details className="k-details">
          <summary>Not installed here ({missing.length})</summary>
          <Card flush>
            <table className="k-table">
              <tbody>
                {missing.map((d) => (
                  <tr key={d.key}>
                    <td>
                      <span className="k-name">{name(d)}</span>
                      <span className="sub">{checks(d)}</span>
                    </td>
                    <td className="muted" title={d.unavailable_reason || undefined}>
                      {d.install ? <code className="k-mono">pip install {d.install}</code> : "Needs setup"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </details>
      )}
    </>
  );
}
