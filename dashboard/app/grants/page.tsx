import type { Metadata } from "next";

import { CapabilityPage } from "@/components/marketing/capability";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Access control for agent tool calls",
  description:
    "You write down what each agent is allowed to do before it runs. A prompt cannot add to that.",
  path: "/grants",
});

/** Both ladders are ordered least to most dangerous, and both come straight
 *  from the engine — `models.py` for impact, `guardrails/base.py` for taint. */
const IMPACT = [
  { k: "read", what: "Returns something. Changes nothing." },
  { k: "write", what: "Changes state that can be changed back." },
  { k: "high_impact", what: "Wide blast radius, or spawns something with its own tools." },
  { k: "irreversible", what: "Money moved, data deleted, mail sent. No undo." },
] as const;

const TAINT = [
  { k: "none", what: "Constant, from your own code." },
  { k: "user", what: "The operator typed it." },
  { k: "retrieved", what: "It came out of a document." },
  { k: "tool_result", what: "A tool returned it. A third party wrote it." },
  { k: "subagent", what: "Another agent asserted it." },
  { k: "memory", what: "It was written to memory earlier, by something." },
] as const;

export default function Page() {
  return (
    <CapabilityPage
      kicker="Access control"
      title={["What each agent", "is allowed to do"]}
      lede="You write that down before the agent runs. A prompt cannot add to it."
      docs="/docs/access"
      challenge={
        <p>
          Text filters have to guess whether a string is an attack, and an attacker
          gets a new try every request. Asking whether the agent was ever allowed to
          do this does not depend on how the request was worded.
        </p>
      }
      feature={{
        title: "What the tool can do, and where the argument came from",
        lede: "A call is judged on both. How dangerous the tool is, and whether a document supplied the value.",
        body: (
          <div className="ladders mk-stagger">
            <div className="ladder">
              <p className="mk-label">Tool impact</p>
              <ol>
                {IMPACT.map((r) => (
                  <li key={r.k}>
                    <code>{r.k}</code>
                    <span>{r.what}</span>
                  </li>
                ))}
              </ol>
            </div>
            <div className="ladder">
              <p className="mk-label">Argument taint</p>
              <ol>
                {TAINT.map((r) => (
                  <li key={r.k}>
                    <code>{r.k}</code>
                    <span>{r.what}</span>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        ) }}
      steps={[
        {
          title: "Declare what each tool actually does",
          body: (
            <p>
              A tool is <code>read</code>, <code>write</code>, <code>high_impact</code>{" "}
              or <code>irreversible</code>. That is the floor for what a call can be
              reasoned about as — and for a shell tool it really is only the floor,
              because <code>ls</code> and <code>rm -rf</code> are               the same tool.
            </p>
          ),
        },
        {
          title: "Grant the capability, with its limits",
          body: (
            <p>
              A grant carries constraints — a value ceiling, an environment, a maximum
              taint for the data that may reach it. Anything not granted is refused;
              that is the default, not a rule somebody has to remember to write.
            </p>
          ),
        },
        {
          title: "Track where each argument came from",
          body: (
            <p>
              Arguments are tainted by origin: something the operator typed, something a
              document said, something a tool returned. A transfer whose amount came out
              of a retrieved page is a different call from one the user asked for, and
              the record says which it was.
            </p>
          ),
        },
        {
          title: "Untrusted content may fill a value, never choose an action",
          body: (
            <p>
              This is the line the whole model rests on. A retrieved document can supply
              an account number that then gets checked; it cannot decide that a transfer
              is the next step. Control flow belongs to the operator&rsquo;s intent, and
              data belongs to the data.
            </p>
          ),
        },
        {
          title: "Read the chain, not only the step",
          body: (
            <p>
              Two harmless calls can compose into a privilege escalation, and a
              destructive action is often reached rather than requested. Cascades,
              blast radius and loops are evaluated across the run, so an outcome nobody
              asked for in one step is still caught.
            </p>
          ),
        },
      ]}
      gaps={{
        title: "What grants do not do",
        body: (
          <p>
            A grant is only as good as the declaration behind it, and the impact we infer
            for an undeclared tool is a guess we label as one. We also cannot bound what
            a tool does on the other side of its own API: if a tool you declared as a
            read deletes something, containment believed you.
          </p>
        ) }}
      related={["/runtime", "/discovery", "/control-points"]}
    />
  );
}
