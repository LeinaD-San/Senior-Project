"""
Smoke tests for the smaller endpoints: health check, maps key config, and the
HTML page-serving routes.
"""
import os


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_config_maps_returns_key(client):
    r = client.get("/config/maps")
    assert r.status_code == 200
    body = r.json()
    # conftest sets these env vars; one of the two should be returned.
    assert body["google_maps_js_api_key"] in (
        "test-google-maps-js-key",
        "test-google-maps-key",
    )


def test_config_maps_returns_none_without_key(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_JS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    r = client.get("/config/maps")
    assert r.status_code == 200
    assert r.json()["google_maps_js_api_key"] is None


def test_landing_page_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_itinerary_page_serves_html(client):
    r = client.get("/itinerary")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_login_page_serves_html(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_planner_page_serves_html(client):
    r = client.get("/planner")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_account_page_serves_html(client):
    r = client.get("/account")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_ai_test_returns_503_when_not_configured(client, monkeypatch):
    # main.openai_client is built at import time from OPENAI_API_KEY (which can
    # be set by the project's .env file). Force it to None so we exercise the
    # "not configured" branch and never hit the real OpenAI API.
    import main
    monkeypatch.setattr(main, "openai_client", None)
    r = client.get("/ai/test")
    assert r.status_code == 503
