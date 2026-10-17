# regional/uk

UK GDPR and DPA 2018, Arts. 22A-22D automated decision-making, and FCA Consumer Duty and SM&CR rules for agents serving UK customers.

**Status.** Incubating, and every policy starts in **observe**: it records what it would
have done and blocks nothing. Simulate it against your traffic, then promote the
policies you want (`agentfox policy enforce <key>`). These are starter rules translated
from community policy examples, not a compliance certification; review them with
someone qualified before relying on them.

**What it ships.** 3 policies, 33 rules:

| Policy | Covers | Source file | Rules |
|---|---|---|---|
| `policies/uk-fca-conduct.yaml` | FCA Consumer Duty, SM&CR and market conduct | `fca-financial-conduct.rego` | 7 |
| `policies/uk-automated-decisions.yaml` | UK GDPR Arts. 22A-22D automated decisions | `ico-automated-decisions.rego` | 10 |
| `policies/uk-gdpr.yaml` | UK GDPR and DPA 2018 | `uk-gdpr-data-protection.rego` | 16 |

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

- No individual rule.

- Deployment configuration (`data.config.*`): the source lets a deployer set a
  senior-manager approval flag (`uk-fca-conduct` autonomous trading), an adequacy list
  and a data-privacy-framework flag (`uk-gdpr` transfers). The rules are carried with
  the source's defaults (no approval, the default adequacy list, no framework
  certification); the configuration knobs are not.

## Origin and license

Translated from `examples/policies/uk-regulatory/` in https://github.com/microsoft/agent-governance-toolkit at commit `c767f83`.
Copyright (c) Microsoft Corporation, MIT License; the full text is in
`THIRD_PARTY_NOTICES.md`. Each policy file and `checks/rules.py` names its source file.

```bash
agentfox policy packs test regional/uk
```
