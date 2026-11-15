"""Перекладач з кількома варіантами перекладу.

1) Основне джерело — публічний endpoint Google Translate (client=gtx). Він безкоштовний,
   без ключа, і, що головне, повертає словникові варіанти з оцінкою популярності (score).
   Це неофіційний API: він може змінитися або обмежити частоту запитів.
2) Запасний варіант — MyMemory (api.mymemory.translated.net), теж безкоштовний і без ключа
   (ліміт близько 5000 символів на день з однієї IP; більше, якщо задати MYMEMORY_EMAIL).

Результати кешуються в пам'яті, щоб не смикати API повторно для того самого слова.
"""
import logging
import os
from collections import OrderedDict

import httpx

log = logging.getLogger("uvicorn.error")

SOURCE_LANG = os.getenv("SOURCE_LANG", "en")
TARGET_LANG = os.getenv("TARGET_LANG", "uk")
MYMEMORY_EMAIL = os.getenv("MYMEMORY_EMAIL", "")

GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"

_TIMEOUT = httpx.Timeout(8.0)
_CACHE_SIZE = 2000
_cache: "OrderedDict[str, list[dict]]" = OrderedDict()


class TranslatorUnavailable(Exception):
    pass


def _dedupe(variants: list[dict], source_word: str) -> list[dict]:
    seen: set[str] = set()
    result = []
    for v in variants:
        text = " ".join(v["text"].split()).strip()
        key = text.lower()
        if not text or key in seen or key == source_word.lower():
            continue
        seen.add(key)
        result.append({**v, "text": text})
    return result


def parse_google(data: dict, word: str) -> list[dict]:
    """Розбирає відповідь Google (dj=1). Спершу основний переклад, далі словник за score."""
    main = "".join(s.get("trans", "") for s in data.get("sentences") or []).strip()

    dictionary = []
    for group in data.get("dict") or []:
        pos = group.get("pos") or None
        for entry in group.get("entry") or []:
            if entry.get("word"):
                dictionary.append(
                    {"text": entry["word"], "pos": pos, "score": float(entry.get("score") or 0)}
                )
    dictionary.sort(key=lambda v: v["score"], reverse=True)

    variants = []
    if main:
        top_score = dictionary[0]["score"] if dictionary else 1.0
        variants.append({"text": main, "pos": None, "score": max(top_score, 1.0)})
    variants.extend(dictionary)
    return _dedupe(variants, word)


def parse_mymemory(data: dict, word: str) -> list[dict]:
    # При вичерпаному ліміті MyMemory відповідає HTTP 200, але з responseStatus 429/403
    # і текстом попередження замість перекладу
    status = str(data.get("responseStatus", "200"))
    if status != "200":
        raise ValueError(f"MyMemory responseStatus={status}: {data.get('responseDetails')}")
    variants = []
    main = (data.get("responseData") or {}).get("translatedText") or ""
    if main.isupper():  # MyMemory інколи повертає КАПСОМ
        main = main.lower()
    if main:
        variants.append({"text": main, "pos": None, "score": 1.0})
    matches = data.get("matches") or []
    matches = sorted(matches, key=lambda m: float(m.get("match") or 0), reverse=True)
    for m in matches:
        text = m.get("translation") or ""
        if text and len(text) <= 60:
            variants.append({"text": text, "pos": None, "score": float(m.get("match") or 0)})
    return _dedupe(variants, word)


async def _google(client: httpx.AsyncClient, word: str) -> list[dict]:
    params = [
        ("client", "gtx"), ("sl", SOURCE_LANG), ("tl", TARGET_LANG),
        ("dt", "t"), ("dt", "bd"), ("dj", "1"), ("q", word),
    ]
    r = await client.get(GOOGLE_URL, params=params)
    r.raise_for_status()
    return parse_google(r.json(), word)


async def _mymemory(client: httpx.AsyncClient, word: str) -> list[dict]:
    params = {"q": word, "langpair": f"{SOURCE_LANG}|{TARGET_LANG}"}
    if MYMEMORY_EMAIL:
        params["de"] = MYMEMORY_EMAIL
    r = await client.get(MYMEMORY_URL, params=params)
    r.raise_for_status()
    return parse_mymemory(r.json(), word)


async def translate(word: str) -> list[dict]:
    """Повертає список варіантів [{text, pos, score}], від найпопулярнішого."""
    key = word.lower()
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"}) as client:
        variants: list[dict] = []
        for provider in (_google, _mymemory):
            try:
                variants = await provider(client, word)
            except (httpx.HTTPError, ValueError) as e:
                log.warning("Перекладач %s не відповів для %r: %s: %s",
                            provider.__name__, word, type(e).__name__, e)
                continue
            if variants:
                break
            log.warning("Перекладач %s повернув порожній результат для %r", provider.__name__, word)

    if not variants:
        raise TranslatorUnavailable("Не вдалося отримати переклад")

    _cache[key] = variants
    if len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return variants
