# tool-containment

What an agent may do with a tool call, decided from where its arguments came from and
what the tool can do, not from whether a detector recognised the payload. The one pack
that ships in enforce.

**Risk.** A recipient, an account or an amount copied out of a document or a tool
result reaches an irreversible tool; a tool nobody declared is called; a loop runs away.

**What it ships.** `policies/tool-containment.yaml` (25 rules, enforce, fail closed),
golden cases.

**Remediation.** Declare tools with their real impact (`agentfox declare tool`) and
grant only what each agent needs (`agentfox permit grant`).

```bash
agentfox policy packs test tool-containment
```
