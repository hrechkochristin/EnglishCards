"""Підключення до бази даних.

Локально за замовчуванням використовується SQLite-файл flashcards.db.
Для деплою достатньо задати змінну середовища DATABASE_URL (наприклад, Postgres з Neon).
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")


def _normalize_url(url: str) -> str:
    # Хостинги часто дають "postgres://" або "postgresql://",
    # а SQLAlchemy + psycopg3 очікує "postgresql+psycopg://".
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _normalize_url(os.getenv("DATABASE_URL", "sqlite:///./flashcards.db"))

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
