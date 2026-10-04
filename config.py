import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env")


# Telegram ID администратора.
# Можно переопределить переменной окружения ADMIN_ID; если она не задана,
# используется прежнее значение, поведение бота не меняется.
ADMIN_ID = int(os.getenv("ADMIN_ID") or 954997534)
