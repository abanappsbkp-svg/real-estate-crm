"""
Database connection setup
Single place for the engine, session factory and the get_db dependency.
Every router imports get_db from here (never from main.py, to avoid circular imports).
"""

import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from config import settings


def _normalize_db_url(url: str) -> str:
    """Render/Heroku sometimes give 'postgres://', which SQLAlchemy 2 rejects."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


DATABASE_URL = _normalize_db_url(settings.DATABASE_URL)

def _json_default(value):
    """Let JSON columns (audit logs, custom fields) store Decimal, UUID and dates."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _json_serializer(obj):
    return json.dumps(obj, default=_json_default)


_engine_kwargs = {
    "json_serializer": _json_serializer,
    "echo": settings.DEBUG,
    "pool_pre_ping": True,  # recover from dropped connections (Render free DBs sleep)
}
if settings.ENVIRONMENT == "testing":
    _engine_kwargs["poolclass"] = NullPool

engine = create_engine(DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency: yields a database session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def sync_schema(Base) -> None:
    """
    Create missing tables, add missing columns and relax NOT NULL constraints
    so an existing database matches models.py. Safe to run on every startup:
    it never drops tables, columns or data.
    """
    from sqlalchemy import inspect, text

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            db_columns = {c["name"]: c for c in inspector.get_columns(table.name)}
            for column in table.columns:
                col_type = column.type.compile(dialect=engine.dialect)
                if column.name not in db_columns:
                    conn.execute(text(
                        f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS "{column.name}" {col_type}'
                    ))
                elif column.nullable and not db_columns[column.name]["nullable"] and not column.primary_key:
                    conn.execute(text(
                        f'ALTER TABLE "{table.name}" ALTER COLUMN "{column.name}" DROP NOT NULL'
                    ))


def seed_reference_data() -> None:
    """Insert the supported languages (users.preferred_language points at them)."""
    from sqlalchemy import text

    languages = [("en", "English"), ("ru", "Russian"), ("hy", "Armenian"), ("fa", "Persian")]
    with engine.begin() as conn:
        for code, name in languages:
            conn.execute(
                text(
                    "INSERT INTO languages (id, code, name, is_active, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), :code, :name, true, now(), now()) "
                    "ON CONFLICT (code) DO NOTHING"
                ),
                {"code": code, "name": name},
            )
