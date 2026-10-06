# payments/refunds

Refunds and transfers as business rules.

**What it ships.**

- `vocabulary.tool_hints` and `vocabulary.roles`: the words the policy compiler
  (`agentfox policy compile`) maps to a tool (refund → `payments.refund`) and to an
  approver role (finance, manager, legal …). Without them every compiled threshold
  asks which tool it governs.
- `ladders/refund-approval.yaml`: "under $10 auto-approve, $10–100 verify, over $100
  needs finance", as a template. It governs nothing until applied:
  `agentfox policy rules apply src/agentfox/packs/payments/refunds/ladders/refund-approval.yaml`.
- `fixtures/world.yaml`: the payments desk of the demo world (the transfer and refund
  tools, the payments operations agent and its grants).
- Golden cases for the ladder, the compiler and the transfer containment.

**Risk.** A refund or a transfer approved above what anyone agreed, or sent to an
account that came out of a document.

```bash
agentfox policy packs test payments/refunds
```
