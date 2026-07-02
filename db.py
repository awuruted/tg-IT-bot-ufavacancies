"""
Работа с базой вакансий (SQLite).

На Amvera папка /data — единственное место, которое сохраняется между
пересборками приложения. Поэтому путь к базе зависит от того, где мы
запущены: локально или в облаке Amvera (там выставлена переменная
окружения AMVERA=true автоматически).
"""

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = "/data/vacancies.db" if os.environ.get("AMVERA") else "vacancies.db"


def init_db():
    """Создаёт таблицу вакансий, если её ещё нет. Вызывается при старте."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vacancies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                employer TEXT,
                salary_from INTEGER,
                salary_to INTEGER,
                currency TEXT,
                url TEXT,
                snippet TEXT,
                area TEXT,
                published_at TEXT,
                source TEXT DEFAULT 'hh.ru'
            )
            """
        )
        # Добавляем колонку source в старые базы, где её ещё нет
        try:
            conn.execute("ALTER TABLE vacancies ADD COLUMN source TEXT DEFAULT 'hh.ru'")
        except Exception:
            pass  # колонка уже есть — игнорируем
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def upsert_vacancies(vacancies: list[dict]):
    """Вставляет или обновляет пачку вакансий по id (без дублей)."""
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO vacancies (id, name, employer, salary_from, salary_to,
                                    currency, url, snippet, area, published_at, source)
            VALUES (:id, :name, :employer, :salary_from, :salary_to,
                    :currency, :url, :snippet, :area, :published_at, :source)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                employer=excluded.employer,
                salary_from=excluded.salary_from,
                salary_to=excluded.salary_to,
                currency=excluded.currency,
                url=excluded.url,
                snippet=excluded.snippet,
                area=excluded.area,
                published_at=excluded.published_at,
                source=excluded.source
            """,
            vacancies,
        )
        conn.commit()


def search_vacancies(query: str, limit: int = 15) -> list[dict]:
    """
    Простой поиск по ключевым словам в названии и сниппете.
    Разбивает запрос пользователя на слова и ищет вакансии,
    где встречается хотя бы одно из них (без учёта регистра).
    """
    words = [w.strip() for w in query.lower().split() if len(w.strip()) > 2]
    if not words:
        words = [query.lower()]

    conditions = " OR ".join(["(LOWER(name) LIKE ? OR LOWER(snippet) LIKE ?)"] * len(words))
    params = []
    for w in words:
        like = f"%{w}%"
        params.extend([like, like])

    sql = f"""
        SELECT id, name, employer, salary_from, salary_to, currency, url, snippet, source
        FROM vacancies
        WHERE {conditions}
        ORDER BY published_at DESC
        LIMIT ?
    """
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def count_vacancies() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]


def count_by_source() -> dict:
    """Возвращает количество вакансий по каждому источнику."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM vacancies GROUP BY source"
        ).fetchall()
        return {r["source"]: r["cnt"] for r in rows}
