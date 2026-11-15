import random
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import translator
from .auth import create_token, get_current_user, hash_password, verify_password
from .db import Base, engine, get_db
from .models import Card, User, utcnow
from .schemas import (
    ArchiveIn, CardCreate, CardOut, CardUpdate, Credentials, GameItem, GameMode, RegisterCredentials,
    ReviewIn, TokenOut, TranslateOut, UserOut,
)

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_TRANSLATIONS = 3
AUTO_ARCHIVE_AFTER = 10  # скільки правильних відповідей — і слово йде в архів
_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z '\-]*$")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Створює таблиці users і cards, якщо їх ще немає
    Base.metadata.create_all(bind=engine)
    add_missing_columns()
    yield


def add_missing_columns():
    """create_all не додає нові колонки до вже існуючих таблиць — докидаємо їх вручну."""
    columns = {c["name"] for c in inspect(engine).get_columns("cards")}
    ts_type = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME"
    with engine.begin() as conn:
        if "archived" not in columns:
            conn.execute(text("ALTER TABLE cards ADD COLUMN archived BOOLEAN NOT NULL DEFAULT FALSE"))
        if "archived_at" not in columns:
            conn.execute(text(f"ALTER TABLE cards ADD COLUMN archived_at {ts_type}"))


app = FastAPI(title="English Flashcards", lifespan=lifespan)


def normalize_word(raw: str) -> str:
    word = " ".join(raw.split()).lower()
    if not word or len(word) > 100 or not _WORD_RE.match(word):
        raise HTTPException(422, "Введіть англійське слово або фразу (лише латинські літери)")
    return word


def clean_translations(items: list[str]) -> list[str]:
    seen, result = set(), []
    for t in items:
        t = " ".join(t.split())
        if t and t.lower() not in seen and len(t) <= 100:
            seen.add(t.lower())
            result.append(t)
    return result


def get_own_card(card_id: int, user: User, db: Session) -> Card:
    card = db.get(Card, card_id)
    # Чужа картка поводиться як неіснуюча
    if card is None or card.user_id != user.id:
        raise HTTPException(404, "Картку не знайдено")
    return card


# ---------- Сторінка ----------

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}


# ---------- Користувачі ----------

@app.post("/api/auth/register", response_model=TokenOut, status_code=201)
def register(data: RegisterCredentials, db: Session = Depends(get_db)):
    username = data.username.lower()
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(409, "Такий користувач уже існує")
    user = User(username=username, password_hash=hash_password(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Такий користувач уже існує")
    return TokenOut(token=create_token(user.id), username=user.username)


@app.post("/api/auth/login", response_model=TokenOut)
def login(data: Credentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == data.username.lower()))
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невірний логін або пароль")
    return TokenOut(token=create_token(user.id), username=user.username)


@app.get("/api/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut(id=user.id, username=user.username)


# ---------- Перекладач ----------

@app.get("/api/translate", response_model=TranslateOut)
async def translate_word(
    word: str = Query(min_length=1, max_length=100),
    _user: User = Depends(get_current_user),
):
    word = normalize_word(word)
    try:
        variants = await translator.translate(word)
    except translator.TranslatorUnavailable:
        raise HTTPException(503, "Перекладач зараз недоступний, спробуйте пізніше")
    return TranslateOut(word=word, variants=variants)


# ---------- Картки ----------

@app.get("/api/cards", response_model=list[CardOut])
def list_cards(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(Card).where(Card.user_id == user.id).order_by(Card.created_at.desc())
    ).all()


@app.post("/api/cards", response_model=CardOut, status_code=201)
async def create_card(
    data: CardCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    word = normalize_word(data.word)
    if db.scalar(select(Card).where(Card.user_id == user.id, Card.word == word)):
        raise HTTPException(409, f"Картка «{word}» уже є")

    chosen = clean_translations(data.translations or [])
    try:
        options = [v["text"] for v in await translator.translate(word)]
    except translator.TranslatorUnavailable:
        # Сервер заблоковано (буває на хмарному хостингу) — беремо варіанти, які знайшов браузер
        options = clean_translations(data.options or [])

    if not chosen:
        # Користувач нічого не обрав — беремо 3 найпопулярніші
        chosen = options[:DEFAULT_TRANSLATIONS]
    if not chosen:
        raise HTTPException(503, "Перекладач недоступний — введіть переклад вручну")

    # Власні переклади користувача теж додаємо до списку варіантів
    options = clean_translations(options + chosen)

    card = Card(user_id=user.id, word=word, translations=chosen, options=options)
    db.add(card)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Картка «{word}» уже є")
    db.refresh(card)
    return card


@app.put("/api/cards/{card_id}", response_model=CardOut)
def update_card(
    card_id: int,
    data: CardUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = get_own_card(card_id, user, db)
    chosen = clean_translations(data.translations)
    if not chosen:
        raise HTTPException(422, "Потрібен хоча б один переклад")
    card.translations = chosen
    card.options = clean_translations(list(card.options or []) + chosen)
    db.commit()
    db.refresh(card)
    return card


@app.post("/api/cards/{card_id}/archive", response_model=CardOut)
def archive_card(
    card_id: int,
    data: ArchiveIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = get_own_card(card_id, user, db)
    card.archived = data.archived
    card.archived_at = utcnow() if data.archived else None
    db.commit()
    db.refresh(card)
    return card


@app.delete("/api/cards/{card_id}", status_code=204)
def delete_card(card_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(get_own_card(card_id, user, db))
    db.commit()


# ---------- Гра ----------

@app.get("/api/game/deck", response_model=list[GameItem])
def game_deck(
    mode: GameMode = "en_uk",
    limit: int = Query(20, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Перемішана колода. en_uk: бачиш англійське слово, згадуєш переклад; uk_en: навпаки."""
    # Архівні (вже вивчені) слова в гру не потрапляють
    cards = list(db.scalars(
        select(Card).where(Card.user_id == user.id, Card.archived.is_(False))
    ).all())
    random.shuffle(cards)
    deck = []
    for c in cards[:limit]:
        uk = ", ".join(c.translations)
        if mode == "en_uk":
            deck.append(GameItem(card_id=c.id, question=c.word, answer=uk))
        else:
            deck.append(GameItem(card_id=c.id, question=uk, answer=c.word))
    return deck


@app.post("/api/cards/{card_id}/review", response_model=CardOut)
def review_card(
    card_id: int,
    data: ReviewIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = get_own_card(card_id, user, db)
    if data.knew:
        card.correct_count += 1
        # Слово вгадали вже 10 разів — вважаємо вивченим і прибираємо в архів
        if card.correct_count >= AUTO_ARCHIVE_AFTER and not card.archived:
            card.archived = True
            card.archived_at = utcnow()
    else:
        card.wrong_count += 1
    db.commit()
    db.refresh(card)
    return card
