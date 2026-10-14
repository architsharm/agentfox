"""AgentFox Enterprise. Source-available under the Business Source License 1.1 (see
`ee/LICENSE`); each version becomes Apache-2.0 three years after release.

The open core finds this package through the ``agentfox.extensions`` entry point and
asks it for routes, jobs, schedules, CLI commands, MCP tools, hooks and services
(`agentfox.core.extensions`). Nothing in the open core imports it.
"""

from __future__ import annotations

from typing import Any

__version__ = "0.1.0"


class Enterprise:
    name = "enterprise"
    features = ("access_checks", "compliance", "evidence", "monitoring")

    def routers(self) -> list[Any]:
        from agentfox_ee import access_checks
        from agentfox_ee.compliance.routes import router as compliance
        from agentfox_ee.evidence.routes import router as evidence
        from agentfox_ee.monitoring.routes import router as monitoring

        return [*access_checks.routers(), compliance, evidence, monitoring]

    def jobs(self) -> dict[str, Any]:
        from agentfox_ee.compliance.jobs import recompute_compliance
        from agentfox_ee.evidence.routes import _run_evidence_package
        from agentfox_ee.monitoring.service import handle_job

        return {
            "compliance.recompute": recompute_compliance,
            "evidence.package": _run_evidence_package,
            "monitors.run": handle_job,
        }

    def schedules(self) -> list[dict[str, Any]]:
        from agentfox_ee import monitoring
        from agentfox_ee.compliance.jobs import SCHEDULES

        return [*SCHEDULES, *monitoring.SCHEDULES]

    def session_extensions(self) -> list[tuple[str, str]]:
        return [("agentfox_ee.monitoring.alerts:install", "monitor alerts")]

    def cli(self, app: Any) -> None:
        from agentfox_ee.compliance.cli import compliance_app
        from agentfox_ee.evidence.cli import evidence_app
        from agentfox_ee.monitoring.cli import monitors_app

        app.add_typer(evidence_app, name="evidence")
        app.add_typer(compliance_app, name="compliance")
        # `agentfox scan monitors …`, the scheduled counterpart of every scan.
        for group in app.registered_groups:
            if group.name == "scan":
                group.typer_instance.add_typer(monitors_app, name="monitors")

    def mcp_tools(self, tool_class: Any) -> dict[str, Any]:
        from agentfox_ee.compliance.mcp import mcp_tools

        return mcp_tools(tool_class)

    def hooks(self) -> dict[str, Any]:
        from agentfox_ee import access_checks

        return {"tool_call": access_checks.tool_call_hook}

    def services(self) -> dict[str, Any]:
        from agentfox_ee.compliance import compute_all, ensure_compliance_computed, posture
        from agentfox_ee.compliance.risk import assess
        from agentfox_ee.evidence.package import build
        from agentfox_ee.monitoring import alerts
        from agentfox_ee.monitoring.service import request_run, safe_ensure_monitor

        return {
            "compliance.compute": compute_all,
            "compliance.ensure": ensure_compliance_computed,
            "compliance.posture": posture,
            "risk.assess": assess,
            "evidence.build": build,
            "monitors.ensure": safe_ensure_monitor,
            "monitors.request_run": request_run,
            "alerts.wait_for_delivery": alerts.wait_for_delivery,
        }


def extension() -> Enterprise:
    return Enterprise()
