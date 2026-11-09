/**
 * The product screenshots the docs use, in one place: a re-capture changes a file
 * under public/docs/screens/ and, if its size changed, one line here.
 *
 * width and height are the image's pixel size (PNGs are captured at 2x); <Screenshot> uses them to hold the
 * space while the image loads.
 */

export type Screen = { src: string; alt: string; width: number; height: number };

export const SCREENS = {
  setupKey: {
    src: "/docs/screens/setup-key.png",
    alt: "The Connect your first agent card. Step 1, Create a key, shows a new workspace key (masked here) with a copy button. Step 2 shows pip install -U agentfox and the agentfox init --key --server command with that key filled in.",
    width: 1280,
    height: 1382,
  },
  agentsArrive: {
    src: "/docs/screens/agents-arrive.png",
    alt: "Step 3 of the card after agentfox init reported in: Agents identified, billing and support-triage with 4 tools, and an Add 2 agents to AgentFox button.",
    width: 1280,
    height: 600,
  },
  initTerminal: {
    src: "/docs/screens/init-terminal.svg",
    alt: "Terminal output of agentfox init --key: the agents and tools it recognised, Connected, and the question Add one line to main.py so your app's calls show up in AgentFox? [Y/n].",
    width: 1238,
    height: 538,
  },
  scanTerminal: {
    src: "/docs/screens/scan-terminal.svg",
    alt: "Terminal output of agentfox scan: the agents it found by name, the tools they can reach, and a Next box that says agentfox up.",
    width: 1190,
    height: 904,
  },
  attackTest: {
    src: "/docs/screens/attack-test.png",
    alt: "An agent map with the attack test panel. Each attack set shows how many attacks got through with no guardrails and with the basic guardrails.",
    width: 2440,
    height: 1660,
  },
  activity: {
    src: "/docs/screens/activity.png",
    alt: "An agent's Activity tab listing runs recorded from the app, each with its checks and verdict.",
    width: 2440,
    height: 1660,
  },
  libraries: {
    src: "/docs/screens/libraries.png",
    alt: "Policies, Libraries tab: the Your rules card first, then the libraries that ship with AgentFox, each with where it is applied and whether it watches or blocks.",
    width: 2440,
    height: 960,
  },
  yourRules: {
    src: "/docs/screens/your-rules.png",
    alt: "The Your rules drawer: each rule you wrote, what it checks and what it would do, with Simulate and Add a rule buttons.",
    width: 1280,
    height: 1660,
  },
  agentMap: {
    src: "/docs/screens/agent-map.png",
    alt: "The Agents page: the project map with the user, each agent, its model, tools and data sources, and the guardrail on each line.",
    width: 2440,
    height: 1660,
  },
  sources: {
    src: "/docs/screens/sources.png",
    alt: "Settings, Connections: the gateway, GitHub, a hosted API, the SDK, coding agents and OpenTelemetry, each with its status and a setup button.",
    width: 2440,
    height: 1660,
  },
  agentAccess: {
    src: "/docs/screens/agent-access.png",
    alt: "An agent's Access tab: each tool it may call, with its limits and whether a person must approve it.",
    width: 2440,
    height: 1660,
  },
  approvals: {
    src: "/docs/screens/approvals.png",
    alt: "The Approvals page: a held tool call with the agent, the tool, its arguments, and Approve and Deny buttons.",
    width: 2440,
    height: 1660,
  },
  killSwitch: {
    src: "/docs/screens/kill-switch.png",
    alt: "The agent's Pause menu: Pause, which refuses calls while you investigate, and Stop, which does the same and records an incident.",
    width: 2440,
    height: 1660,
  },
  dataAccess: {
    src: "/docs/screens/data-access.png",
    alt: "Settings, Data access: the people and groups who call the agent, and which data each may see.",
    width: 2440,
    height: 1660,
  },
  policies: {
    src: "/docs/screens/policies.png",
    alt: "The Policies page, Applied rules: the rules on the selected agent, grouped by library, with what each would do and whether it watches or blocks.",
    width: 2440,
    height: 1660,
  },
  ruleDetail: {
    src: "/docs/screens/rule-detail.png",
    alt: "A library opened from Policies, Libraries: its rules, what each checks, what it would do, and a Simulate button.",
    width: 2440,
    height: 1660,
  },
  addRule: {
    src: "/docs/screens/add-rule.png",
    alt: "The New rule page: what do you want to do, with one card per kind of rule, from blocking words to applying a library.",
    width: 2440,
    height: 1660,
  },
  testing: {
    src: "/docs/screens/testing.png",
    alt: "Testing, Attack tests: run a test against an agent, its past runs, and the runs checked without a model.",
    width: 2440,
    height: 1660,
  },
  traces: {
    src: "/docs/screens/traces.png",
    alt: "Activity, Runs tab: recent runs with their agent, what was asked, the outcome and why.",
    width: 2440,
    height: 1660,
  },
  traceDetail: {
    src: "/docs/screens/trace-detail.png",
    alt: "One run: each step with the checks it went through and why it was blocked, with Adjust rule and Prevent this buttons.",
    width: 2440,
    height: 1660,
  },
  issues: {
    src: "/docs/screens/issues.png",
    alt: "The Issues page: what needs a person, by severity, each linked to the run that raised it.",
    width: 2440,
    height: 1660,
  },
  reports: {
    src: "/docs/screens/reports.png",
    alt: "Reports, Compliance: controls mapped to frameworks, with the evidence for each.",
    width: 2440,
    height: 1660,
  },
  integrations: {
    src: "/docs/screens/integrations.png",
    alt: "Settings, Alerts: a Slack webhook, monitors, and the SIEM export command.",
    width: 2440,
    height: 1660,
  },
  tryIt: {
    src: "/docs/screens/try-it.png",
    alt: "Testing, Try it: a prompt attack typed as a user message, and the result: allowed while watching, blocked with every rule blocking, with the two rules that matched.",
    width: 2440,
    height: 1660,
  },
  verifiedSources: {
    src: "/docs/screens/verified-sources.png",
    alt: "Settings, Verified sources: registered data sources with their tier, owner and freshness.",
    width: 2440,
    height: 1660,
  },
} satisfies Record<string, Screen>;
