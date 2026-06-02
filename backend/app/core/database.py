from collections.abc import AsyncGenerator
from pathlib import Path
from urllib.parse import unquote, urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from app.core.settings import get_settings
from app.models.base import Base

settings = get_settings()


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    """Create the SQLite parent directory before SQLAlchemy opens the DB file."""
    if not database_url.startswith("sqlite"):
        return

    parsed = urlparse(database_url)
    raw_path = unquote(parsed.path or "")
    if not raw_path:
        return

    # sqlite+aiosqlite:///./storage/app.db is parsed as /./storage/app.db.
    if raw_path.startswith("/./"):
        db_path = Path("." + raw_path[2:])
    elif raw_path.startswith("//"):
        db_path = Path(raw_path[1:])
    else:
        db_path = Path(raw_path)

    db_path.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent_dir(settings.database_url)
settings.upload_path
settings.report_path

engine = create_async_engine(settings.database_url, future=True, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    # Import models before table creation to ensure metadata is fully registered.
    from app.models import chat, clause, document, evaluation, markdown, report, user  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        if settings.database_url.startswith("sqlite"):
            columns = await connection.execute(text("PRAGMA table_info(documents)"))
            names = {row[1] for row in columns.fetchall()}
            if "owner_user_id" not in names:
                await connection.execute(
                    text("ALTER TABLE documents ADD COLUMN owner_user_id VARCHAR(36)")
                )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
