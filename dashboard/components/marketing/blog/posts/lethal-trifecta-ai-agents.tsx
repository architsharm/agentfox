import Link from "next/link";

import type { TocItem } from "@/components/marketing/blog/article";
import { Diagram, InlineCTA, Takeaways, type FaqItem } from "@/components/marketing/blog/blocks";
import { Code, Output } from "@/components/docs/blocks";

export const toc: TocItem[] = [
  { id: "what-it-is", label: "What the lethal trifecta is" },
  { id: "why-reviews-miss-it", label: "Why tool-by-tool review misses it" },
  { id: "find-it", label: "Finding it in your own repo" },
  { id: "the-finding", label: "What a finding looks like" },
  { id: "breaking-it", label: "Breaking one leg" },
  { id: "honest-limits", label: "What the scan cannot tell you" },
];

export const faq: FaqItem[] = [
  {
    q: "What is the lethal trifecta?",
    a: "A term from Simon Willison for an agent that can do three things at once: read private data, take in content an attacker can write, and send data somewhere out. Each one is ordinary on its own. Together they mean an instruction hidden in a web page or an email can make the agent mail your data to a stranger.",
  },
  {
    q: "Why is each tool fine but the combination dangerous?",
    a: "Because the attacker supplies the missing piece. They cannot read your database and they cannot send your mail, but if your agent can do both and will also read a page they control, they only have to write the instruction. The agent does the rest with its own credentials.",
  },
  {
    q: "How do I check whether my agent has the trifecta?",
    a: "Run agentfox scan in the repository. It classifies every tool and MCP server it finds into the three flags and prints a sentence for any agent that holds all three. It is static and offline: MCP server configs are read, and the servers are never started.",
  },
  {
    q: "How do I fix it?",
    a: "Remove one leg for that agent. Split the work across two agents so no single one holds all three, drop the outbound tool it does not need, or contain the outbound call so it cannot carry arguments that came from untrusted content. Containing the outbound channel is usually the least disruptive of the three.",
  },
  {
    q: "Will the scan find every case?",
    a: "No. Classification is a name-and-description heuristic, so a tool whose name says nothing useful is left unflagged rather than guessed at, and an MCP server it does not recognise is reported as unknown rather than safe. It is a way to find the obvious cases quickly, not a proof that you have none.",
  },
];

export function Body() {
  return (
    <>
      <Takeaways
        items={[
          "Three capabilities that are each unremarkable become an exfiltration path when one agent holds all of them.",
          "Reviewing tools one at a time cannot find it, because every tool passes on its own. The combination is the finding.",
          "agentfox scan reads a repository offline and prints the sentence, naming which tool supplies which leg.",
        ]}
      />

      <h2 id="what-it-is">What the lethal trifecta is</h2>
      <p>
        The term is{" "}
        <a href="https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/" rel="noopener">
          Simon Willison&apos;s
        </a>
        . An agent is in trouble when it can do all three of these at once:
      </p>
      <ul>
        <li>Read private data. Customer records, files, an inbox, a database.</li>
        <li>
          Take in content somebody outside can author. Web pages, search results, incoming
          email, issue comments, a PDF a user uploaded.
        </li>
        <li>
          Send data out, or do something it cannot take back. Send, post, pay, refund, delete,
          write, run a shell command, make an outbound request.
        </li>
      </ul>
      <p>
        Hold one or two and the worst case is bounded. Hold all three and an attacker who can
        write a sentence into any page your agent reads can make it fetch your data and post
        it somewhere they control. They never touch your systems. The agent does it, with
        credentials you gave it, inside a session that looks normal in the logs.
      </p>

      <Diagram
        label="The three capabilities and the path between them"
        caption="Each circle is ordinary. The path only exists when one agent sits in all three, which is why the finding is about the agent and not about any tool."
      >
        <svg className="dg" viewBox="0 0 760 260" xmlns="http://www.w3.org/2000/svg">
          <circle cx="250" cy="110" r="90" className="dg-fill-muted" opacity="0.5" />
          <circle cx="380" cy="110" r="90" className="dg-fill-muted" opacity="0.5" />
          <circle cx="315" cy="175" r="90" className="dg-fill-muted" opacity="0.5" />
          <text x="195" y="70" textAnchor="middle" className="dg-strong">
            Private data
          </text>
          <text x="195" y="88" textAnchor="middle" className="dg-small">
            lookup_customer
          </text>
          <text x="440" y="70" textAnchor="middle" className="dg-strong">
            Untrusted input
          </text>
          <text x="440" y="88" textAnchor="middle" className="dg-small">
            fetch_url
          </text>
          <text x="315" y="238" textAnchor="middle" className="dg-strong">
            Way out
          </text>
          <text x="315" y="256" textAnchor="middle" className="dg-small">
            send_email
          </text>
          <circle cx="315" cy="132" r="9" className="dg-fill-stop" />
          <text x="560" y="128" className="dg-t-stop">
            All three in one agent
          </text>
          <text x="560" y="148" className="dg-small">
            is the finding
          </text>
        </svg>
      </Diagram>

      <h2 id="why-reviews-miss-it">Why tool-by-tool review misses it</h2>
      <p>
        Ask a reviewer whether <code>send_email</code> is a dangerous tool and they will say it
        depends. Ask about <code>fetch_url</code> and they will say it is a fetch.{" "}
        <code>lookup_customer</code> is the entire point of a support agent. Every tool clears
        review, because review happens one tool at a time and each one has an obvious
        justification.
      </p>
      <p>
        The risk is a property of the set. That is an awkward thing for a checklist to catch,
        and it is an easy thing for a scan to catch, which is most of why we built the scan
        this way.
      </p>

      <h2 id="find-it">Finding it in your own repo</h2>
      <p>
        The scan is static. It reads source and configuration, and it does not start anything.
        MCP server configs are read as files; the servers are never launched.
      </p>
      <Code lang="bash">{`pip install agentfox
agentfox scan`}</Code>
      <p>
        Add <code>--fail</code> to make it exit non-zero when it finds a trifecta, which is
        what you want in CI. <code>agentfox scan machine</code> does the same for the MCP
        servers and skills your own AI tools load on your laptop, which is a different set and
        often a more surprising one.
      </p>

      <h2 id="the-finding">What a finding looks like</h2>
      <p>
        The output is a sentence, not a list of tool names, because a list is not something a
        security owner can act on. It names which tool supplies which leg, and then says what
        the combination permits:
      </p>
      <Output>{`agents/support.py: can read customer data (lookup_customer), reads
web pages (fetch_url), and can send email (send_email). An instruction
hidden in a web page could send customer data out.`}</Output>
      <p>
        The tool names in the brackets are the evidence. The last line is the finding. If that
        sentence is wrong about your agent, the scan has mis-classified a tool and you can say
        so; if it is right, you have a decision to make about an agent that is probably already
        running.
      </p>

      <h2 id="breaking-it">Breaking one leg</h2>
      <p>
        You need to remove one of the three for that agent. In rough order of how disruptive
        they are:
      </p>
      <ul>
        <li>
          Drop the outbound tool, if the agent does not really need it. The cheapest fix and
          the rarest, because it usually does need it.
        </li>
        <li>
          Split the work. One agent reads untrusted content and summarises. A second agent,
          with no web access, acts on the summary. The attacker&apos;s text now has to survive
          a boundary that does not pass tool calls.
        </li>
        <li>
          Contain the outbound call. Keep all three tools, and refuse a{" "}
          <code>send_email</code> whose arguments carry values that came from untrusted
          content. This is what{" "}
          <Link href="/blog/prompt-injection-containment-not-detection">containment</Link> does,
          and it is usually the one teams pick, because nothing about the agent has to change.
        </li>
      </ul>
      <p>
        The scan suggests the third by default and names the tool to contain, since that is the
        one that makes the sentence true.
      </p>

      <h2 id="honest-limits">What the scan cannot tell you</h2>
      <p>
        Classification is a heuristic over names and descriptions. We chose that deliberately,
        because this has to run on a repository nobody has imported and a tool&apos;s name is
        usually the most honest description of it available. The consequences are worth stating
        plainly:
      </p>
      <ul>
        <li>
          A tool called <code>do_thing</code> tells the scan nothing, and it is left unflagged
          rather than guessed at. A clean report is not proof.
        </li>
        <li>
          An MCP server it does not recognise is reported as unknown, never as safe. You still
          have to look at it.
        </li>
        <li>
          It reads what the repository declares. A tool reached at runtime through a path the
          source does not name is outside what a static read can see.
        </li>
      </ul>
      <p>
        One more thing we decided early: the classifier does not reuse any benchmark&apos;s list
        of tool names. A scan that knows a benchmark&apos;s tools scores well on that benchmark
        and no better on yours, and we would rather have the second number.
      </p>

      <InlineCTA
        title="Check your own repo in about a minute"
        body="Static and offline. It reads source and MCP configs, starts nothing, and prints the agents that hold all three."
        href="/docs/concepts"
        label="Read the concepts"
        secondary={{ href: "/playground", label: "Try the playground" }}
      />
    </>
  );
}
