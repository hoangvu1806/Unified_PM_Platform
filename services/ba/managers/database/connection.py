from __future__ import annotations

import urllib.parse
from typing import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from config.base_config import settings


class Base(DeclarativeBase):
    """Base model for SQLAlchemy ORM."""

    pass


# Generate sync PostgreSQL connection URL using psycopg2
def get_sync_database_url() -> str:
    encoded_password = urllib.parse.quote_plus(settings.db_password)
    return (
        f"postgresql+psycopg2://{settings.db_user}:{encoded_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


def _create_sync_engine(database_url: str) -> Engine:
    """Build a sync engine. Postgres keeps a pool; SQLite shares one in-memory DB."""
    if database_url.startswith("sqlite"):
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(
        database_url,
        pool_size=settings.db_max_pool_size,
        pool_pre_ping=True,
    )


sync_engine = _create_sync_engine(get_sync_database_url())
SessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)


def configure_sync_engine(database_url: str) -> Engine:
    """Rebind the process-wide sync Session factory.

    Production keeps the import-time Postgres engine. Tests pass a SQLite URL
    so Feature CRUD does not need localhost:5432. Callers that imported
    ``SessionLocal`` still see the new bind via ``sessionmaker.configure``.
    """
    global sync_engine
    new_engine = _create_sync_engine(database_url)
    old_engine = sync_engine
    sync_engine = new_engine
    SessionLocal.configure(bind=sync_engine)
    if old_engine is not None and old_engine is not new_engine:
        old_engine.dispose()
    return sync_engine


def get_db_session() -> Generator[Session, None, None]:
    """Dependency helper to yield a SQLAlchemy session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Initialize database tables if they do not exist."""
    Base.metadata.create_all(bind=sync_engine)
    _ensure_ba_package_columns()


def _ensure_ba_package_columns() -> None:
    """Add columns that create_all will not attach to an existing table.

    Local Docker volumes created before ``feature_status`` must keep packages.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(sync_engine)
    if "ba_packages" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("ba_packages")}
    if "feature_status" in existing:
        return
    dialect = sync_engine.dialect.name
    ddl = (
        "ALTER TABLE ba_packages ADD COLUMN feature_status VARCHAR(32) "
        "NOT NULL DEFAULT 'DRAFT'"
        if dialect == "postgresql"
        else "ALTER TABLE ba_packages ADD COLUMN feature_status VARCHAR(32) DEFAULT 'DRAFT'"
    )
    with sync_engine.begin() as conn:
        conn.execute(text(ddl))
        conn.execute(
            text(
                "UPDATE ba_packages SET feature_status = 'VALIDATED' "
                "WHERE is_validated IS TRUE AND feature_status = 'DRAFT'"
            )
        )
