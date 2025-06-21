from sqlalchemy.orm import Session
from . import models


def add_message_to_history(
    db: Session, user_id: int, role: str, content: str
) -> models.History:
    db_message = models.History(user_id=user_id, role=role, content=content)
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message


def get_user_history(db: Session, user_id: int) -> list[models.History]:
    return db.query(models.History).filter(models.History.user_id == user_id).all()


def clear_user_history(db: Session, user_id: int) -> int:
    num_rows_deleted = (
        db.query(models.History).filter(models.History.user_id == user_id).delete()
    )
    db.commit()
    return num_rows_deleted


def get_or_create_user(db: Session, user_id: int, mode: str = None) -> models.User:
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        user = models.User(id=user_id)
        db.add(user)
        db.commit()
        db.refresh(user)
    if mode:
        user.mode = mode
        db.commit()
        db.refresh(user)
    return user


def update_user_mode(db: Session, user_id: int, mode: str) -> models.User:
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if db_user:
        db_user.mode = mode
        db.commit()
        db.refresh(db_user)
    return db_user


def update_user_model(db: Session, user_id: int, mode: str) -> models.User:
    user = get_or_create_user(db, user_id)
    user.mode = mode
    db.commit()
    db.refresh(user)
    return user
