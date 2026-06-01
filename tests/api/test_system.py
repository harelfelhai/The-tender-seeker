"""Tests for /health endpoint and CORS middleware — zero LLM calls."""
from __future__ import annotations


class TestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_no_auth_required(self, client):
        """Health check must work without an API key."""
        resp = client.get("/health", headers={})
        assert resp.status_code == 200

    def test_health_body(self, client):
        data = client.get("/health").json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_version_format(self, client):
        version = client.get("/health").json()["version"]
        parts = version.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)


class TestCors:
    def test_cors_headers_present_on_health(self, client):
        """OPTIONS preflight to /health should echo back CORS allow headers."""
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-API-Key",
            },
        )
        # FastAPI/Starlette returns 200 for OPTIONS when CORS middleware is active
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers

    def test_cors_origin_echoed(self, client):
        resp = client.get("/health", headers={"Origin": "http://localhost:3000"})
        acao = resp.headers.get("access-control-allow-origin", "")
        # With allow_origins=["*"], header is either "*" or the echoed origin
        assert acao in ("*", "http://localhost:3000")

    def test_cors_allow_methods_includes_get(self, client):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        allow_methods = resp.headers.get("access-control-allow-methods", "")
        assert "GET" in allow_methods or allow_methods == "*"

    def test_cors_headers_on_authed_endpoint(self, client):
        """CORS headers are present even on protected endpoints (preflight must work)."""
        resp = client.options(
            "/tenders",
            headers={
                "Origin": "http://app.example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-API-Key",
            },
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers
