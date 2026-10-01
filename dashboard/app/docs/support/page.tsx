import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Before you file an issue",
  description: "Commands to run before a GitHub issue, and what not to paste.",
  path: "/docs/support",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Help</p>
      <h1>Before you file</h1>
      <p>
        A report is likely to contain production data, and a GitHub issue is public.
        Do not paste real prompts, tool arguments, retrieved documents, or audit rows.
        Replace names, accounts, URLs, and secrets with obvious placeholders.
      </p>
      <h2>Run these first</h2>
      <pre>
        <code>{`agentfox doctor
agentfox version
agentfox policy list`}</code>
      </pre>
      <p>
        <code>doctor</code> grades the runtime configuration and the tool declarations.
        It also prints the lines that are about AgentFox itself: development
        authentication, and a detector that fails open on timeout. <code>version</code>{" "}
        is what every template asks for. The first line is enough, or the commit SHA
        from a clone. <code>policy list</code> prints which packs are bound, and whether
        each is in observe or enforce.
      </p>
      <p>
        A reduced reproduction with made-up values is enough. The command reference is{" "}
        <Link href="/docs/commands">Commands</Link>. What the product does not do yet is{" "}
        <Link href="/docs/limits">Limits</Link>.
      </p>
      <p>
        Where to send the report is on <Link href="/support">Support</Link>. A
        vulnerability goes through GitHub&apos;s private advisories, not a public issue.
      </p>
    </article>
  );
}
