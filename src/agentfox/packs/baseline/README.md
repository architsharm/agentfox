# baseline

Prompt injection, PII, secrets and safety on every surface. Not a property of a sector
or a jurisdiction, so it applies to every agent, and it is what protects a deployment
that has bound nothing (in observe).

**Risk.** An instruction hidden in user input or a retrieved document steers the
agent; personal data or a credential leaks through an answer or a tool call.

**What it ships.** `policies/baseline.yaml` (13 rules, observe), golden cases.

**Remediation.** Run it in observe, read what it would have done (`agentfox policy
simulate`), then `agentfox policy enforce baseline`.

```bash
agentfox policy packs show baseline
agentfox policy packs test baseline
```
