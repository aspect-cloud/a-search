from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import os

from app.db.models import Base

# Use /tmp for the database in a serverless environment like Vercel
db_path = "/tmp/as_search_bot.db"
DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

async def async_init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
