---
name: tour-product
description: Runs a safe, offline tour of what AgentFox does, using a throwaway database so nothing the user owns changes. Use when someone asks "what does this do", "show me", "demo it", or is evaluating the product before adopting it.
---

# Tour the product

> Commands below are written as `agentfox …`. If `agentfox` isn't on PATH, see
> [Running the CLI](../../AGENTS.md#running-the-cli).

The goal is to show, not tell: the user watches a prompt injection get caught, a tainted
tool call get contained, and a tampered audit log get detected. Nothing touches their real
database, and nothing leaves the machine.

## 1. Set up an isolated scratch environment

```bash
export AGENTFOX_DATABASE_URL=sqlite:////tmp/agentfox-tour.db
export AGENTFOX_EVIDENCE_DIR=/tmp/agentfox-tour-evidence
agentfox admin version
```

If the launcher exits 127, the product isn't installed. Offer the install line it prints
and continue once it's installed.

## 2. First look at their own code (read-only, about 10 seconds)

```bash
agentfox scan --sessions . --skip-sessions
```

Summarise:

- which files call a model
- which calls are ungoverned
- how many of the live adversarial probes were caught

Keep `--skip-sessions` unless the user explicitly wants their local AI-tool transcripts
scanned. Never pass `--submit`.

## 3. The end-to-end walkthrough

The plugin's safety hook asks the user before `demo` runs, because it briefly promotes `baseline`
to enforce and writes demo data. That's expected; the database is the scratch one, and the
demo restores `baseline` to observe when it finishes.

```bash
agentfox demo
```

Narrate the steps as they print, one sentence each:

1. A normal call is allowed and traced.
2. An indirect injection in a retrieved document is detected, tainted and blocked.
3. The injection tries to move money with a tainted argument. It is contained by policy even
   though the text got through.
4. An unregistered agent appears. A shadow-agent finding is raised.
5. PII in an outbound response is redacted.
6. An eval suite catches a plausible but ungrounded answer, and the CI gate fails.
7. The audit chain is verified, tampered with, and the break is located.
8. An auditor evidence package is exported with a chain-of-custody manifest.

## 4. Let them poke at it

Offer two or three of these, based on what they reacted to:

```bash
agentfox findings
agentfox test action "DELETE FROM customers" --kind sql
agentfox policy rules suggest "refunds above 500 dollars need a manager"
agentfox test probes
agentfox report status --framework eu-ai-act
```

For the UI, the operate-deployment skill starts the gateway and dashboard.

## 5. Close

Tell the user:

- **What is theirs to keep:** nothing yet. The scratch DB is at `/tmp/agentfox-tour.db`, and
  deleting it undoes the tour.
- **The next step:** the onboard-codebase skill (`/agentfox:start`), which governs their
  real code in observe mode.
