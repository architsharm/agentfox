---
name: red-team
description: Runs AgentFox's adversarial probe suite (22 OWASP-LLM and MITRE-ATLAS-mapped probes) against an agent's real capability grants and policy bindings. It explains recall and precision, turns misses into policy fixes and re-runs to prove them. Use for "red-team my agent", "pentest the agent", "is it vulnerable to prompt injection", or /agentfox:redteam.
---

# Red team

> Commands below are written as `agentfox …`. If `agentfox` isn't on PATH, see
> [Running the CLI](../../AGENTS.md#running-the-cli).

## 1. Scope

- **Pick the agent:** confirm the slug with `agentfox agents list`. Probes run against the
  agent's *registered* grants and the policies bound to it, so a registration with no
  declared tools gives an optimistic result. Say so when it applies.
- **Choose the database:** probes create a campaign and findings in whichever DB
  `NOMETRIA_DATABASE_URL` points at. If the user doesn't want them in their real queue, use
  a scratch DB and `agentfox admin seed` there.

## 2. See the probes, then run them

```bash
agentfox test probes
agentfox test redteam <agent>
agentfox test redteam <agent> --probes <id1>,<id2>
```

Use `--probes` to re-run just the probes that failed.

## 3. Read the result correctly

- **Recall** is the share of adversarial probes that were stopped. A miss means an attack got
  through, and it becomes a `redteam` finding.
- **Precision** is the share of blocks that were real attacks. A benign probe being blocked is a
  `redteam_over_block` finding. That is a usability cost, not a security win.
- **Mode matters.** In observe mode, "stopped" means `effective_verdict`. Say whether the
  agent is actually protected today or only would be once enforcement is on.
- **Some misses are correct by design.** For example, a stricter EU AI Act Art. 14 policy
  demands human sign-off regardless. Check the rule that fired before calling it a bug.

## 4. Fix loop

For each miss, name the probe, the attack class and the surface. Then choose the smallest
fix:

| Miss type | Usual fix |
|---|---|
| injection in retrieved/tool content | make sure the agent marks that content untrusted (SDK `s.retrieved()`, LangGraph `retrieval_node`), so taint rules apply |
| tainted argument reached a high-impact tool | declare the tool's `impact` correctly; `tool-containment` handles the rest |
| capability abuse | tighten the identity's capability grants (`POST /api/identities/{id}/capabilities`) |
| content category | add a policy rule (**author-policy**), then simulate |

After the fix, re-run only the failed probes, then the full suite. Report the before and after
numbers in a table.

## 5. Deeper runners (optional)

`redteam probes` also lists wrapped runners (Garak, PyRIT) if the `[redteam]` extra is
installed. They need a real model and `NOMETRIA_ALLOW_EGRESS=true`. Ask before using them.
