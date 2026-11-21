/**
 * Building blocks for the two benchmark pages (/benchmark, /benchmark/latency), on
 * the home page's type scale and visual language (app/lp.css).
 */

import { CopyButton } from "@/components/docs/copy";
import { REPO_URL, SITE_URL } from "@/lib/site";

import { CopyChip } from "./client";
import { Arrow } from "./parts";

export const SRC = `${REPO_URL}/blob/main`;

export type Bar = { name: string; value: number; label: string; ours?: boolean };

/** One comparison as horizontal bars. `max` sets the full width; defaults to 100. */
export function BarCard({
  title,
  hint,
  rows,
  note,
  max = 100,
  loss = false,
}: {
  title: string;
  hint: string;
  rows: Bar[];
  note?: string;
  max?: number;
  loss?: boolean;
}) {
  return (
    <div className={`lp-pair${loss ? " is-loss" : ""}`}>
      <div className="lp-pair-head">
        <h3>{title}</h3>
        <span>{hint}</span>
      </div>
      {rows.map((r) => (
        <div key={r.name} className={`lp-pair-row${r.ours ? " is-ours" : ""}`}>
          <span className="lp-pair-name">{r.name}</span>
          <span className="lp-pair-track">
            <i style={{ "--w": r.value === 0 ? "0%" : `${Math.max(0.6, (r.value / max) * 100)}%` } as React.CSSProperties} />
          </span>
          <span className="lp-pair-v">{r.label}</span>
        </div>
      ))}
      {note && <p className="lp-pair-src">{note}</p>}
    </div>
  );
}

/** A numbered section of a benchmark write-up. */
export function DocSection({
  id,
  n,
  title,
  lead,
  children,
}: {
  id: string;
  /** Shown only where the order carries meaning, as on the benchmark pages. */
  n?: number;
  title: string;
  lead?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="lp-doc-sec">
      {n !== undefined && <span className="lp-doc-n">{String(n).padStart(2, "0")}</span>}
      <h2>{title}</h2>
      {lead && <p className="lp-doc-lead">{lead}</p>}
      {children}
    </section>
  );
}

/** A plain table in the home page's style. `ours` rows are highlighted. */
export function Table({
  head,
  rows,
  source,
}: {
  head: string[];
  rows: { cells: React.ReactNode[]; ours?: boolean }[];
  source?: { label: string; path: string };
}) {
  return (
    <figure className="lp-doc-fig">
      <div className="lp-doc-scroll" tabIndex={0} role="region" aria-label={head.join(", ")}>
        <table className="lp-table">
          <thead>
            <tr>
              {head.map((h, i) => (
                <th key={i}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={r.ours ? "is-ours" : undefined}>
                {r.cells.map((c, j) => (
                  <td key={j}>{c}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {source && <Source {...source} />}
    </figure>
  );
}

export function Source({ label, path }: { label: string; path: string }) {
  return (
    <figcaption className="lp-doc-src">
      Source:{" "}
      <a href={`${SRC}/${path}`} target="_blank" rel="noreferrer">
        {label}
      </a>
    </figcaption>
  );
}

/** What a result does not show. Every section has one. */
export function Limits({ items, label = "Limits" }: { items: React.ReactNode[]; label?: string }) {
  return (
    <div className="lp-doc-limits">
      <span>{label}</span>
      <ul>
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </div>
  );
}

export function Rerun({ commands }: { commands: string[] }) {
  return (
    <div className="lp-doc-rerun">
      {commands.map((c) => (
        <CopyChip key={c} text={c} wide />
      ))}
    </div>
  );
}

/** The contents strip under the hero. */
export function Contents({ items }: { items: { id: string; label: string }[] }) {
  return (
    <nav className="lp-doc-toc" aria-label="On this page">
      {items.map((it, i) => (
        <a key={it.id} href={`#${it.id}`}>
          <i>{String(i + 1).padStart(2, "0")}</i>
          {it.label}
        </a>
      ))}
    </nav>
  );
}

/** The accepted paper behind the detector comparison. */
export function PaperCard() {
  return (
    <a className="lp-paper" href="https://github.com/architsharm/waiti2026-artifact" target="_blank" rel="noreferrer">
      <h3>No Tier Wins Everywhere: Benchmarking Rules, Classifiers, a Judgment Model and an LLM as Security Detectors for AI Agents</h3>
      <p>
        Accepted at WAITI 2026, a workshop of ACSAC 2026, to be presented in Los Angeles on 7 December. Five kinds of
        detector compared on the same rows across eight kinds of security decision: 21 labelled datasets, 175,816 labelled decisions.
      </p>
      <span className="lp-paper-link">
        Per-row decisions and scripts <Arrow />
      </span>
    </a>
  );
}

/** A citation for the page, as BibTeX. A number with a stable reference gets quoted; one inside a paragraph does not. */
export function Cite({ id, title, path }: { id: string; title: string; path: string }) {
  const bib = `@misc{${id},\n  title = {${title}},\n  author = {{Nometria}},\n  year = {2026},\n  howpublished = {\\url{${SITE_URL}${path}}},\n  note = {Scripts and results files: ${REPO_URL}}\n}`;
  return (
    <figure className="lp-doc-cite">
      <figcaption>Cite this page</figcaption>
      <pre>{bib}</pre>
      <CopyButton text={bib} />
    </figure>
  );
}

/** Dataset structured data for a benchmark page: the results files behind it, as downloads. */
export function DatasetLd({ name, description, path, files }: { name: string; description: string; path: string; files: string[] }) {
  const data = {
    "@context": "https://schema.org",
    "@type": "Dataset",
    name,
    description,
    url: `${SITE_URL}${path}`,
    license: "https://www.apache.org/licenses/LICENSE-2.0",
    isAccessibleForFree: true,
    creator: { "@id": `${SITE_URL}/#organisation` },
    distribution: files.map((f) => ({
      "@type": "DataDownload",
      encodingFormat: f.endsWith(".csv") ? "text/csv" : "application/json",
      contentUrl: `${REPO_URL.replace("github.com", "raw.githubusercontent.com")}/main/${f}`,
    })),
  };
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />;
}
