# eu-ai-act

The EU AI Act as runtime measures and data. An engineering interpretation, not legal
advice; it supports specific articles and does not make a system compliant.

**What it ships.**

- `policies/eu-ai-act-high-risk.yaml`: measures supporting Art. 5, 10, 12, 14, 15 and 50
  for agents classified high-risk (7 rules, observe).
- `vocabulary.condition_values.risk_tier`: the risk classes (prohibited, high, limited,
  minimal) the classifier emits and policy lint checks `risk_tier` conditions against.
- `vocabulary.annex_iii_cues` and `prohibited_cues`: the words the classifier
  (`capabilities/compliance/risk.py`) proposes a class from, for a person to confirm.
- `fallback`: on a deployment that has bound nothing, an agent declared `high` or
  `prohibited` gets this pack's policies beside baseline, in observe.

**Remediation.** Classify each agent (`agentfox report risk`), confirm the class, and
bind this pack to the high-risk ones.

```bash
agentfox policy packs test eu-ai-act
```
