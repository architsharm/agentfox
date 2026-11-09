import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code } from "@/components/docs/blocks";
import { CliIndex, CliReference } from "@/components/docs/reference";
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
        <code>scripts/gen/docs_reference.py</code>. If it is on this page, it runs. Commands marked{" "}
        <strong>Enterprise</strong> need AgentFox Enterprise (Cloud or the self-hosted Enterprise
        stack); the open-source package lists them and says so when you run one.
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
          Commands that read or write local state use one database per
          installation, not per folder: <code>~/.agentfox/agentfox.db</code> (or{" "}
          <code>$XDG_DATA_HOME/agentfox/agentfox.db</code>). <code>AGENTFOX_STATE_DIR</code> or{" "}
          <code>AGENTFOX_DATABASE_URL</code> moves it; in a source checkout it is the repository
          root. The full table is in{" "}
          <Link href="/docs/reference/install#state">Install options</Link>.
        </p>
      </Callout>

      <CliReference />
    </article>
  );
}
