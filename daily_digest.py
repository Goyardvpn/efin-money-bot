"""Утренняя рассылка в 07:00 по Москве: прогноз погоды в Москве и мотивационная цитата.

Подключается одной строкой в run.py: daily_digest.install().

Переменные окружения (все необязательные):
    DAILY_DIGEST=off            полностью отключить ежедневную рассылку
    DAILY_DIGEST_ONLY_ADMIN=1   слать только администратору (удобно для проверки)

Администратор может в любой момент командой /digest получить такое же
сообщение прямо сейчас, не дожидаясь 07:00.

Для работы расписания нужен пакет python-telegram-bot с job-queue
(в requirements.txt: python-telegram-bot[job-queue]).
"""

import asyncio
import json
import os
import urllib.parse
import urllib.request
from datetime import date, time, timezone

from telegram.error import Forbidden, TelegramError
from telegram.ext import Application, CommandHandler, filters

from config import ADMIN_ID
from database import get_users

# 07:00 по Москве = 04:00 UTC. В Москве нет перехода на летнее время (UTC+3 круглый год),
# поэтому фиксированное UTC-время надёжнее и не зависит от базы часовых поясов на сервере.
SEND_TIME_UTC = time(hour=4, minute=0, tzinfo=timezone.utc)

MOSCOW_LAT = 55.7558
MOSCOW_LON = 37.6173
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_TIMEOUT = 10  # секунд

# Коды погоды WMO, которые отдаёт Open-Meteo: код -> (эмодзи, описание).
_WEATHER_CODES = {
    0: ("☀️", "ясно"),
    1: ("🌤", "преимущественно ясно"),
    2: ("⛅", "переменная облачность"),
    3: ("☁️", "пасмурно"),
    45: ("🌫", "туман"),
    48: ("🌫", "изморозь и туман"),
    51: ("🌦", "лёгкая морось"),
    53: ("🌦", "морось"),
    55: ("🌦", "сильная морось"),
    56: ("🌧", "ледяная морось"),
    57: ("🌧", "сильная ледяная морось"),
    61: ("🌧", "небольшой дождь"),
    63: ("🌧", "дождь"),
    65: ("🌧", "сильный дождь"),
    66: ("🌧", "ледяной дождь"),
    67: ("🌧", "сильный ледяной дождь"),
    71: ("🌨", "небольшой снег"),
    73: ("❄️", "снег"),
    75: ("❄️", "сильный снегопад"),
    77: ("❄️", "снежные зёрна"),
    80: ("🌦", "небольшие ливни"),
    81: ("🌧", "ливни"),
    82: ("⛈", "сильные ливни"),
    85: ("🌨", "снежные заряды"),
    86: ("🌨", "сильные снежные заряды"),
    95: ("⛈", "гроза"),
    96: ("⛈", "гроза с градом"),
    99: ("⛈", "сильная гроза с градом"),
}

QUOTES = [
    "Начни с малого, но начни сегодня — завтра будет проще.",
    "Каждая встреча — шаг к результату. Сделай сегодняшний шаг уверенным.",
    "Результат любит тех, кто не откладывает.",
    "Не жди идеального момента: он создаётся действиями.",
    "Маленькие ежедневные усилия побеждают редкие большие рывки.",
    "Отказ — это не конец, а информация. Забери урок и иди дальше.",
    "Сильные не те, у кого всё получается, а те, кто продолжает после неудач.",
    "Хороший день начинается с ясной цели. Выбери главное дело и сделай его первым.",
    "Дисциплина — это когда делаешь, даже если не хочется.",
    "Ты ближе к цели, чем кажется. Продолжай.",
    "Сегодня ты можешь сделать то, что вчера откладывал.",
    "Уверенность растёт из действий, а не из ожидания.",
    "Не сравнивай свой первый шаг с чужим сотым.",
    "Победа складывается из десятков спокойных, правильных решений.",
    "Хочешь изменить результат — измени сегодняшнее действие.",
    "Энергия идёт за вниманием. Направь её на то, что приближает к цели.",
    "Трудности — это тренажёр: без нагрузки мышцы не растут.",
    "Лучшее время для старта было вчера, второе лучшее — прямо сейчас.",
    "Не бойся ошибиться — бойся не попробовать.",
    "Первая встреча дня задаёт тон всему дню. Начни её с улыбки.",
    "Один звонок, одно сообщение, одна встреча — так строятся большие результаты.",
    "Терпение и настойчивость открывают двери, которые не открывает талант.",
    "Сфокусируйся на процессе — результат придёт сам.",
    "Новый день — чистый лист. Напиши на нём что-то стоящее.",
    "Сложно не значит невозможно. Это значит — интересно.",
    "Твой темп — это твой темп. Главное, чтобы он не останавливался.",
    "Привычки решают больше, чем настроение.",
    "Расти понемногу каждый день — через год себя не узнаешь.",
    "Начни с самого трудного, и остальной день пройдёт легче.",
    "Благодарность за вчерашнее — топливо для сегодняшнего.",
    "Командная работа превращает хорошие идеи в большие результаты.",
    "Спокойствие и ясная голова зарабатывают больше, чем суета.",
    "Не нужно быть лучшим во всём. Нужно быть лучше, чем вчера.",
    "Сделанное неидеально лучше задуманного идеально.",
]


def quote_of_the_day(today=None):
    """Цитата выбирается по дате: каждый день новая, без повторов до конца списка."""
    today = today or date.today()
    return QUOTES[today.toordinal() % len(QUOTES)]


def _temp(value):
    rounded = round(value)
    return "0°" if rounded == 0 else f"{rounded:+d}°"


def _fetch_weather():
    """Синхронный запрос прогноза на сегодня. Возвращает dict или бросает исключение."""
    query = urllib.parse.urlencode({
        "latitude": MOSCOW_LAT,
        "longitude": MOSCOW_LON,
        "daily": ",".join([
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "wind_speed_10m_max",
        ]),
        "timezone": "Europe/Moscow",
        "forecast_days": 1,
    })
    request = urllib.request.Request(
        f"{WEATHER_URL}?{query}",
        headers={"User-Agent": "efin-money-bot"},
    )
    with urllib.request.urlopen(request, timeout=WEATHER_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8"))

    daily = data["daily"]
    return {key: values[0] for key, values in daily.items() if key != "time" and values}


def format_weather(weather):
    """Превращает ответ API в читаемый блок текста."""
    emoji, description = _WEATHER_CODES.get(weather.get("weather_code"), ("🌡", "без описания"))
    lines = [f"{emoji} Погода в Москве на сегодня: {description}"]

    t_max = weather.get("temperature_2m_max")
    t_min = weather.get("temperature_2m_min")
    if t_max is not None and t_min is not None:
        lines.append(f"🌡 Днём до {_temp(t_max)}, ночью около {_temp(t_min)}")
    elif t_max is not None:
        lines.append(f"🌡 Днём до {_temp(t_max)}")

    rain = weather.get("precipitation_probability_max")
    if rain is not None:
        lines.append(f"☔ Вероятность осадков: {round(rain)}%")

    wind_kmh = weather.get("wind_speed_10m_max")
    if wind_kmh is not None:
        # API отдаёт км/ч, переводим в м/с.
        lines.append(f"💨 Ветер до {round(wind_kmh / 3.6)} м/с")

    return "\n".join(lines)


async def build_digest_text():
    try:
        weather = await asyncio.wait_for(
            asyncio.to_thread(_fetch_weather),
            timeout=WEATHER_TIMEOUT + 5,
        )
        weather_block = format_weather(weather)
    except Exception as error:
        print(f"[Daily digest] Не удалось получить погоду: {type(error).__name__}: {error}")
        weather_block = "🌡 Прогноз погоды сейчас недоступен."

    return (
        "☀️ Доброе утро!\n\n"
        f"{weather_block}\n\n"
        f"💪 {quote_of_the_day()}\n\n"
        "Хорошего дня!"
    )


def _recipient_ids():
    if os.getenv("DAILY_DIGEST_ONLY_ADMIN", "").strip().lower() in {"1", "true", "yes", "on"}:
        return [ADMIN_ID]

    ids = [user["user_id"] for user in get_users() if not user["is_blocked"]]
    if ADMIN_ID not in ids:
        ids.append(ADMIN_ID)
    return ids


async def send_daily_digest(context):
    text = await build_digest_text()
    recipients = _recipient_ids()

    sent = 0
    failed = 0
    for user_id in recipients:
        try:
            await context.bot.send_message(chat_id=user_id, text=text)
            sent += 1
        except Forbidden:
            # Пользователь заблокировал бота: это не ошибка, просто пропускаем.
            failed += 1
        except TelegramError as error:
            failed += 1
            print(f"[Daily digest] Не удалось отправить user_id={user_id}: {error}")

        # Небольшая пауза, чтобы не упереться в лимиты Telegram.
        await asyncio.sleep(0.05)

    print(f"[Daily digest] Рассылка завершена: отправлено {sent}, не доставлено {failed}")


async def _digest_command(update, context):
    """/digest — администратор получает утреннее сообщение прямо сейчас."""
    await update.message.reply_text(await build_digest_text())


def _schedule(application):
    if application.bot_data.get("_efin_daily_digest"):
        return
    application.bot_data["_efin_daily_digest"] = True

    application.add_handler(
        CommandHandler("digest", _digest_command, filters=filters.User(user_id=ADMIN_ID))
    )

    if os.getenv("DAILY_DIGEST", "on").strip().lower() in {"off", "0", "false", "no"}:
        print("[Daily digest] Расписание отключено переменной DAILY_DIGEST")
        return

    if application.job_queue is None:
        print(
            "[Daily digest] ⚠️ JobQueue недоступен: в requirements.txt должен быть "
            "python-telegram-bot[job-queue]. Расписание не создано, команда /digest работает."
        )
        return

    application.job_queue.run_daily(
        send_daily_digest,
        time=SEND_TIME_UTC,
        name="daily_digest",
    )
    print("[Daily digest] Рассылка запланирована на 07:00 МСК")


_installed = False


def install():
    """Подключается к Application так же, как knowledge_bootstrap: через run_polling."""
    global _installed
    if _installed:
        return
    _installed = True

    original_run_polling = Application.run_polling

    def run_polling_with_digest(self, *args, **kwargs):
        _schedule(self)
        return original_run_polling(self, *args, **kwargs)

    Application.run_polling = run_polling_with_digest
