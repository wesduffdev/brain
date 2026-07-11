"""Migration — materialize the v0 schema.

v0 has no schema *evolution* yet, so the migration is simply "create the tables
the models declare" (``Base.metadata.create_all``). Following the deep-module
rule — do not introduce a tool until something varies across it — a full
migration framework (Alembic) is deferred until the schema starts changing over
time; see ADR 0007. When that happens, this module is where it lands, so callers
keep saying ``create_all(engine)``.

Run it against the configured database with::

    python -m app.db.migrate        # uses DATABASE_URL

Because a migration is often the first thing to touch a freshly-started
Postgres, ``main`` waits for the database to accept connections
(``wait_for_database``, retrying with bounded backoff) before creating the
schema, so ``make migrate`` right after ``docker compose up`` no longer races
the DB's first-boot init. It fails with a clear error if the database never
comes up within the configured timeout.
"""
from __future__ import annotations

from sqlalchemy.engine import Engine

from app.db.models import Base
from app.db.session import create_db_engine, database_url, wait_for_database


def create_all(engine: Engine) -> None:
    """Create every v0 table that does not already exist. Idempotent."""
    Base.metadata.create_all(engine)


def drop_all(engine: Engine) -> None:
    """Drop every v0 table. Used to reset a database (e.g. between tests)."""
    Base.metadata.drop_all(engine)


def main() -> None:
    url = database_url()
    engine = create_db_engine(url)
    target = engine.url.render_as_string(hide_password=True)
    print(f"waiting for database at {target} to accept connections...")
    wait_for_database(engine)  # retry with bounded backoff, or fail clearly on timeout
    create_all(engine)
    tables = ", ".join(sorted(Base.metadata.tables))
    print(f"schema created on {target}: {tables}")


if __name__ == "__main__":
    main()
