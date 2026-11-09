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
        <code>scripts/gen/docs_reference.py</code>. If it is on this page, it runs.
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
          With an account key configured (<code>agentfox login</code>, or{" "}
          <code>AGENTFOX_URL</code> and <code>AGENTFOX_API_KEY</code>), <code>findings</code>,{" "}
          <code>agents list</code>, <code>permit</code>, <code>declare</code>,{" "}
          <code>policy</code>, <code>report</code> and <code>test suites</code> read and write
          your account through its API, and each prints which it uses. Otherwise commands use
          the database in <code>AGENTFOX_STATE_DIR</code> (or{" "}
          <code>AGENTFOX_DATABASE_URL</code>, which also wins over a key;{" "}
          <code>AGENTFOX_LOCAL=1</code> does too). In a source checkout the default is the
          repository itself; set the variable to keep experiments out of it. See{" "}
          <Link href="/docs/reference/config">Configuration</Link>.
        </p>
      </Callout>

      <CliReference />
    </article>
  );
}
