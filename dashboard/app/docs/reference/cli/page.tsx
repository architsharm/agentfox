import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code } from "@/components/docs/blocks";
import { CliIndex, CliReference, RenamedTable } from "@/components/docs/reference";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "CLI reference",
  description: "Every agentfox command and option, generated from the CLI itself.",
  path: "/docs/reference/cli",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Reference</p>
      <h1>CLI reference</h1>
      <p className="docs-lede">
        Every command and option, generated from the CLI by{" "}
        <code>scripts/docs_reference.py</code>. If it is on this page, it runs.
      </p>

      <p>
        The commands are grouped the way the work goes: see what you have, watch it run,
        contain what it can do, prove it. <code>agentfox --help</code> prints the same
        panels, and every command takes <code>--help</code>. For walkthroughs that put
        these commands together, start with the <Link href="/docs/quickstart">Quickstart</Link>.
      </p>
      <Code>{`agentfox --help
agentfox scan --help`}</Code>

      <CliIndex />

      <Callout kind="note" title="Where state lives">
        <p>
          Commands that read or write state use the database in{" "}
          <code>AGENTFOX_STATE_DIR</code> (or <code>AGENTFOX_DATABASE_URL</code>). In a
          source checkout the default is the repository itself; set the variable to keep
          experiments out of it. See <Link href="/docs/reference/config">Configuration</Link>.
        </p>
      </Callout>

      <CliReference />

      <h2 id="renamed">Renamed commands</h2>
      <p>
        The CLI was consolidated. The old names still run, hidden from{" "}
        <code>--help</code>, so scripts and installed hooks keep working.
      </p>
      <RenamedTable />
    </article>
  );
}
