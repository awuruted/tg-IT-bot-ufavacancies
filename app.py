"""
Точка входа приложения.

Запускает:
1. Telegram-бота (long polling) — отвечает на вопросы пользователя по вакансиям.
2. Планировщик, который раз в час обновляет базу вакансий с hh.ru.
3. Маленький HTTP-сервер на порту из amvera.yaml — нужен только для того,
   чтобы Amvera видела "живое" приложение и не считала его упавшим
   (бот сам по себе не слушает HTTP, поэтому добавляем заглушку).
"""

import asyncio
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import CommandStart
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db import init_db, search_vacancies, count_vacancies
from llm import ask_llm
from parser import update_vacancies

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
HEALTHCHECK_PORT = int(os.environ.get("PORT", 8080))

bot = None
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я помогу найти IT-вакансии в Уфе.\n"
        "Просто напиши, кого ты ищешь, например:\n"
        "«python разработчик удалённо» или «devops от 150000»."
    )


@dp.message(F.text)
async def handle_query(message: Message):
    try:
        await message.chat.do("typing")
        candidates = search_vacancies(message.text, limit=15)
        answer = ask_llm(message.text, candidates)
        await message.answer(answer)
    except TelegramNetworkError as e:
        logger.warning("Сетевая ошибка Telegram при ответе пользователю: %s", e)
        # не пытаемся повторно отправить — следующее сообщение пользователя
        # обработается штатно, если сеть восстановится


def run_healthcheck_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"ok, vacancies in db: {count_vacancies()}".encode())

        def log_message(self, *args):
            pass  # не засоряем логи health-check запросами

    server = HTTPServer(("0.0.0.0", HEALTHCHECK_PORT), Handler)
    server.serve_forever()


async def main():
    global bot
    if not TG_BOT_TOKEN:
        raise RuntimeError(
            "Не задана переменная окружения TG_BOT_TOKEN. "
            "Получи токен у @BotFather и пропиши его в настройках приложения Amvera."
        )

    init_db()

    # health-check сервер в отдельном потоке, чтобы не блокировать бота
    Thread(target=run_healthcheck_server, daemon=True).start()

    # планировщик: первый сбор вакансий сразу при старте, потом раз в час
    scheduler = AsyncIOScheduler()
    scheduler.add_job(update_vacancies, "interval", hours=1, next_run_time=None)
    scheduler.start()
    await asyncio.to_thread(update_vacancies)

    bot = Bot(token=TG_BOT_TOKEN, session=AiohttpSession(timeout=60))
    logger.info("Бот запущен, начинаю polling...")

    # при временных сетевых сбоях polling не должен умирать насовсем —
    # перезапускаем цикл с паузой вместо падения процесса
    while True:
        try:
            await dp.start_polling(bot)
            break
        except TelegramNetworkError as e:
            logger.warning("Сетевая ошибка при polling, повтор через 5 сек: %s", e)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
