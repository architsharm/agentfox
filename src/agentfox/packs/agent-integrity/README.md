# agent-integrity

**The risk.** An agent does something its task never asked for (an agent told to
summarise a document moves money); a coding agent writes code that a reviewer would
reject (`shell=True`, `verify=False`, SQL built from strings); an answer states
something its retrieved context does not support.

**What it ships.** One policy, watching (`mode: observe`):

| Rule | Acts on | Default |
|---|---|---|
| `intent.misaligned` | the `intent.misaligned` risk from `judgment/checks.py` (a judge when one is enabled, a cautious word check otherwise) | Ask a human |
| `code.insecure` | `CODE.*` detections from `detectors/code.py` | Ask a human |
| `grounding.unsupported` | `GROUNDING.UNSUPPORTED` from the opt-in `grounding.nli` detector | Block, **re-asked** once on the model proxy |

**Remediation.** Review what each rule would have held on Policies → Performance, then
start enforcing. Turn on `grounding.nli` (Policies → Library → Detectors) once its model
is installed; without it the grounding rule never fires.

```bash
agentfox policy packs test agent-integrity
```
