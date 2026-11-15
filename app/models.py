from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    cards: Mapped[list["Card"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Card(Base):
    __tablename__ = "cards"
    # Один користувач не може мати дві картки з тим самим словом
    __table_args__ = (UniqueConstraint("user_id", "word", name="uq_cards_user_word"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    word: Mapped[str] = mapped_column(String(100))
    # Переклади, які користувач обрав (або 3 найпопулярніші за замовчуванням)
    translations: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Усі варіанти, які дав перекладач, щоб потім можна було змінити вибір без нового запиту
    options: Mapped[list[str]] = mapped_column(JSON, default=list)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[User] = relationship(back_populates="cards")
