"""
Обращение к LLM через встроенный сервис Amvera.

ВАЖНО: точный URL эндпоинта и формат запроса нужно сверить в личном
кабинете Amvera в разделе LLM/AI после регистрации — там же выдаётся
токен. Ниже — рабочий шаблон по образцу обычного OpenAI-совместимого
API (Amvera заявляет токен-биллинг и доступ к GPT/LLaMA моделям).
Если реальный эндпоинт будет отличаться — поменяй только LLM_API_URL
и, если нужно, структуру json в функции ask_llm.
"""

import os

import requests

LLM_TOKEN = os.environ.get("AMVERA_LLM_TOKEN", "")
LLM_API_URL = os.environ.get(
    "AMVERA_LLM_API_URL", "https://llm.api.amvera.ru/v1/chat/completions"
)
LLM_MODEL = os.environ.get("AMVERA_LLM_MODEL", "gpt-4.1")

SYSTEM_PROMPT = (
    "Ты — помощник по поиску IT-вакансий в Уфе. Тебе дают вопрос "
    "пользователя и список подходящих вакансий (название, работодатель, "
    "зарплата, ссылка). Кратко и по делу скажи, какие вакансии лучше всего "
    "подходят под запрос и почему. Если подходящих вакансий нет — честно "
    "скажи об этом и предложи переформулировать запрос."
)


def ask_llm(user_query: str, vacancies: list[dict]) -> str:
    if not LLM_TOKEN:
        return (
            "LLM не настроена: не задана переменная окружения AMVERA_LLM_TOKEN. "
            "Вот вакансии без анализа:\n"
            + format_vacancies_plain(vacancies)
        )

    context = format_vacancies_plain(vacancies)
    prompt = f"Вопрос пользователя: {user_query}\n\nНайденные вакансии:\n{context}"

    try:
        resp = requests.post(
            LLM_API_URL,
            headers={"Authorization": f"Bearer {LLM_TOKEN}"},
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except requests.RequestException as e:
        return f"Не удалось получить ответ от LLM ({e}). Вот вакансии без анализа:\n{context}"
    except (KeyError, IndexError):
        return f"Неожиданный формат ответа LLM. Вот вакансии без анализа:\n{context}"


def format_vacancies_plain(vacancies: list[dict]) -> str:
    if not vacancies:
        return "Подходящих вакансий не найдено в базе."
    lines = []
    for v in vacancies:
        salary = ""
        if v.get("salary_from") or v.get("salary_to"):
            salary = f" | {v.get('salary_from') or '?'}-{v.get('salary_to') or '?'} {v.get('currency') or ''}"
        lines.append(f"- {v['name']} ({v.get('employer', '')}){salary}\n  {v['url']}")
    return "\n".join(lines)
