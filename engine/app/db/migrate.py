"""Migration — materialize the v0 schema.

v0 has no schema *evolution* yet, so the migration is simply "create the tables
the models declare" (``Base.metadata.create_all``). Following the deep-module
rule — do not introduce a tool until something varies across it — a full
migration framework (Alembic) is deferred until the schema starts changing over
time; see ADR 0007. When that happens, this module is where it lands, so callers
keep saying ``create_all(engine)``.

Run it against the configured database with::

    python -m app.db.migrate        # uses DATABASE_URL
"""
from __future__ import annotations

from sqlalchemy.engine import Engine

from app.db.models import Base
from app.db.session import create_db_engine, database_url


def create_all(engine: Engine) -> None:
    """Create every v0 table that does not already exist. Idempotent."""
    Base.metadata.create_all(engine)


def drop_all(engine: Engine) -> None:
    """Drop every v0 table. Used to reset a database (e.g. between tests)."""
    Base.metadata.drop_all(engine)


def main() -> None:
    url = database_url()
    engine = create_db_engine(url)
    create_all(engine)
    tables = ", ".join(sorted(Base.metadata.tables))
    print(f"schema created on {engine.url.render_as_string(hide_password=True)}: {tables}")


if __name__ == "__main__":
    main()
