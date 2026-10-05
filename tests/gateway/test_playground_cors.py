"""The playground's allowed origins.

The playground page is called from the browser, cross-origin and unauthenticated, so a
missing origin does not fail loudly: the page shows "Failed to fetch" while curl against
the same API looks healthy. That happened in production, and it happens again the moment
a second host (a standby dashboard, a custom domain mid-move) needs to be allowed.
"""

from __future__ import annotations

import pytest

from agentfox.core.config import get_settings, reset_settings_cache

VERCEL = "https://guardrails-agentfox.vercel.app"
VERCEL_OLD = "https://guardrails-dashboard-eight.vercel.app"
RENDER = "https://nometria-dashboard.onrender.com"


@pytest.fixture(autouse=True)
def _clean_settings():
    reset_settings_cache()
    yield
    reset_settings_cache()


def _origins(value: str | None) -> list[str]:
    if value is not None:
        import os

        os.environ["NOMETRIA_PLAYGROUND_CORS_ORIGIN"] = value
    reset_settings_cache()
    try:
        return get_settings().playground_cors_origins
    finally:
        import os

        os.environ.pop("NOMETRIA_PLAYGROUND_CORS_ORIGIN", None)


def test_unset_means_no_extra_origins():
    assert _origins(None) == []


def test_a_single_origin_still_works():
    assert _origins(VERCEL) == [VERCEL]


def test_several_hosts_are_all_allowed():
    assert _origins(f"{VERCEL},{RENDER}") == [VERCEL, RENDER]


def test_whitespace_trailing_slashes_blanks_and_duplicates_are_tolerated():
    assert _origins(f" {VERCEL}/ , , {RENDER} , {VERCEL} ") == [VERCEL, RENDER]


def test_the_app_allows_localhost_plus_every_configured_origin():
    import os

    os.environ["NOMETRIA_PLAYGROUND_CORS_ORIGIN"] = f"{VERCEL},{RENDER}"
    reset_settings_cache()
    try:
        from agentfox.gateway.app import create_app

        app = create_app()
        allowed: list[str] = []
        for middleware in app.user_middleware:
            origins = middleware.kwargs.get("allow_origins")
            if origins:
                allowed = list(origins)
        assert "http://localhost:3000" in allowed and "http://127.0.0.1:3000" in allowed
        assert VERCEL in allowed and RENDER in allowed
    finally:
        os.environ.pop("NOMETRIA_PLAYGROUND_CORS_ORIGIN", None)
        reset_settings_cache()
