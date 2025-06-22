from sqlalchemy import Column, Integer, String, Text, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.types import JSON

Base = declarative_base()


class History(Base):
    __tablename__ = "history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    file_names = Column(JSON, nullable=True) # New column to store list of file names


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, index=True)
    mode = Column(String, default="fast")
