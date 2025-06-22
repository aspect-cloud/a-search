from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models import Base

DATABASE_URL = "sqlite+aiosqlite:///db/as_search_bot.db"

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

async def async_init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
