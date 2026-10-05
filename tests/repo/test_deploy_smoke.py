"""The deployment smoke test has to be right about a deployment it cannot reach here.

`scripts/deploy_smoke.py` only ever runs against a live URL, which means its own logic
is the part nobody exercises until a deployment is already broken and the script says
the wrong thing. These tests run every check against a scripted deployment in-process,
with no network at all: a healthy one, then one deliberately broken in each of the ways
that actually shipped to a live URL.

What they prove: each check passes on a healthy response shape and fails, with a
quotable reason, on the specific bad shape it exists to catch. What they do not prove:
that the recorded response shapes still match the real API. That binding is what
running the script against the deployment is for.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("deploy_smoke", REPO / "scripts" / "deploy_smoke.py")
deploy_smoke = importlib.util.module_from_spec(_spec)
sys.modules["deploy_smoke"] = deploy_smoke  # dataclasses resolve through sys.modules
_spec.loader.exec_module(deploy_smoke)

API = "https://api.example.test"
DASH = "https://dash.example.test"


class FakeResponse:
    def __init__(self, status_code: int, body=None, headers: dict | None = None):
        self.status_code = status_code
        self._body = body
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.text = "" if body is None else json.dumps(body)

    def json(self):
        if self._body is None:
            raise ValueError("response body is not JSON")
        return self._body


def _openapi(paths: dict) -> dict:
    return {"openapi": "3.1.0", "paths": paths}


def _default_paths() -> dict:
    paths = {path: {"get": {}} for path in deploy_smoke.EXPECTED_PATHS}
    paths["/api/internal/jobs/run"] = {"get": {}, "post": {}}
    paths["/api/playground/sessions"] = {"post": {}}
    return paths


class FakeDeployment:
    """A scripted API and dashboard, standing in for an httpx.Client.

    Every attribute below is a knob a test turns to break exactly one thing. The
    defaults describe a deployment where everything works.
    """

    def __init__(self):
        self.health = FakeResponse(200, {"status": "ok", "version": "0.3.0"})
        self.openapi = FakeResponse(200, _openapi(_default_paths()))
        self.cron_status = {"GET": 401, "POST": 401}
        self.authenticated_status = 401
        self.session_status = 201
        self.session_body = {"session_id": "pg_test", "mode": "observe"}
        self.enforce_status = 200
        self.cors_status = 200
        self.cors_allow_origin = DASH
        self.dashboard_status = {"/login": 200, "/playground": 200, "/benchmark": 200}
        self.root = FakeResponse(200, {"name": "agentfox", "version": "0.3.0", "docs": "/docs"})
        #: How many reads a sandbox survives before it starts answering 404, which is
        #: what a visitor hit when sandboxes lived in one process of a many-process API.
        self.sandbox_reads_before_gone = None
        # Playground chat: what the sandbox reports before and after the enforce flip.
        self.observe_blocked = False
        self.observe_effective_verdict = "block"
        self.enforce_blocked = True
        self.chat_status = 200
        self.raise_on = {}  # url substring -> exception to raise
        self.mode = "observe"
        self.requests: list[tuple[str, str]] = []
        self.closed = False

    # -- httpx.Client surface ------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def request(self, method, url, json=None, headers=None):  # noqa: A002
        self.requests.append((method, url))
        for fragment, exc in self.raise_on.items():
            if fragment in url:
                raise exc
        return self._route(method, url, json or {}, headers or {})

    # -- routing -------------------------------------------------------------
    def _route(self, method, url, body, headers):
        if url.startswith(DASH):
            return FakeResponse(self.dashboard_status.get(url[len(DASH) :], 404))
        path = url[len(API) :]

        if path in ("", "/"):
            return self.root
        if path.endswith("/state"):
            self.state_reads = getattr(self, "state_reads", 0) + 1
            limit = self.sandbox_reads_before_gone
            if limit is not None and self.state_reads > limit:
                return FakeResponse(404, {"detail": "expired or never existed"})
            return FakeResponse(200, {"traces": [], "chain": {"valid": True}})
        if path == "/api/health":
            return self.health
        if path == "/openapi.json":
            return self.openapi
        if path == deploy_smoke.CRON_PATH:
            return FakeResponse(self.cron_status[method], {"detail": "nope"})
        if path == deploy_smoke.AUTHENTICATED_PATH:
            return FakeResponse(self.authenticated_status, {"detail": "nope"})
        if path == "/api/playground/sessions":
            if method == "OPTIONS":
                allow = (
                    {"access-control-allow-origin": self.cors_allow_origin}
                    if self.cors_allow_origin
                    else {}
                )
                return FakeResponse(self.cors_status, headers=allow)
            return FakeResponse(self.session_status, self.session_body)
        if path.endswith("/enforce"):
            self.mode = body.get("mode", self.mode)
            return FakeResponse(self.enforce_status, {"mode": self.mode})
        if path.endswith("/chat"):
            return self._chat()
        return FakeResponse(404, {"detail": "Not Found"})

    def _chat(self):
        if self.chat_status != 200:
            return FakeResponse(self.chat_status, {"detail": "boom"})
        enforcing = self.mode == "enforce"
        blocked = self.enforce_blocked if enforcing else self.observe_blocked
        return FakeResponse(
            200,
            {
                "reply": None if blocked else "sure thing",
                "blocked": blocked,
                "escalated": False,
                "verdict": {
                    "verdict": "block" if blocked else "allow",
                    "effective_verdict": "block" if enforcing else self.observe_effective_verdict,
                    "rules_fired": [{"rule_id": "injection.direct", "effect": "block"}],
                },
            },
        )


def run(client) -> dict[str, deploy_smoke.CheckResult]:
    return {r.name: r for r in deploy_smoke.run_checks(client, API, DASH)}


def assert_only_failure(results: dict, name: str, fragment: str) -> None:
    failed = [n for n, r in results.items() if not r.ok]
    assert failed == [name], f"expected only {name} to fail, got {failed}"
    assert fragment in results[name].detail, results[name].detail


# -- the healthy case --------------------------------------------------------


def test_a_healthy_deployment_passes_every_check():
    results = run(FakeDeployment())
    assert [n for n, r in results.items() if not r.ok] == []
    assert len(results) == len(deploy_smoke.CHECKS)


def test_the_playground_check_really_flips_the_sandbox_to_enforce():
    client = FakeDeployment()
    run(client)
    assert client.mode == "enforce"
    chats = [u for m, u in client.requests if u.endswith("/chat")]
    assert len(chats) == 2, "the same message must be sent before and after the flip"


# -- health ------------------------------------------------------------------


def test_health_reporting_a_non_ok_status_fails():
    client = FakeDeployment()
    client.health = FakeResponse(200, {"status": "degraded"})
    assert_only_failure(run(client), "api_health", "'degraded'")


def test_health_returning_a_server_error_fails():
    client = FakeDeployment()
    client.health = FakeResponse(500, {"detail": "boom"})
    assert_only_failure(run(client), "api_health", "returned 500")


def test_health_returning_html_instead_of_json_fails():
    client = FakeDeployment()
    client.health = FakeResponse(200, None)
    assert_only_failure(run(client), "api_health", "did not return JSON")


# -- the published route table ----------------------------------------------


def test_a_missing_route_family_fails_and_names_it():
    client = FakeDeployment()
    paths = _default_paths()
    del paths["/api/proposals"]
    client.openapi = FakeResponse(200, _openapi(paths))
    assert_only_failure(run(client), "api_openapi_routes", "/api/proposals")


def test_a_cron_path_without_post_fails():
    client = FakeDeployment()
    paths = _default_paths()
    paths[deploy_smoke.CRON_PATH] = {"get": {}}
    client.openapi = FakeResponse(200, _openapi(paths))
    assert_only_failure(run(client), "api_openapi_routes", "missing POST")


def test_a_cron_path_without_get_fails():
    client = FakeDeployment()
    paths = _default_paths()
    paths[deploy_smoke.CRON_PATH] = {"post": {}}
    client.openapi = FakeResponse(200, _openapi(paths))
    assert_only_failure(run(client), "api_openapi_routes", "missing GET")


# -- the cron entrypoint -----------------------------------------------------


def test_a_cron_endpoint_that_answers_200_anonymously_fails():
    client = FakeDeployment()
    client.cron_status["POST"] = 200
    assert_only_failure(run(client), "cron_requires_auth", "open to anyone")


def test_a_cron_method_that_answers_405_fails():
    client = FakeDeployment()
    client.cron_status["GET"] = 405
    assert_only_failure(run(client), "cron_requires_auth", "never run the job")


def test_a_cron_endpoint_that_answers_503_passes():
    """503 is how a deployment with no cron secret configured refuses, which is still
    a refusal, so the check accepts it."""
    client = FakeDeployment()
    client.cron_status = {"GET": 503, "POST": 503}
    assert [n for n, r in run(client).items() if not r.ok] == []


def test_an_unexpected_cron_status_fails():
    client = FakeDeployment()
    client.cron_status["POST"] = 500
    assert_only_failure(run(client), "cron_requires_auth", "returned 500")


# -- auth --------------------------------------------------------------------


def test_an_account_route_open_to_anonymous_callers_fails():
    client = FakeDeployment()
    client.authenticated_status = 200
    assert_only_failure(run(client), "authenticated_route_rejects_anonymous", "auth is not on")


def test_an_account_route_returning_500_fails_differently_from_401():
    client = FakeDeployment()
    client.authenticated_status = 500
    assert_only_failure(
        run(client), "authenticated_route_rejects_anonymous", "failing rather than rejecting"
    )


def test_a_403_on_an_account_route_is_accepted_as_a_rejection():
    client = FakeDeployment()
    client.authenticated_status = 403
    assert [n for n, r in run(client).items() if not r.ok] == []


# -- the public playground ---------------------------------------------------


def test_a_playground_that_will_not_create_a_sandbox_fails():
    client = FakeDeployment()
    client.session_status = 429
    assert_only_failure(run(client), "playground_end_to_end", "returned 429")


def test_a_sandbox_response_without_a_session_id_fails():
    """Both sandbox checks depend on creation, so both report it rather than one hiding it."""
    client = FakeDeployment()
    client.session_body = {"mode": "observe"}
    results = run(client)
    failed = {n for n, r in results.items() if not r.ok}
    assert failed == {"playground_end_to_end", "playground_sandbox_survives"}
    assert "no session_id" in results["playground_end_to_end"].detail


def test_observe_mode_that_already_blocks_fails():
    client = FakeDeployment()
    client.observe_blocked = True
    assert_only_failure(run(client), "playground_end_to_end", "still in observe mode")


def test_a_detector_that_does_not_flag_the_known_payload_fails():
    client = FakeDeployment()
    client.observe_effective_verdict = "allow"
    assert_only_failure(run(client), "playground_end_to_end", "known injection payload")


def test_enforce_mode_that_does_not_actually_block_fails():
    client = FakeDeployment()
    client.enforce_blocked = False
    assert_only_failure(run(client), "playground_end_to_end", "enforce mode is not taking effect")


def test_an_enforce_flip_that_errors_fails():
    client = FakeDeployment()
    client.enforce_status = 500
    assert_only_failure(run(client), "playground_end_to_end", "returned 500")


# -- CORS --------------------------------------------------------------------


def test_a_preflight_rejected_outright_fails():
    client = FakeDeployment()
    client.cors_status = 400
    assert_only_failure(run(client), "cors_preflight_from_dashboard", "browser preflight fails")


def test_a_preflight_with_no_allow_origin_header_fails():
    """The failure that looks fine under curl and shows as "Failed to fetch" in a browser."""
    client = FakeDeployment()
    client.cors_allow_origin = None
    assert_only_failure(
        run(client), "cors_preflight_from_dashboard", "no Access-Control-Allow-Origin"
    )


def test_a_preflight_allowing_a_different_origin_fails():
    client = FakeDeployment()
    client.cors_allow_origin = "https://someone-else.example.test"
    assert_only_failure(run(client), "cors_preflight_from_dashboard", "does not cover")


def test_a_wildcard_allow_origin_passes():
    client = FakeDeployment()
    client.cors_allow_origin = "*"
    assert [n for n, r in run(client).items() if not r.ok] == []


def test_the_preflight_origin_is_the_dashboard_scheme_and_host_only():
    assert deploy_smoke._origin("https://dash.example.test/playground?a=1") == DASH


# -- dashboard pages ---------------------------------------------------------


def test_a_dashboard_login_page_that_redirects_fails():
    client = FakeDeployment()
    client.dashboard_status["/login"] = 307
    assert_only_failure(run(client), "dashboard_login", "returned 307")


def test_a_dashboard_playground_page_that_500s_fails():
    client = FakeDeployment()
    client.dashboard_status["/playground"] = 500
    assert_only_failure(run(client), "dashboard_playground", "returned 500")


# -- unreachable deployments -------------------------------------------------


def test_a_connection_error_is_reported_as_a_failed_check_not_a_crash():
    client = FakeDeployment()
    client.raise_on = {"api.example.test": ConnectionError("name resolution failed")}
    results = run(client)
    api_checks = [
        "api_health",
        "api_openapi_routes",
        "cron_requires_auth",
        "authenticated_route_rejects_anonymous",
        "playground_end_to_end",
        "cors_preflight_from_dashboard",
    ]
    for name in api_checks:
        assert not results[name].ok
        assert "ConnectionError" in results[name].detail
    # The dashboard is a separate host, so its checks still report honestly.
    assert results["dashboard_login"].ok


# -- the command line --------------------------------------------------------


@pytest.fixture
def stub_httpx(monkeypatch):
    """Replace httpx.Client inside the script with a scripted deployment."""
    client = FakeDeployment()
    monkeypatch.setattr(deploy_smoke.httpx, "Client", lambda **kwargs: client)
    return client


def test_a_sandbox_that_vanishes_between_reads_is_caught():
    """The failure this check exists for: one instance serves it, the next has never heard of it."""
    fake = FakeDeployment()
    fake.sandbox_reads_before_gone = 3
    assert_only_failure(run(fake), "playground_sandbox_survives", "was gone on read 4")


def test_a_private_benchmark_page_is_caught():
    fake = FakeDeployment()
    fake.dashboard_status["/benchmark"] = 307  # bounced to sign-in
    assert_only_failure(run(fake), "dashboard_benchmark", "returned 307")


def test_a_bare_404_at_the_api_root_is_caught():
    fake = FakeDeployment()
    fake.root = FakeResponse(404, {"detail": "Not Found"})
    assert_only_failure(run(fake), "api_root_is_discoverable", "returned 404")


def test_main_exits_zero_and_prints_a_pass_line_per_check(stub_httpx, capsys):
    code = deploy_smoke.main(["--api-url", API, "--dashboard-url", DASH])
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("PASS") == len(deploy_smoke.CHECKS)
    assert "FAIL" not in out
    assert f"all {len(deploy_smoke.CHECKS)} checks passed" in out
    assert stub_httpx.closed, "the client must be closed"


def test_main_exits_non_zero_and_names_the_failing_check(stub_httpx, capsys):
    stub_httpx.cors_allow_origin = None
    code = deploy_smoke.main(["--api-url", API, "--dashboard-url", DASH])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL  cors_preflight_from_dashboard" in out
    assert f"1 of {len(deploy_smoke.CHECKS)} checks failed: cors_preflight_from_dashboard" in out


def test_main_json_output_is_machine_readable(stub_httpx, capsys):
    stub_httpx.authenticated_status = 200
    code = deploy_smoke.main(["--api-url", API, "--dashboard-url", DASH, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["api_url"] == API
    assert payload["dashboard_url"] == DASH
    failing = [c["name"] for c in payload["checks"] if not c["ok"]]
    assert failing == ["authenticated_route_rejects_anonymous"]


def test_a_trailing_slash_on_either_url_does_not_double_up(stub_httpx):
    deploy_smoke.main(["--api-url", API + "/", "--dashboard-url", DASH + "/"])
    assert all("//api" not in url.removeprefix("https://") for _, url in stub_httpx.requests)


def test_the_defaults_point_at_the_live_deployments():
    parser = deploy_smoke.build_parser()
    args = parser.parse_args([])
    assert args.api_url == deploy_smoke.DEFAULT_API_URL
    assert args.dashboard_url == deploy_smoke.DEFAULT_DASHBOARD_URL
    assert args.as_json is False
