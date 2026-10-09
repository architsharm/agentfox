# Stock Rego and Cedar policy libraries

Reusable policy building blocks, kept as data. Nothing in AgentFox loads them at
request time; they are here so a team that writes its own Rego or Cedar beside
AgentFox's declarative policies has tested helpers to start from.

| Directory | What | Tests |
|---|---|---|
| `rego/` | 11 Rego library modules: approval gates, tool-call and token budgets, confidence floor, content-hash pinning, drift warning, egress allowlist, information-flow labels (two variants), PII patterns, redaction, and a default composition of all of them | each module has a sibling `*_test.rego`, run with `opa test rego/` |
| `cedar/` | the same gates written in Cedar (10 policies) | each policy has a sibling `*_test.json`, run with `cedar run-tests --policies X.cedar --tests X_test.json` |

`tests/platform/policy/test_stdlib.py` runs both suites when the `opa` or `cedar`
binary is on `PATH`, and skips them otherwise.

## How this relates to AgentFox's Rego export

AgentFox's own policies are declarative YAML (`platform/policy/model.py`).
`compile_to_rego` in `platform/policy/opa.py` compiles one of them to a
self-contained Rego module under `package agentfox.policy.<key>`, evaluated against
the input `OpaPolicyEngine._shape` builds (surface, tool, arguments, detections,
taint, capability, budget). The generated module does not import these libraries,
and these libraries do not read that input shape: they expect the input documented
in each file's header comment (an intervention point, a host snapshot and a policy
target).

So the two meet only where you write Rego by hand: copy or import a helper from
`rego/` into your own module, adapt the input paths to the AgentFox input, and keep
the helper's tests next to it. The package names (`agt.*`,
`agent_control_specification.lib.ifc`) and file names are the upstream ones,
unchanged, so the bundled tests keep passing as shipped.

## Origin and license

Copied unchanged from `policy-engine/policy/lib/` and `policy-engine/policy/cedar-lib/`
of https://github.com/microsoft/agent-governance-toolkit at commit c767f83, except for
a copyright header added to `rego/ifc.rego` and `rego/ifc_test.rego`, which shipped
without one. Copyright (c) Microsoft Corporation, MIT License: full text in `LICENSE`
in this directory and in `THIRD_PARTY_NOTICES.md`. The upstream test-runner scripts
and the Cedar directory's README were not copied.
