"""FastAPI application — inline gateway + control-plane API.

One process serves both surfaces, which is a deployment choice rather than an
architectural one: it keeps the self-host story to a single container (NFR-4, X-8),
and the gateway is stateless so it scales out horizontally (NFR-3).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__
from ..availability import (
    check_services,
    get_admission_controller,
    observe_governed_request,
    service_health,
)
from ..compliance.catalog import load_catalog
from ..config import get_settings
from ..db import init_db
from ..guardrails import all_detectors, available_detectors
from ..providers import all_providers, available_providers
from .deps import current_user, db
from .routes import (
    answerability,
    discovery,
    entitlement,
    escalation,
    evaluation,
    governance,
    inline,
    integrations,
    jobs,
    memory,
    messaging,
    onboarding,
    playground,
    policy,
    proposals,
    provenance,
    registry,
    tuning,
    waitlist,
)

log = logging.getLogger(__name__)


def _load_demo_fixtures() -> None:
    """Re-register the offline provider's scripted replies when a seeded DB is present.

    Purely a demo affordance, and scoped to exactly that: the scripts live in the
    `echo` provider's process memory, so a server started after `agentfox seed` would
    otherwise lose them and the walkthrough would not reproduce over HTTP. Guarded on
    the seeded suite existing so a real deployment never picks up fixture text.
    """
    try:
        from sqlalchemy import select

        from ..db import session_scope
        from ..models import EvalSuite
        from ..seed import register_scripts

        with session_scope() as session:
            if session.scalar(select(EvalSuite).where(EvalSuite.key == "support-quality")):
                register_scripts()
                log.info("demo fixtures detected — offline provider scripts registered")
    except Exception as exc:  # never let a fixture concern break startup
        log.debug("demo fixture load skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _load_demo_fixtures()
    settings = get_settings()
    log.info(
        "AgentFox %s starting — provider=%s policy_engine=%s mode=%s egress=%s",
        __version__,
        settings.default_provider,
        settings.policy_engine,
        settings.default_policy_mode,
        settings.allow_egress,
    )
    # Pay any model-loading cost now, off the request path — a classifier detector
    # that only gets slow once, on its very first call, would otherwise silently
    # degrade the first real request every time this process starts (P3-6's 40ms
    # per-detector timeout is nowhere near enough to also cover loading a model).
    from ..guardrails import warm_all

    warm_all()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgentFox Control Plane",
        version=__version__,
        description=(
            "Agent-native, vendor-neutral governance, security and compliance for AI "
            "agents in production. Inline enforcement under /v1, control plane under /api."
        ),
        lifespan=lifespan,
    )

    # The dashboard is a client of this API (X-5). In self-host it is same-origin or
    # localhost; nothing here opens the control plane to the internet by itself.
    # The public playground page is the one deliberate exception — it is designed
    # to be called cross-origin, unauthenticated, from wherever it's hosted, so its
    # origin is additive here via NOMETRIA_PLAYGROUND_CORS_ORIGIN rather than
    # widening this list's intent for every other route.
    cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    cors_origins.extend(get_settings().playground_cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Nometria-Trace",
            "X-Nometria-Verdict",
            "X-Nometria-Effective-Verdict",
            # Same two values under names that say which one took effect:
            # applied = what happened, would-be = the counterfactual. See
            # gateway/verdicts.py.
            "X-Nometria-Applied-Verdict",
            "X-Nometria-Would-Be-Verdict",
            "X-Nometria-Decision",
            "X-Nometria-Mode",
            "X-Nometria-Latency-Ms",
        ],
    )

    @app.middleware("http")
    async def degradation_gate(request: Request, call_next):
        """Gap 0.7 — fail-open/closed per *service*, and never silently.

        `fail_mode` was only ever consulted per detector: one detector timed out, so
        this one request went unchecked. That is the wrong granularity for the failure
        that actually matters. When the detector pipeline as a whole has nothing to
        run, the policy engine's OPA sidecar is unreachable (`policy/store.py` quietly
        substitutes the native engine), the database is refusing connections, or the
        configured model provider is gone, *every* request is ungoverned — and the
        deployment reports 200s throughout, which is precisely the indistinguishable-
        from-working failure `availability.py`'s docstring refuses to accept.

        So: probe the dependencies, run the operator's declared `FailPolicy`, and put
        the answer where it can be seen. Fail-closed refuses here rather than admitting
        an ungoverned request; fail-open serves it but records it and stamps the
        response, and converts to closed once the degradation outlasts its budget.
        Scoped to ``/v1/*`` for the same reason as the admission gate below: ``/api/*``
        is the operator control plane, and an operator diagnosing an outage must not be
        locked out by the outage.
        """
        if not request.url.path.startswith("/v1/"):
            return await call_next(request)

        # Counted before the verdict so the ledger's denominator includes the healthy
        # traffic — five degraded requests out of five is an outage, five out of fifty
        # thousand is a blip, and a fraction over failures alone cannot tell them apart.
        observe_governed_request()
        events = check_services()
        blocking = [e for e in events if e.verdict == "block"]
        if blocking:
            event = blocking[0]
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "type": "agentfox_service_degraded",
                        "message": event.reason,
                        "service": event.control,
                        "detail": event.error,
                        "escalated": event.escalated,
                        "fail_mode": get_settings().fail_mode,
                        "degraded_services": sorted({e.control for e in blocking}),
                    }
                },
                headers={
                    "Retry-After": "5",
                    "X-Nometria-Degraded": ",".join(sorted({e.control for e in blocking})),
                },
            )

        response = await call_next(request)
        if events:
            # The request was served without a dependency the governance layer needed.
            # A caller that gets a 200 back deserves to know that much without going
            # and reading someone else's logs.
            response.headers["X-Nometria-Degraded"] = ",".join(sorted({e.control for e in events}))
        return response

    @app.middleware("http")
    async def admission_gate(request: Request, call_next):
        """P15-6 — shed load before it reaches governance, never after.

        Scoped to ``/v1/*``, the inline surface an agent actually calls under load;
        ``/api/*`` is the operator control plane, low-volume by nature and already
        outside what this admission budget is sized for. This runs ahead of
        routing, so a shed request never reaches `Enforcer` — under saturation the
        thing to drop is work, not the checks on the work that gets through
        (`availability.py`'s module docstring).
        """
        if not request.url.path.startswith("/v1/"):
            return await call_next(request)

        controller = get_admission_controller()
        priority = request.headers.get("X-Nometria-Priority", "normal")
        admission = controller.admit(scope="inline", priority=priority)
        if not admission.admitted:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "type": "agentfox_admission_shed",
                        "message": admission.reason,
                        "retry_after_seconds": admission.retry_after_seconds,
                    }
                },
                headers={"Retry-After": str(max(1, round(admission.retry_after_seconds)))},
            )
        controller.enter()
        try:
            return await call_next(request)
        finally:
            controller.leave()

    app.include_router(inline.router)
    app.include_router(registry.router)
    app.include_router(policy.router)
    app.include_router(evaluation.router)
    app.include_router(governance.router)
    app.include_router(tuning.router)
    app.include_router(escalation.router)
    app.include_router(answerability.router)
    app.include_router(onboarding.router)
    app.include_router(provenance.router)
    app.include_router(entitlement.router)
    app.include_router(integrations.router)
    app.include_router(jobs.router)
    app.include_router(discovery.router)
    app.include_router(memory.router)
    app.include_router(messaging.router)
    app.include_router(proposals.router)
    # Unauthenticated by design (see playground.py's module docstring) — the only
    # router in this app that never depends on `current_user`. It keeps no state in
    # this process: a sandbox is a tenant in the deployment database, so any instance
    # can serve any sandbox and NFR-3 still holds.
    app.include_router(playground.router)
    # Also unauthenticated by design, and for a plainer reason than the playground's:
    # joining a waitlist is what someone does *before* they have an account to sign in
    # with. It writes one row to the one table that holds no tenant's data, and calls
    # nothing — see waitlist.py's module docstring for what keeps a public write safe.
    app.include_router(waitlist.router)

    def _health_payload() -> dict[str, Any]:
        degradation = service_health()
        return {
            "status": "ok",
            "version": __version__,
            "governance_healthy": degradation.get("healthy"),
            "degradation": degradation,
        }

    @app.get("/", tags=["platform"], summary="Service root")
    def root() -> dict[str, Any]:
        """Name the service and say where to go next. Unauthenticated.

        Added because `GET /` and `GET /health` both returned `{"detail":"Not Found"}`
        on the deployed API while only `/api/health` worked, which reads as a dead host
        to anyone checking by hand or with a default uptime probe.

        It reports the product name, the running version, and paths. It reports no
        configuration: not the database, the provider, the policy mode, the fail mode,
        the enabled detectors or any credential. Reaching this route proves the process
        is up and serving HTTP and nothing more — it runs no dependency check, so a 200
        here does not mean the database or the detectors are healthy. `/api/health`
        answers that.
        """
        return {
            "service": "agentfox",
            "description": (
                "Governance, security and compliance for AI agents. Inline enforcement "
                "under /v1, control plane under /api."
            ),
            "version": __version__,
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": "/api/health",
            "metrics": "/metrics",
        }

    @app.get("/health", tags=["platform"], summary="Health")
    def health_alias() -> dict[str, Any]:
        """The same payload as `/api/health`, at the path probes default to.

        An alias, not a second implementation: both call the same function, so the two
        cannot drift apart and report different things about one process.
        """
        return _health_payload()

    # `summary` pinned so the docstring below does not rewrite this route's label in
    # the generated Appendix C table (scripts/api_routes.py) — the explanation belongs
    # in the description, and the public summary of this route has not changed.
    @app.get("/api/health", tags=["platform"], summary="Health")
    def health() -> dict[str, Any]:
        """Liveness, plus what is currently not being checked (gap 0.7).

        `status` stays "ok" for a process that is up and serving — that is what every
        liveness probe already pointed at this route means by it, and changing it would
        start restarting healthy containers. What a fail-open deployment needs *on top*
        is `governance_healthy`: a fail-open system reports success while checking
        nothing, so a 200 here is exactly the signal that cannot tell a working control
        from an absent one.
        """
        return _health_payload()

    @app.get("/api/version", tags=["platform"])
    def version() -> dict[str, Any]:
        """Every version that participates in a decision (X-4 determinism)."""
        settings = get_settings()
        catalog = load_catalog()
        return {
            "code_version": __version__,
            "catalog_version": catalog.get("version"),
            "catalog_review_status": catalog.get("review_status"),
            "policy_engine": settings.policy_engine,
            "default_provider": settings.default_provider,
            "default_policy_mode": settings.default_policy_mode,
            "fail_mode": settings.fail_mode,
            "enforcement_budget_ms": settings.enforcement_budget_ms,
            "detector_versions": {k: d.version for k, d in all_detectors().items()},
            "egress_allowed": settings.allow_egress,
        }

    @app.post("/api/_migrate_policy_canaries", tags=["platform"])
    def migrate_policy_canaries(
        session: Session = Depends(db), user=Depends(current_user)
    ) -> dict[str, Any]:
        """One-off: apply migration a1b2c3d4e5f6 (policy_canaries, P12-6) directly —
        the deployed wheel does not bundle migrations/, so this stands in for
        `alembic upgrade head` for this table. Idempotent; safe to remove once run.

        Owner-only: runs raw DDL against production.
        """
        if user.role != "owner":
            raise HTTPException(403, "owner role required to run a schema migration")
        from sqlalchemy import text

        session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS policy_canaries (
                    id VARCHAR(40) NOT NULL PRIMARY KEY,
                    policy_id VARCHAR(40) NOT NULL,
                    stable_version_id VARCHAR(40) NOT NULL,
                    candidate_version_id VARCHAR(40) NOT NULL,
                    steps JSON NOT NULL,
                    step_index INTEGER NOT NULL,
                    percent INTEGER NOT NULL,
                    status VARCHAR(16) NOT NULL,
                    max_block_rate_delta FLOAT NOT NULL,
                    min_sample INTEGER NOT NULL,
                    started_by VARCHAR(120),
                    rollback_reason TEXT NOT NULL,
                    completed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    org_id VARCHAR(64) NOT NULL
                )
                """
            )
        )
        session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_policy_canaries_policy_id "
                "ON policy_canaries (policy_id)"
            )
        )
        session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_policy_canaries_status "
                "ON policy_canaries (status)"
            )
        )
        session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_policy_canaries_org_id "
                "ON policy_canaries (org_id)"
            )
        )
        session.commit()

        result = session.execute(text("UPDATE alembic_version SET version_num = 'a1b2c3d4e5f6'"))
        if result.rowcount == 0:
            session.execute(text("INSERT INTO alembic_version (version_num) VALUES ('a1b2c3d4e5f6')"))
        session.commit()

        return {"migrated": True}

    @app.get("/api/detectors", tags=["platform"])
    def detectors(session: Session = Depends(db), _u=Depends(current_user)) -> dict[str, Any]:
        """P3-11 — which detectors exist, which are live, and how fast they are."""
        from sqlalchemy import func, select

        from ..models import DetectorRun

        stats: dict[str, dict[str, Any]] = {}
        rows = session.execute(
            select(
                DetectorRun.detector_key,
                func.count(),
                func.avg(DetectorRun.duration_ms),
                func.max(DetectorRun.duration_ms),
            ).group_by(DetectorRun.detector_key)
        ).all()
        for key, count, avg_ms, max_ms in rows:
            stats[key] = {
                "runs": int(count),
                "avg_ms": round(float(avg_ms or 0), 3),
                "max_ms": round(float(max_ms or 0), 3),
            }

        available = available_detectors()
        # Why the OSS-wrapped and licence-restricted detectors aren't live here —
        # shown in the UI so "not installed" doesn't read as a bug. The native
        # detectors (injection.heuristic, pii.native, safety.lexicon, schema.json,
        # secrets.native) need none of this and are always available.
        unavailable_reason = {
            # pii.presidio answers for itself too, and has to: this said it was
            # "available in the self-hosted docker-compose deployment", which is
            # only true where its 400MB spaCy model has also been provisioned —
            # and getting that wrong is what the detector's own reason exists to
            # explain. It also named the wrong extra (`[presidio]`, not `[pii]`).
            # rails.nemo and rails.guardrails_ai answer for themselves now that
            # they can actually be turned on: their reason names the setting to
            # set and distinguishes "not installed" from "installed, nothing
            # configured" from "configured, but it did not load". A fixed
            # sentence here could say none of that.
            "safety.granite": (
                "Wrapped IBM Granite Guardian, via transformers — needs the model "
                "weights downloaded ahead of time (never fetched at request time); "
                "not present in this deployment's function image."
            ),
            "safety.restricted": (
                "Meta Llama Guard / Google ShieldGemma — capable, but their licences "
                "aren't OSI-approved (usage restrictions, a MAU clause), so this stays "
                "opt-in only via NOMETRIA_ACCEPT_RESTRICTED_MODEL_LICENSES=1, "
                "regardless of deployment."
            ),
        }
        return {
            "detectors": [
                {
                    "key": key,
                    "version": detector.version,
                    "surfaces": list(detector.surfaces),
                    "available": key in available,
                    "enabled": key in get_settings().enabled_detectors,
                    # A detector that knows why it is unavailable says so itself;
                    # the table above covers the ones that predate that. Twenty
                    # Hub validators maintained in a hard-coded dict in this file
                    # would drift from the catalogue on the first addition.
                    "unavailable_reason": (
                        None
                        if key in available
                        else getattr(detector, "unavailable_reason", None)
                        or unavailable_reason.get(key)
                    ),
                    "label": getattr(detector, "label", None),
                    "install": getattr(detector, "package", None),
                    "stats": stats.get(key, {}),
                }
                for key, detector in sorted(all_detectors().items())
            ],
            "budget_ms": get_settings().enforcement_budget_ms,
            "detector_timeout_ms": get_settings().detector_timeout_ms,
        }

    @app.get("/api/reliability", tags=["platform"])
    def reliability(session: Session = Depends(db), _u=Depends(current_user)) -> dict[str, Any]:
        """P15 — circuit-breaker state and live budget consumption."""
        from sqlalchemy import select

        from ..models import Agent, Budget
        from ..reliability import BREAKER, check_budget

        budgets = []
        for budget in session.scalars(select(Budget).where(Budget.scope_type == "agent")):
            agent = session.get(Agent, budget.scope_id)
            verdict = check_budget(session, "agent", budget.scope_id)
            budgets.append({"agent": agent.slug if agent else budget.scope_id, **verdict.to_json()})
        return {
            "circuit_breakers": BREAKER.snapshot(),
            "budgets": budgets,
            "fallback_chain": get_settings().fallback_chain,
            # Gap 0.7: the per-service degradation ledger, alongside the per-provider
            # breaker it complements. `fail_mode` travels with it because "degraded"
            # means something different under each — open means those requests were
            # served unchecked, closed means they were refused.
            "fail_mode": get_settings().fail_mode,
            "degradation": service_health(),
        }

    @app.get("/metrics", tags=["platform"], response_class=PlainTextResponse)
    def metrics(session: Session = Depends(db)) -> str:
        """I-7 — Prometheus exposition.

        Unauthenticated on purpose, like every other /metrics endpoint: a scrape job
        that needs a bearer token is a scrape job nobody configures. It exposes counts
        and rates, never content — no prompt, no finding detail, no identifier.
        """
        from ..integrations.prometheus import render_metrics

        return render_metrics(session)

    @app.get("/api/providers", tags=["platform"])
    def providers(_u=Depends(current_user)) -> dict[str, Any]:
        """X-2 — the neutrality surface, made inspectable."""
        available = available_providers()
        return {
            "providers": [
                {
                    "key": key,
                    "available": key in available,
                    "default": key == get_settings().default_provider,
                }
                for key in sorted(all_providers())
            ],
            "note": (
                "Hosted providers report unavailable unless NOMETRIA_ALLOW_EGRESS=1 and "
                "a key is configured. Zero egress is the default (NFR-4)."
            ),
        }

    return app


app = create_app()
