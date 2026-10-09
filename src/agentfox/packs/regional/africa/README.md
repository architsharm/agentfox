# regional/africa

Data protection rules for Egypt, Ethiopia, Ghana, Kenya, Mauritius, Nigeria (NDPA, CBN, NFIU, BVN/NIN, POS), Rwanda, South Africa, Tanzania and Uganda, plus five general agent controls.

**Status.** Incubating, and every policy starts in **observe**: it records what it would
have done and blocks nothing. Simulate it against your traffic, then promote the
policies you want (`agentfox policy enforce <key>`). These are starter rules translated
from community policy examples, not a compliance certification; review them with
someone qualified before relying on them.

**What it ships.** 19 policies, 211 rules:

| Policy | Covers | Source file | Rules |
|---|---|---|---|
| `policies/africa-human-approval.yaml` | Human approval for high-risk actions | `agent-human-approval.rego` | 4 |
| `policies/africa-model-routing.yaml` | Model routing for sensitive tasks | `agent-model-routing.rego` | 3 |
| `policies/africa-pii-leakage.yaml` | Personal data in agent output | `agent-pii-leakage.rego` | 6 |
| `policies/africa-prompt-injection.yaml` | Injection phrases in tool arguments | `agent-prompt-injection.rego` | 2 |
| `policies/africa-tool-permissions.yaml` | Restricted tools | `agent-tool-permissions.rego` | 1 |
| `policies/nigeria-bvn-nin.yaml` | Nigeria BVN/NIN protection | `bvn-nin-protection.rego` | 19 |
| `policies/nigeria-cbn-limits.yaml` | Nigeria CBN transaction limits | `cbn-transaction-limits.rego` | 10 |
| `policies/egypt-pdpl.yaml` | Egypt PDPL 151/2020 | `egypt-pdpl.rego` | 18 |
| `policies/ethiopia-pdp.yaml` | Ethiopia PDP Proclamation 1321/2024 | `ethiopia-pdp.rego` | 15 |
| `policies/ghana-dpa.yaml` | Ghana Data Protection Act 843 | `ghana-dpa.rego` | 14 |
| `policies/kenya-dpa.yaml` | Kenya Data Protection Act 2019 | `kdpa-data-protection.rego` | 15 |
| `policies/mauritius-dpa.yaml` | Mauritius Data Protection Act 2017 | `mauritius-dpa.rego` | 17 |
| `policies/nigeria-ndpa.yaml` | Nigeria NDPA 2023 data residency | `ndpa-data-residency.rego` | 12 |
| `policies/nigeria-nfiu-aml.yaml` | Nigeria NFIU anti-money-laundering | `nfiu-aml.rego` | 11 |
| `policies/south-africa-popia.yaml` | South Africa POPIA | `popia-south-africa.rego` | 13 |
| `policies/nigeria-pos-geofencing.yaml` | Nigeria POS terminal geofencing | `pos-geofencing.rego` | 6 |
| `policies/rwanda-dpa.yaml` | Rwanda Law 058/2021 | `rwanda-dpa.rego` | 15 |
| `policies/tanzania-pdpa.yaml` | Tanzania PDPA 2022 | `tanzania-pdpa.rego` | 15 |
| `policies/uganda-dppa.yaml` | Uganda DPPA 2019 | `uganda-dppa.rego` | 15 |

`checks/rules.py` holds the translated conditions as a rule table that raises one risk
code per rule; each policy rule turns its code into an effect with `action_risk`.
`cases/golden.yaml` fires every rule once.

## How the translation maps

The source policies are Rego over an input of `action`, `params`, `output` and
`context`. In AgentFox:

| Source | AgentFox |
|---|---|
| `action` (tool name) and `params` | the tool key and its arguments, on `tool_args` |
| `output` | the message text, on `input` and `output`; `action` there is the surface name, as in the source |
| `context` | `evidence["context"]` when the caller supplies it, else empty |
| `deny` / `escalate` / `audit` | `block` / `escalate` / `allow` (fired and recorded, nothing withheld) |

Regular expressions are carried verbatim and run in ASCII mode, as RE2 does. Absent
values, `not`, typed equality and cross-type ordering follow Rego. The source
policies' own unit tests, where they ship any, run against the tables in
`tests/platform/packs/test_translated_packs.py`.

## Left out

Rules that could not be expressed exactly are left out rather than approximated:

- `africa-model-routing`, "Model routing denied: model '%v' is on the banned list": denies models on a banned list that is empty unless configured (`data.config.model_routing.banned_models`), so as shipped it never fires; deployment configuration is not carried.
- `africa-pii-leakage`, "PII leakage: custom high-sensitivity pattern detected in agent output — blocked": matches deployer-supplied patterns (`data.config.pii_leakage.extra_patterns`), none by default; deployment configuration is not carried.
- `africa-tool-permissions`, "Tool permission denied: '%v' is on the denied list — action blocked": denies tools on a deny list that is empty unless configured (`data.config.tool_permissions.denied`); deployment configuration is not carried. Use agent capability grants.
- `africa-tool-permissions`, "Tool permission denied: '%v' is not in the allowed tools list": allowlist mode, active only when `data.config.tool_permissions.allowed` is configured; deployment configuration is not carried. Use agent capability grants.

- Deployment configuration (`data.config.*`): `africa-human-approval`,
  `africa-model-routing`, `africa-pii-leakage`, `africa-prompt-injection` and
  `africa-tool-permissions` are carried with the source's default lists and
  thresholds; the overrides are not.
- The jurisdiction router (`jurisdiction-router.rego`), which picks policies from
  `context.customer_country`: not carried. Bind the policies for a jurisdiction to the
  agents that serve it.

## Origin and license

Translated from `examples/policies/african-regulatory/` in https://github.com/microsoft/agent-governance-toolkit at commit `c767f83`.
Copyright (c) Microsoft Corporation, MIT License; the full text is in
`THIRD_PARTY_NOTICES.md`. Each policy file and `checks/rules.py` names its source file.

```bash
agentfox policy packs test regional/africa
```
