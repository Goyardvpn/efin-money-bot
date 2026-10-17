#!/usr/bin/env python3
"""PreToolUse: блокирует правки файлов с секретами и боевых баз данных.

Claude Code передаёт описание вызова инструмента в stdin (JSON).
Код возврата 2 запрещает действие, текст из stderr показывается Claude.
Любая неожиданная ошибка пропускает действие, чтобы хук не ломал работу.
"""

import json
import sys
from pathlib import PurePosixPath

DB_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm"}


def protection_reason(path):
    posix = PurePosixPath(str(path).replace("\\", "/"))
    name = posix.name

    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "файл с секретами (.env)"

    if "data" in posix.parts and posix.suffix.lower() in DB_SUFFIXES:
        return "боевая база данных (data/*.db)"

    return None


def main():
    try:
        payload = json.load(sys.stdin)
        tool_input = payload.get("tool_input") or {}
        path = tool_input.get("file_path") or tool_input.get("path")
    except Exception:
        return 0

    if not path:
        return 0

    reason = protection_reason(path)
    if reason:
        sys.stderr.write(
            f"Заблокировано: {path} это {reason}. "
            "Не меняй такие файлы. Попроси пользователя сделать это вручную.\n"
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
