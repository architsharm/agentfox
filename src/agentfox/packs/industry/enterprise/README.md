# industry/enterprise

General enterprise and SaaS agents: blocks file deletion, code execution and SSH, holds file writes, email and deploys for approval, and blocks SSN-shaped numbers.

**Status.** Incubating, and every policy starts in **observe**: it records what it would
have done and blocks nothing. Simulate it against your traffic, then promote the
policies you want (`agentfox policy enforce <key>`). These are starter rules translated
from community policy examples, not a compliance certification; review them with
someone qualified before relying on them.

**What it ships.** 1 policy, 7 rules:

| Policy | Covers | Source file | Rules |
|---|---|---|---|
| `policies/industry-enterprise.yaml` | Enterprise | `enterprise.rego` | 7 |

`checks/rules.py` holds the translated conditions as a rule table that raises one risk
code per rule; each policy rule turns its code into an effect with `action_risk`.
Rules that test only a single tool name are plain `tool:` conditions instead (6 of them). `cases/golden.yaml` fires every rule once.

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

- `industry-enterprise`, "Tool call budget exceeded (50)": reads the run's tool-call count from the request envelope (`envelope.budgets.tool_call_count`); AgentFox's policy input carries a budget verdict (`budget_exceeded`), not a raw count, so the threshold cannot be expressed. Set an agent budget instead.

- The source profile's **default deny** and its **allow-list** (for example `read_*`,
  `search_*`, `lookup_*`): not carried. A pack's default effect applies to every event
  on every surface, so a default of block would block every ordinary message, not only
  unlisted tools; and an allow rule cannot lower another rule's effect in AgentFox.
  Restrict which tools an agent may call with capability grants instead.

## Origin and license

Translated from `examples/policies/production/` in https://github.com/microsoft/agent-governance-toolkit at commit `c767f83`.
Copyright (c) Microsoft Corporation, MIT License; the full text is in
`THIRD_PARTY_NOTICES.md`. Each policy file and `checks/rules.py` names its source file.

```bash
agentfox policy packs test industry/enterprise
```
