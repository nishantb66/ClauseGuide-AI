from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from app.core.settings import get_settings
from app.models.base import Base

settings = get_settings()
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
