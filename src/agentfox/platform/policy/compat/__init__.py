"""Reading policies written in other formats.

`agent_governance` translates agent-governance rule YAML and policy manifests into
`PolicyDocument`s; `schema/` holds the published JSON Schemas manifests are checked
against (copied unmodified, MIT — see `schema/LICENSE`), and `schema_check` is the
validator. Everything here is pure: it plans, and the caller saves.
"""
