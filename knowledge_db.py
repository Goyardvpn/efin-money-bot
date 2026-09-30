import sqlite3
from pathlib import Path

# Отдельная БД только для базы знаний.
# Основная БД data/efin.db (пользователи, заявки, заработок, тарифы и настройки) не затрагивается.
DB_PATH = Path("data/knowledge.db")


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
