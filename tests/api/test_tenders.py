"""Tests for /tenders endpoints — zero LLM calls."""
from __future__ import annotations

from src.smarttender.agents.criteria_agent import CriteriaAgent

from .conftest import seed_tender


class TestListTenders:
    def test_requires_auth(self, client):
        assert client.get("/tenders").status_code == 401

    def test_empty_when_no_tenders(self, authed):
        client, _ = authed
        resp = client.get("/tenders")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_seeded_tender(self, authed):
        client, _ = authed
        analysis = seed_tender(client)
        resp = client.get("/tenders")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["tender_id"] == analysis.tender_id
        assert items[0]["title_he"] == analysis.title_he

    def test_returns_multiple_tenders(self, authed):
        client, _ = authed
        a1 = seed_tender(client)
        # Seed a second tender with a different ID
        a2 = CriteriaAgent.mock()
        a2.tender_id = "TENDER-002"
        a2.title_he = "מכרז שני"
        seed_tender(client, a2)
        items = client.get("/tenders").json()
        assert len(items) == 2


class TestGetTender:
    def test_requires_auth(self, client):
        assert client.get("/tenders/NONEXISTENT").status_code == 401

    def test_not_found_returns_404(self, authed):
        client, _ = authed
        assert client.get("/tenders/NONEXISTENT").status_code == 404

    def test_returns_full_analysis(self, authed):
        client, _ = authed
        analysis = seed_tender(client)
        resp = client.get(f"/tenders/{analysis.tender_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tender_id"] == analysis.tender_id
        assert "criteria" in data
        assert len(data["criteria"]) == len(analysis.criteria)


class TestIngestTender:
    def test_requires_auth(self, client, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        with open(pdf, "rb") as f:
            resp = client.post("/tenders/ingest", files={"file": ("test.pdf", f, "application/pdf")})
        assert resp.status_code == 401

    def test_rejects_non_pdf(self, authed):
        client, _ = authed
        resp = client.post(
            "/tenders/ingest",
            files={"file": ("doc.docx", b"fake content", "application/octet-stream")},
            data={"model": "haiku"},
        )
        assert resp.status_code == 400

    def test_ingest_with_mocked_extraction(self, authed, tmp_path, monkeypatch):
        """Ingest a PDF with LLM call mocked — tests the full ingest flow at zero cost."""
        client, _ = authed

        # Patch the pipeline to return mock analysis without calling the LLM
        from src.smarttender.agents import graph as graph_mod
        mock_analysis = CriteriaAgent.mock()

        original_node = graph_mod.TenderPipeline.node_extract_criteria
        def fake_extract(self, state, *, on_status=None):
            state.analysis = mock_analysis
            return state
        monkeypatch.setattr(graph_mod.TenderPipeline, "node_extract_criteria", fake_extract)

        pdf = tmp_path / "tender.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake content")
        with open(pdf, "rb") as f:
            resp = client.post(
                "/tenders/ingest",
                files={"file": ("tender.pdf", f, "application/pdf")},
                data={"model": "haiku"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["tender_id"] == mock_analysis.tender_id
        assert data["criteria_count"] == len(mock_analysis.criteria)

        # Verify it's stored and retrievable
        get_resp = client.get(f"/tenders/{mock_analysis.tender_id}")
        assert get_resp.status_code == 200

    def test_ingest_idempotent(self, authed, tmp_path, monkeypatch):
        """Re-ingesting the same tender_id overwrites cleanly."""
        client, _ = authed

        from src.smarttender.agents import graph as graph_mod
        mock_analysis = CriteriaAgent.mock()

        def fake_extract(self, state, *, on_status=None):
            state.analysis = mock_analysis
            return state
        monkeypatch.setattr(graph_mod.TenderPipeline, "node_extract_criteria", fake_extract)

        pdf = tmp_path / "tender.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        for _ in range(2):
            with open(pdf, "rb") as f:
                resp = client.post(
                    "/tenders/ingest",
                    files={"file": ("tender.pdf", f, "application/pdf")},
                    data={"model": "haiku"},
                )
            assert resp.status_code == 200

        assert len(client.get("/tenders").json()) == 1
