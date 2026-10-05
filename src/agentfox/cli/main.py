"""AgentFox CLI.

The commands a platform engineer runs (``eval gate``, ``policy simulate``) and the
commands a compliance lead runs (``compliance status``, ``evidence export``) are the
same binary against the same API. That is the land-and-expand path in PRD §4.3
expressed as a tool: the engineer installs it for CI, and the CISO finds their view
already there.
"""

from __future__ import annotations

import sys

import typer

from agentfox.cli.auth_cli import register as _register_auth
from agentfox.cli.business_cli import register as _register_business
from agentfox.cli.capability_cli import register as _register_capability
from agentfox.cli.commands import root
from agentfox.cli.commands.access import access_app
from agentfox.cli.commands.agents import agents_app
from agentfox.cli.commands.audit import audit_app, evidence_app
from agentfox.cli.commands.compliance import compliance_app
from agentfox.cli.commands.db import db_app
from agentfox.cli.commands.evals import eval_app
from agentfox.cli.commands.hooks import hooks_app
from agentfox.cli.commands.policy import policy_app
from agentfox.cli.commands.proposals import proposals_app
from agentfox.cli.commands.redteam import redteam_app
from agentfox.cli.commands.scan import scan_app
from agentfox.cli.commands.tools import tools_app
from agentfox.cli.controls_cli import register as _register_controls
from agentfox.cli.layout import apply_layout
from agentfox.cli.mcp_cli import register as _register_mcp
from agentfox.cli.onboarding import register as _register_onboarding
from agentfox.cli.quickscan import register as _register_quickscan
from agentfox.cli.report_cli import register as _register_report

app = typer.Typer(
    name="agentfox",
    help="Agent-native, vendor-neutral governance for AI agents in production.",
    no_args_is_help=True,
    add_completion=False,
)

# Registration order is the order Typer keeps, so it is kept as it always was.
app.add_typer(agents_app, name="agents")
app.add_typer(policy_app, name="policy")
app.add_typer(eval_app, name="eval")
app.add_typer(audit_app, name="audit")
app.add_typer(evidence_app, name="evidence")
app.add_typer(compliance_app, name="compliance")
app.add_typer(redteam_app, name="redteam")
app.add_typer(scan_app, name="scan")
app.add_typer(tools_app, name="tools")
app.add_typer(access_app, name="access")
app.add_typer(db_app, name="db")
app.add_typer(hooks_app, name="hooks")

# The three commands a new user runs, registered as top-level verbs. The rest of this
# CLI is right for an operator running a governance programme and wrong for the first
# ten minutes.
_register_onboarding(app)
_register_quickscan(app)
_register_auth(app)
_register_controls(app)
_register_business(app)
_register_mcp(app)
_register_capability(app)
_register_report(app)
root.register(app)

app.add_typer(proposals_app, name="proposals")

# The visible tree (Start · See · Watch · Contain · Prove · Operate) is a layer over
# everything registered above: new names for the same callbacks, old names hidden but
# still working. Keep this the last registration in the module.
apply_layout(app)


def main() -> None:  # pragma: no cover - console entry point
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
