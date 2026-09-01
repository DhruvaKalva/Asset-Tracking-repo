"""Engine + session. SQLite for zero-setup dev, Postgres in prod via DATABASE_URL."""
from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=not _is_sqlite,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after the first release. create_all() creates missing *tables*
# but never alters an existing one, so a database seeded before these shipped
# would keep the old shape and every query touching them would fail.
#
# This is a deliberate stand-in for Alembic: the project has no migration tool,
# and the alternative -- telling everyone to drop their database -- is worse.
# Reach for Alembic the moment a change needs more than an additive column.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "equipment": {
        "mobility": "VARCHAR(8) DEFAULT 'MOVABLE'",
        "home_site_id": "VARCHAR(16)",
    },
}


def _apply_additive_migrations() -> None:
    inspector = inspect(engine)
    for table, columns in _ADDED_COLUMNS.items():
        if not inspector.has_table(table):
            continue  # create_all() will build it with the columns already on it
        existing = {c["name"] for c in inspector.get_columns(table)}
        missing = {name: ddl for name, ddl in columns.items() if name not in existing}
        if not missing:
            continue
        with engine.begin() as conn:
            for name, ddl in missing.items():
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db() -> None:
    from app import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)
    _apply_additive_migrations()
