# Architecture decision records

One file per decision that shapes the code and is expensive to reverse: what was decided, the
options that lost, and what follows from it. A record is never edited to say something new; a
later record supersedes it and says so in its status line.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-repository-structure.md) | One package in layers held by import-linter; `capabilities/`, `harnesses/`, `plugins/`, packs; the repository outside `src/`; what is deferred | Accepted, 2026-10-07 |
| [0002](0002-customer-authored-rules.md) | Customer rules are data plus a managed policy pack; end-user message and re-ask on the rule; per-workspace detectors; importers only plan | Accepted, 2026-10-08 |

## Writing one

Copy the shape of the newest record: **Status**, **Context**, **Decision**, **Consequences**,
**Alternatives considered**. Number it one past the last, name it after the decision rather than
the problem, and add it to the table above and to `plugins/shared/reference/docs-map.md` (Class A
covers `docs/adr/*.md`, so a new file needs no new row). Longer reasoning and the evidence behind a
record can live in `docs/design/` and be linked from it.
