"""Verify Alembic migrations apply cleanly to a fresh database."""
from __future__ import annotations

import os
import pytest
from sqlalchemy import create_engine, inspect, text


EXPECTED_TABLES = {"tenders", "companies", "api_keys", "match_results"}

EXPECTED_COLUMNS = {
    "tenders": {"id", "title_he", "publisher_he", "source_pdf", "analysis_json", "model_used", "created_at"},
    "companies": {"id", "name", "profile_json", "created_at"},
    "api_keys": {"key_hash", "company_id", "label", "is_active", "created_at"},
    "match_results": {"id", "company_id", "tender_id", "is_eligible", "compatibility_score",
                      "relevance_score", "final_score", "report_json", "computed_at"},
}


@pytest.fixture()
def migrated_db(tmp_path):
    """Apply migrations to a fresh SQLite DB in a temp dir; yield its engine."""
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "test_migrations.db"
    db_url = f"sqlite:///{db_path}"

    # Find alembic.ini (two levels up from this file)
    ini = str((tmp_path.parent.parent / "The-tender-seeker" / "alembic.ini").resolve())
    # Fallback: search project root
    import pathlib
    project_root = pathlib.Path(__file__).parent.parent
    ini = str(project_root / "alembic.ini")

    cfg = Config(ini)
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    yield engine
    engine.dispose()


class TestInitialMigration:
    def test_all_tables_created(self, migrated_db):
        tables = set(inspect(migrated_db).get_table_names())
        assert EXPECTED_TABLES.issubset(tables)

    def test_alembic_version_table_exists(self, migrated_db):
        tables = set(inspect(migrated_db).get_table_names())
        assert "alembic_version" in tables

    def test_alembic_version_at_head(self, migrated_db):
        with migrated_db.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        assert row is not None
        assert len(row[0]) > 0

    @pytest.mark.parametrize("table,columns", EXPECTED_COLUMNS.items())
    def test_columns_present(self, migrated_db, table, columns):
        actual = {c["name"] for c in inspect(migrated_db).get_columns(table)}
        assert columns.issubset(actual), f"Missing columns in {table}: {columns - actual}"

    def test_api_keys_index_on_company_id(self, migrated_db):
        indexes = {idx["name"] for idx in inspect(migrated_db).get_indexes("api_keys")}
        assert any("company_id" in name for name in indexes)

    def test_match_results_indexes(self, migrated_db):
        indexes = {idx["name"] for idx in inspect(migrated_db).get_indexes("match_results")}
        assert any("company_id" in name for name in indexes)
        assert any("tender_id" in name for name in indexes)

    def test_upgrade_is_idempotent(self, migrated_db, tmp_path):
        """Running upgrade head twice on the same DB should not raise."""
        from alembic import command
        from alembic.config import Config
        import pathlib

        db_url = str(migrated_db.url)
        ini = str(pathlib.Path(__file__).parent.parent / "alembic.ini")
        cfg = Config(ini)
        cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(cfg, "head")  # second run — must be a no-op

    def test_downgrade_removes_tables(self, migrated_db):
        from alembic import command
        from alembic.config import Config
        import pathlib

        db_url = str(migrated_db.url)
        ini = str(pathlib.Path(__file__).parent.parent / "alembic.ini")
        cfg = Config(ini)
        cfg.set_main_option("sqlalchemy.url", db_url)
        command.downgrade(cfg, "base")

        tables = set(inspect(migrated_db).get_table_names())
        assert EXPECTED_TABLES.isdisjoint(tables)
