"""SQLAlchemy engine / session plumbing."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(url: str):
    engine = make_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return engine, factory
