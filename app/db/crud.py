from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from . import models


async def add_message_to_history(
    db: AsyncSession, user_id: int, role: str, content: str
) -> models.History:
    db_message = models.History(user_id=user_id, role=role, content=content)
    db.add(db_message)
    await db.commit()
    await db.refresh(db_message)
    return db_message


async def get_user_history(db: AsyncSession, user_id: int) -> list[models.History]:
    result = await db.execute(
        select(models.History).filter(models.History.user_id == user_id)
    )
    return result.scalars().all()


async def clear_user_history(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(
        delete(models.History).filter(models.History.user_id == user_id)
    )
    await db.commit()
    return result.rowcount


async def get_or_create_user(
    db: AsyncSession, user_id: int, mode: str = None
) -> models.User:
    result = await db.execute(select(models.User).filter(models.User.id == user_id))
    user = result.scalars().first()
    if not user:
        user = models.User(id=user_id)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    if mode:
        user.mode = mode
        await db.commit()
        await db.refresh(user)
    return user


async def update_user_mode(db: AsyncSession, user_id: int, mode: str) -> models.User:
    result = await db.execute(select(models.User).filter(models.User.id == user_id))
    db_user = result.scalars().first()
    if db_user:
        db_user.mode = mode
        await db.commit()
        await db.refresh(db_user)
    return db_user


async def update_user_model(db: AsyncSession, user_id: int, mode: str) -> models.User:
    user = await get_or_create_user(db, user_id)
    user.mode = mode
    await db.commit()
    await db.refresh(user)
    return user
