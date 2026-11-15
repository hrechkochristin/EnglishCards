from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=128)


class RegisterCredentials(Credentials):
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password(cls, password: str) -> str:
        if any(
            char.isalpha() and not ("A" <= char <= "Z" or "a" <= char <= "z")
            for char in password
        ):
            raise ValueError("Пароль може містити лише латинські літери")
        if not any("A" <= char <= "Z" for char in password):
            raise ValueError("Пароль має містити велику латинську літеру")
        if not any("a" <= char <= "z" for char in password):
            raise ValueError("Пароль має містити малу латинську літеру")
        if not any("0" <= char <= "9" for char in password):
            raise ValueError("Пароль має містити цифру")
        return password


class TokenOut(BaseModel):
    token: str
    username: str


class UserOut(BaseModel):
    id: int
    username: str


class Variant(BaseModel):
    text: str
    pos: str | None = None  # частина мови: noun, verb...
    score: float = 0.0


class TranslateOut(BaseModel):
    word: str
    variants: list[Variant]


class CardCreate(BaseModel):
    word: str = Field(min_length=1, max_length=100)
    # Якщо None або порожній список — збережемо 3 найпопулярніші переклади
    translations: list[str] | None = None


class CardUpdate(BaseModel):
    translations: list[str] = Field(min_length=1)


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    word: str
    translations: list[str]
    options: list[str]
    correct_count: int
    wrong_count: int
    created_at: datetime


class ReviewIn(BaseModel):
    knew: bool


GameMode = Literal["en_uk", "uk_en"]


class GameItem(BaseModel):
    card_id: int
    question: str
    answer: str
