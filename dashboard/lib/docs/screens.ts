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
    alt: "The Connect your first agent card. Step 1, Create a key, shows a new workspace key with a copy button. Step 2 shows the pip install and agentfox init --key command with that key filled in.",
    width: 1280,
    height: 1342,
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
    height: 782,
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
    alt: "The Your rules drawer: each rule you wrote with its surfaces and effect, business rules with their mode, and a Start blocking button.",
    width: 1280,
    height: 1800,
  },
} satisfies Record<string, Screen>;
