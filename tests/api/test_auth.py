"""Tests for /auth endpoints — zero LLM calls."""
from __future__ import annotations

from .conftest import company_payload


class TestRegister:
    def test_returns_api_key(self, client):
        resp = client.post("/auth/register", json=company_payload())
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_key"].startswith("sk-st-")
        assert data["company_id"] == "514123456"
        assert "warning" in data

    def test_key_format(self, client):
        key = client.post("/auth/register", json=company_payload()).json()["api_key"]
        # sk-st- + 64 hex chars (32 bytes)
        assert len(key) == len("sk-st-") + 64

    def test_register_twice_both_keys_valid(self, client):
        key1 = client.post("/auth/register", json=company_payload()).json()["api_key"]
        key2 = client.post("/auth/register", json=company_payload()).json()["api_key"]
        assert key1 != key2
        for key in (key1, key2):
            resp = client.get("/auth/me", headers={"X-API-Key": key})
            assert resp.status_code == 200

    def test_different_companies_different_ids(self, client):
        id_a = client.post("/auth/register", json=company_payload("111", "חברה א")).json()["company_id"]
        id_b = client.post("/auth/register", json=company_payload("222", "חברה ב")).json()["company_id"]
        assert id_a != id_b


class TestMe:
    def test_valid_key_returns_company(self, registered):
        client, api_key, company_id = registered
        resp = client.get("/auth/me", headers={"X-API-Key": api_key})
        assert resp.status_code == 200
        data = resp.json()
        assert data["company_id"] == company_id
        assert data["company_name"] is not None

    def test_no_key_returns_401(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_wrong_key_returns_401(self, client):
        resp = client.get("/auth/me", headers={"X-API-Key": "sk-st-wrong"})
        assert resp.status_code == 401

    def test_empty_key_returns_401(self, client):
        resp = client.get("/auth/me", headers={"X-API-Key": ""})
        assert resp.status_code == 401


class TestRevoke:
    def test_revoke_succeeds(self, registered):
        client, api_key, _ = registered
        resp = client.delete("/auth/revoke", headers={"X-API-Key": api_key})
        assert resp.status_code == 200

    def test_revoked_key_returns_403(self, registered):
        client, api_key, _ = registered
        client.delete("/auth/revoke", headers={"X-API-Key": api_key})
        resp = client.get("/auth/me", headers={"X-API-Key": api_key})
        assert resp.status_code == 403

    def test_revoke_only_affects_that_key(self, client):
        key1 = client.post("/auth/register", json=company_payload("111", "חברה א")).json()["api_key"]
        key2 = client.post("/auth/register", json=company_payload("222", "חברה ב")).json()["api_key"]
        client.delete("/auth/revoke", headers={"X-API-Key": key1})
        # key2 of a different company still works
        assert client.get("/auth/me", headers={"X-API-Key": key2}).status_code == 200

    def test_cannot_revoke_without_key(self, client):
        resp = client.delete("/auth/revoke")
        assert resp.status_code == 401
