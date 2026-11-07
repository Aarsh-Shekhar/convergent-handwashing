"""Database engine/session management (SQLite for dev/tests, PostgreSQL via docker-compose)."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from convergent.common.config import Settings, load_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None, settings: Settings | None = None) -> Engine:
    settings = settings or load_settings()
    url = url or settings.database_url
    if url.startswith("sqlite"):
        if ":memory:" not in url and "mode=memory" not in url:
            db_path = url.replace("sqlite:///", "")
            if db_path and db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL") if ":memory:" not in url else None
            cur.close()

        return engine
    return create_engine(url, pool_pre_ping=True, future=True)


class Database:
    def __init__(self, url: str | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.url = url or self.settings.database_url
        self.engine = make_engine(self.url, self.settings)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False, class_=Session)

    def session(self) -> Session:
        return self.SessionLocal()

    def get_db(self) -> Generator[Session, None, None]:
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def dispose(self) -> None:
        self.engine.dispose()


def run_migrations(url: str) -> str:
    """Apply Alembic migrations to ``head`` using the packaged migration scripts. Returns the head revision."""
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    migrations = Path(__file__).resolve().parent / "migrations"
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")
    return str(ScriptDirectory.from_config(cfg).get_current_head())


def current_revision(url: str) -> str | None:
    from alembic.runtime.migration import MigrationContext

    engine = make_engine(url)
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()
