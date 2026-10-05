/**
 * Building blocks for the docs pages. Every page under /docs uses these rather than
 * hand-rolled markup, so a code block, a warning and a numbered walkthrough look the
 * same everywhere.
 *
 * Commands inside <Code> are checked in CI: scripts/docs_reference.py --check resolves
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
      <pre>
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

/** A numbered walkthrough. Each <Step> is one thing the reader does. */
export function Steps({ children }: { children: ReactNode }) {
  return <ol className="docs-steps">{children}</ol>;
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
            {item.why && <span> — {item.why}</span>}
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** A two-column "what you want → what to run" table. */
export function TaskTable({ rows }: { rows: { task: string; run: string; href?: string }[] }) {
  return (
    <table className="docs-tasks">
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
    </table>
  );
}
