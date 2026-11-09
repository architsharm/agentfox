/**
 * Building blocks for the docs pages. Every page under /docs uses these rather than
 * hand-rolled markup, so a code block, a warning and a numbered walkthrough look the
 * same everywhere.
 *
 * Commands inside <Code> are checked in CI: scripts/gen/docs_reference.py --check resolves
 * every `agentfox ...` line against the live CLI, flags included.
 */
import Link from "next/link";
import type { ReactNode } from "react";

import { CopyButton } from "./copy";

export function Code({
  children,
  title,
  lang = "bash",
  copy = true,
}: {
  /** The code itself, as a template literal: <Code>{`agentfox scan`}</Code> */
  children: string;
  /** A file name or a caption, shown above the block. */
  title?: string;
  /** bash | python | ts | yaml | toml | json | text (output) */
  lang?: string;
  copy?: boolean;
}) {
  const text = children.replace(/^\n+|\s+$/g, "");
  return (
    <figure className={`docs-code docs-code-${lang}`}>
      {(title || copy) && (
        <figcaption>
          <span>{title ?? (lang === "text" ? "Output" : lang)}</span>
          {copy && lang !== "text" && <CopyButton text={text} />}
        </figcaption>
      )}
      {/* Focusable so a keyboard user can scroll a long line sideways. */}
      <pre tabIndex={0}>
        <code>{text}</code>
      </pre>
    </figure>
  );
}

/** What a command prints. Never copied, visually quieter than a command. */
export function Output({ children, title }: { children: string; title?: string }) {
  return (
    <Code lang="text" copy={false} title={title ?? "Output"}>
      {children}
    </Code>
  );
}

export function Callout({
  kind = "note",
  title,
  children,
}: {
  kind?: "note" | "tip" | "warning";
  title?: string;
  children: ReactNode;
}) {
  const label = title ?? { note: "Note", tip: "Tip", warning: "Careful" }[kind];
  return (
    <aside className={`docs-callout docs-callout-${kind}`} role="note">
      <p className="docs-callout-title">{label}</p>
      <div>{children}</div>
    </aside>
  );
}

/**
 * For pages whose commands name the demo's agents: a command such as
 * `permit grant support-triage …` fails with "unknown agent" on a reader's own data.
 */
export function DemoAgentNames() {
  return (
    <Callout kind="note" title="Agent names in these examples">
      <p>
        The commands name the demo&apos;s agents, <code>support-triage</code> and{" "}
        <code>payments-ops</code>. Use your own agent&apos;s name instead (
        <code>agentfox agents list</code> shows them), or run{" "}
        <code>agentfox demo --in-workspace</code> first to follow along with the demo&apos;s.
      </p>
    </Callout>
  );
}

/** A numbered walkthrough. Each <Step> is one thing the reader does. */
export function Steps({ children, topLevel = false }: { children: ReactNode; topLevel?: boolean }) {
  return (
    <>
      {/* Each step's title is an h3. Straight under the page's h1, screen readers
          need an h2 above them, or the outline skips a level. */}
      {topLevel && <h2 className="sr-only">Steps</h2>}
      <ol className="docs-steps">{children}</ol>
    </>
  );
}

export function Step({ title, children }: { title: string; children: ReactNode }) {
  return (
    <li className="docs-step">
      <h3>{title}</h3>
      {children}
    </li>
  );
}

/** "In the web app: Agents → support-bot → Kill switch" */
export function InTheApp({ path, children }: { path: string; children: ReactNode }) {
  return (
    <p className="docs-inapp">
      <span>In the web app</span>{" "}
      <Link href={path}>{children}</Link>
    </p>
  );
}

/** The links at the foot of a page: where to go next. */
export function NextSteps({ items }: { items: { href: string; label: string; why?: string }[] }) {
  return (
    <nav className="docs-next" aria-label="Next">
      <p>Next</p>
      <ul>
        {items.map((item) => (
          <li key={item.href}>
            <Link href={item.href}>{item.label}</Link>
            {item.why && <span>: {item.why}</span>}
          </li>
        ))}
      </ul>
    </nav>
  );
}

/**
 * A screenshot of the product, bordered and captioned. Files live under
 * public/docs/screens/; give the image's real pixel size so the page does not jump
 * while it loads. Use one per step that changes what the reader sees, no more.
 */
export function Screenshot({
  src,
  alt,
  caption,
  width,
  height,
}: {
  /** Under /docs/screens/, e.g. "/docs/screens/setup-key.png" */
  src: string;
  /** What the image shows, for someone who cannot see it. */
  alt: string;
  /** One line under the image. */
  caption?: ReactNode;
  width: number;
  height: number;
}) {
  return (
    <figure className="docs-shot">
      {/* A plain <img>: these are static files, shown at their own size. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} width={width} height={height} loading="lazy" decoding="async" />
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

/** A two-column "what you want → what to run" table. */
export function TaskTable({ rows }: { rows: { task: string; run: string; href?: string }[] }) {
  return (
    <div className="docs-table" tabIndex={0}><table className="docs-tasks">
      <thead>
        <tr>
          <th>You want to</th>
          <th>Run</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.task}>
            <td>{row.href ? <Link href={row.href}>{row.task}</Link> : row.task}</td>
            <td>
              <code>{row.run}</code>
            </td>
          </tr>
        ))}
      </tbody>
    </table></div>
  );
}

/**
 * A grid of linked cards: the choices on an overview page ("pick your stack", "what next").
 * Each card is a title and one line.
 */
export function Cards({ items }: { items: { href: string; title: string; text: string }[] }) {
  return (
    <ul className="docs-cards">
      {items.map((item) => (
        <li key={item.href}>
          <Link href={item.href}>
            <strong>{item.title}</strong>
            <span>{item.text}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
