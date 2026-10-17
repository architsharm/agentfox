# regional/india

DPDP Act, CERT-In Directions, RBI data localisation and KYC, SEBI CSCRF and Aadhaar rules for agents serving Indian customers.

**Status.** Incubating, and every policy starts in **observe**: it records what it would
have done and blocks nothing. Simulate it against your traffic, then promote the
policies you want (`agentfox policy enforce <key>`). These are starter rules translated
from community policy examples, not a compliance certification; review them with
someone qualified before relying on them.

**What it ships.** 5 policies, 23 rules:

| Policy | Covers | Source file | Rules |
|---|---|---|---|
| `policies/india-aadhaar.yaml` | Aadhaar Act s.29 and 2021 Regulations | `aadhaar-pii-protection.rego` | 5 |
| `policies/india-cert-in.yaml` | CERT-In Directions 2022 | `certin-2022-directions.rego` | 2 |
| `policies/india-dpdp.yaml` | DPDP Act 2023 and Rules 2025 | `dpdp-data-protection.rego` | 5 |
| `policies/india-rbi.yaml` | RBI payment data, KYC and IT governance | `rbi-data-localization.rego` | 5 |
| `policies/india-sebi.yaml` | SEBI CSCRF 2024 and AI/ML amendment | `sebi-governance.rego` | 6 |

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

- `india-cert-in`, "CERT-In 2022 Directions (iv): logs must be retained within India, configured region: '%v'": fires on every event that does not carry the parameter it tests, including every ordinary message and tool call (the source applies it at every intervention point, where the parameter is almost never present). Carried as written it would mark all traffic; narrowed to events that carry the parameter it would be a different rule.
- `india-cert-in`, "Direction (i): NTP clock sync - escalate if not synced": fires on every event that does not carry the parameter it tests, including every ordinary message and tool call (the source applies it at every intervention point, where the parameter is almost never present). Carried as written it would mark all traffic; narrowed to events that carry the parameter it would be a different rule.
- `india-sebi`, "SEBI CSCRF 2024: audit logs must be retained within India, configured region: '%v'": fires on every event that does not carry the parameter it tests, including every ordinary message and tool call (the source applies it at every intervention point, where the parameter is almost never present). Carried as written it would mark all traffic; narrowed to events that carry the parameter it would be a different rule.

- The jurisdiction router that selects these policies by `context.customer_country`:
  not carried. Bind the policies to the agents that serve Indian customers.

## Origin and license

Translated from `examples/policies/india-regulatory/` in https://github.com/microsoft/agent-governance-toolkit at commit `c767f83`.
Copyright (c) Microsoft Corporation, MIT License; the full text is in
`THIRD_PARTY_NOTICES.md`. Each policy file and `checks/rules.py` names its source file.

```bash
agentfox policy packs test regional/india
```
