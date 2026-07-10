"""Persistence internals — SQLAlchemy schema, connection, and migration.

This package holds everything that knows the database exists: the ORM models
(the v0 tables from BRIEF §15), the engine/session factory built from
`DATABASE_URL`, and the migration that materializes the schema. Application code
never imports these directly — it goes through the repository port
(`app.ports.repositories`) and its adapters (`app.repositories`).
"""
