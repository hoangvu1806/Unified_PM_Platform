"""Existing Postgres volumes keep packages when feature_status is added."""

from __future__ import annotations

from sqlalchemy import inspect, text

import managers.database.connection as db_connection
from managers.database.connection import configure_sync_engine, get_sync_database_url, init_db


def test_init_db_adds_missing_feature_status_column():
    configure_sync_engine("sqlite:///:memory:")
    try:
        with db_connection.sync_engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE ba_packages ("
                    "session_id VARCHAR PRIMARY KEY, "
                    "feature_title VARCHAR, "
                    "is_validated BOOLEAN NOT NULL DEFAULT 0"
                    ")"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO ba_packages (session_id, feature_title, is_validated) "
                    "VALUES ('11111111-1111-1111-1111-111111111111', 'Old package', 1)"
                )
            )
        init_db()
        columns = {
            col["name"]
            for col in inspect(db_connection.sync_engine).get_columns("ba_packages")
        }
        assert "feature_status" in columns
        with db_connection.sync_engine.connect() as conn:
            status = conn.execute(text("SELECT feature_status FROM ba_packages")).scalar_one()
        assert status == "VALIDATED"
    finally:
        configure_sync_engine(get_sync_database_url())
