# Policy-manifest JSON schemas (compatibility data)

JSON Schemas (draft 2020-12) describing an external agent-policy manifest format and
its wire messages. They are here as data for the importer that converts those
manifests into AgentFox policies; AgentFox's own policy format does not use them.

| File | Describes |
|---|---|
| `manifest.schema.json` | a policy manifest: metadata, policies, intervention points |
| `approval.schema.json` | the manifest's approval section |
| `cedar_advice.schema.json` | advice objects returned by Cedar policies |
| `wire/*.schema.json` | snapshot, policy input, verdict, effect, request and result messages (see `wire/README.md`) |

## Origin and license

Copied unchanged from `policy-engine/spec/schema/` of
https://github.com/microsoft/agent-governance-toolkit at commit c767f83 (a copyright
comment was added to `wire/README.md`). Copyright (c) Microsoft Corporation, MIT
License: full text in `LICENSE` in this directory and in `THIRD_PARTY_NOTICES.md`.
JSON has no comment syntax, so the schema files carry the notice through that
`LICENSE` file rather than a header.
