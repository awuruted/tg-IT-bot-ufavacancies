"""
Сбор IT-вакансий по Уфе из нескольких источников:
  - hh.ru       (открытый API, ключ не нужен)
  - SuperJob     (официальный API, нужен SUPERJOB_API_KEY)
  - Trudvsem.ru  (открытый гос. API, ключ не нужен)
"""

import logging
import os
import time
from datetime import datetime

import requests

from db import upsert_vacancies

logger = logging.getLogger(__name__)

REQUEST_DELAY = 0.4  # пауза между запросами в секундах

HEADERS_BASE = {
    "User-Agent": "ufa-it-vacancies-bot/1.0 (contact: your_email@example.com)"
}

# ──────────────────────────────────────────────
# HH.RU
# ──────────────────────────────────────────────

HH_URL = "https://api.hh.ru/vacancies"
HH_AREA_UFA = 1467

IT_QUERY = (
    "программист OR разработчик OR developer OR python OR java OR "
    "frontend OR backend OR devops OR тестировщик OR QA OR аналитик данных OR "
    "системный администратор OR 1C OR data science"
)


def _parse_hh_item(item: dict) -> dict:
    salary = item.get("salary") or {}
    return {
        "id": f"hh_{item['id']}",
        "name": item.get("name", ""),
        "employer": (item.get("employer") or {}).get("name", ""),
        "salary_from": salary.get("from"),
        "salary_to": salary.get("to"),
        "currency": salary.get("currency"),
        "url": item.get("alternate_url", ""),
        "snippet": " ".join(filter(None, [
            (item.get("snippet") or {}).get("requirement"),
            (item.get("snippet") or {}).get("responsibility"),
        ])),
        "area": (item.get("area") or {}).get("name", "Уфа"),
        "published_at": item.get("published_at", ""),
        "source": "hh.ru",
    }


def fetch_hh(max_pages: int = 20) -> list[dict]:
    results = []
    for page in range(max_pages):
        params = {
            "area": HH_AREA_UFA,
            "text": IT_QUERY,
            "search_field": "name",
            "per_page": 100,
            "page": page,
        }
        try:
            resp = requests.get(HH_URL, params=params, headers=HEADERS_BASE, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning("[hh.ru] Ошибка на странице %s: %s", page, e)
            break

        data = resp.json()
        results.extend(data.get("items", []))
        if page >= data.get("pages", 1) - 1:
            break
        time.sleep(REQUEST_DELAY)

    return [_parse_hh_item(i) for i in results]


# ──────────────────────────────────────────────
# SUPERJOB
# ──────────────────────────────────────────────
# Как получить ключ:
# 1. Зайди на https://api.superjob.ru/
# 2. Зарегистрируйся и создай приложение
# 3. Скопируй «Секретный ключ» (начинается с v3.r....)
# 4. Добавь в переменные окружения Amvera: SUPERJOB_API_KEY=v3.r.XXX...

SJ_URL = "https://api.superjob.ru/2.0/vacancies/"
SJ_TOWN_UFA = 209  # id Уфы в справочнике SuperJob

IT_KEYWORDS_SJ = [
    "программист", "разработчик", "developer", "python", "java",
    "frontend", "backend", "devops", "тестировщик", "QA", "1C",
]


def _parse_sj_item(item: dict) -> dict:
    return {
        "id": f"sj_{item['id']}",
        "name": item.get("profession", ""),
        "employer": (item.get("firm_name") or ""),
        "salary_from": item.get("payment_from") or None,
        "salary_to": item.get("payment_to") or None,
        "currency": "RUR" if item.get("currency") == "rub" else item.get("currency", ""),
        "url": item.get("link", ""),
        "snippet": item.get("candidat", ""),  # описание требований к кандидату
        "area": "Уфа",
        "published_at": datetime.fromtimestamp(
            item.get("date_published", 0)
        ).isoformat() if item.get("date_published") else "",
        "source": "superjob.ru",
    }


def fetch_superjob() -> list[dict]:
    api_key = os.environ.get("SUPERJOB_API_KEY")
    if not api_key:
        logger.info("[superjob] SUPERJOB_API_KEY не задан — пропускаю источник.")
        return []

    headers = {**HEADERS_BASE, "X-Api-App-Id": api_key}
    results = []

    for keyword in IT_KEYWORDS_SJ:
        params = {
            "town": SJ_TOWN_UFA,
            "keyword": keyword,
            "count": 100,
            "page": 0,
        }
        try:
            resp = requests.get(SJ_URL, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            results.extend(data.get("objects", []))
        except requests.RequestException as e:
            logger.warning("[superjob] Ошибка по ключевому слову '%s': %s", keyword, e)
        time.sleep(REQUEST_DELAY)

    # убираем дубли по id (одна вакансия может попасть в несколько запросов)
    seen = set()
    unique = []
    for item in results:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)

    return [_parse_sj_item(i) for i in unique]


# ──────────────────────────────────────────────
# TRUDVSEM.RU (гос. портал «Работа России»)
# ──────────────────────────────────────────────
# Открытый API, ключ не нужен.
# Башкортостан (Уфа) — код региона 02.

TV_URL = "https://opendata.trudvsem.ru/api/v1/vacancies/region/0200000000000"

IT_KEYWORDS_TV = [
    "программист", "разработчик", "developer", "python", "java",
    "1C", "devops", "тестировщик", "системный администратор",
]


def _parse_tv_item(item: dict) -> dict:
    vac = item.get("vacancy", item)
    salary = vac.get("salary", "")
    salary_from = None
    salary_to = None
    if isinstance(salary, str) and "-" in salary:
        parts = salary.replace(" ", "").split("-")
        try:
            salary_from = int(parts[0])
            salary_to = int(parts[1])
        except (ValueError, IndexError):
            pass
    elif isinstance(salary, (int, float)):
        salary_from = int(salary)

    return {
        "id": f"tv_{vac.get('id', '')}",
        "name": vac.get("job-name", ""),
        "employer": vac.get("company", {}).get("name", "") if isinstance(vac.get("company"), dict) else "",
        "salary_from": salary_from,
        "salary_to": salary_to,
        "currency": "RUR",
        "url": vac.get("vac_url", ""),
        "snippet": vac.get("duty", ""),
        "area": "Уфа",
        "published_at": vac.get("creation-date", ""),
        "source": "trudvsem.ru",
    }


def fetch_trudvsem() -> list[dict]:
    results = []
    for keyword in IT_KEYWORDS_TV:
        params = {"text": keyword, "limit": 100, "offset": 0}
        try:
            resp = requests.get(TV_URL, params=params, headers=HEADERS_BASE, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("results", {}).get("vacancies", [])
            results.extend(items)
        except requests.RequestException as e:
            logger.warning("[trudvsem] Ошибка по слову '%s': %s", keyword, e)
        time.sleep(REQUEST_DELAY)

    seen = set()
    unique = []
    for item in results:
        vac = item.get("vacancy", item)
        vid = vac.get("id", "")
        if vid and vid not in seen:
            seen.add(vid)
            unique.append(item)

    return [_parse_tv_item(i) for i in unique]


# ──────────────────────────────────────────────
# ОБЩАЯ ФУНКЦИЯ ОБНОВЛЕНИЯ
# ──────────────────────────────────────────────

def update_vacancies():
    """Собирает вакансии со всех источников и сохраняет в базу."""
    total = 0

    logger.info("=== Обновление вакансий ===")

    hh = fetch_hh()
    if hh:
        upsert_vacancies(hh)
        logger.info("[hh.ru] Сохранено: %s", len(hh))
        total += len(hh)

    sj = fetch_superjob()
    if sj:
        upsert_vacancies(sj)
        logger.info("[superjob.ru] Сохранено: %s", len(sj))
        total += len(sj)

    tv = fetch_trudvsem()
    if tv:
        upsert_vacancies(tv)
        logger.info("[trudvsem.ru] Сохранено: %s", len(tv))
        total += len(tv)

    logger.info("=== Итого обработано: %s вакансий ===", total)
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from db import init_db
    init_db()
    update_vacancies()
