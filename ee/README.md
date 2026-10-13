# AgentFox Enterprise

Everything outside this directory (and `dashboard/ee/`) is the open core, Apache-2.0.
What is in here is **source-available** under the [Business Source License 1.1](LICENSE):

- you can read, modify and run it for development and testing;
- you can run it in production for **one workspace governing up to four agents**;
- anything larger, or offering it to others as a service, needs a commercial licence
  (support@nometria.com);
- **each version becomes Apache-2.0 three years after it is released.**

## What it adds

| Feature | What it is |
|---|---|
| `compliance` | Control status against EU AI Act, ISO 42001, SOC 2, NIST AI RMF, OWASP and MITRE ATLAS; reviews and sign-off; risk register and obligations; the board view |
| `evidence` | Auditor evidence packages: a signed zip with its own verifier |
| `monitoring` | Fleet monitoring of connected repositories, MCP servers and APIs, with Slack alerts |
| `access_checks` | Your own access control (RBAC service, OPA, Cedar) consulted before a tool call runs |

## How it plugs in

The open core never imports this package. It is found through the
`agentfox.extensions` entry point (or as `agentfox_ee` on the import path in a checkout)
and contributes routes, jobs, schedules, CLI commands and hooks through
`agentfox.core.extensions`. Without it, the open core runs on its own and the dashboard
leaves these areas out.

```bash
pip install agentfox ./ee      # or: PYTHONPATH=src:ee/src for a checkout
```
