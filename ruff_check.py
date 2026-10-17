#!/usr/bin/env python3
"""PostToolUse: после правки .py файла запускает Ruff и показывает ошибки Claude.

Правила описаны в ruff.toml (только настоящие ошибки, без форматирования).
Если Ruff не установлен, хук молча ничего не делает.
Код возврата 2 отправляет текст из stderr обратно Claude, чтобы он исправил.
"""

import json
import os
import shutil
import subprocess
import sys


def main():
    try:
        payload = json.load(sys.stdin)
        tool_input = payload.get("tool_input") or {}
        path = tool_input.get("file_path") or ""
    except Exception:
        return 0

    if not path.endswith(".py") or not os.path.isfile(path):
        return 0

    ruff = shutil.which("ruff")
    if not ruff:
        return 0

    try:
        result = subprocess.run(
            [ruff, "check", path],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.environ.get("CLAUDE_PROJECT_DIR") or None,
        )
    except Exception:
        return 0

    if result.returncode == 0:
        return 0

    sys.stderr.write("Ruff нашёл проблемы, исправь их:\n" + (result.stdout or result.stderr))
    return 2


if __name__ == "__main__":
    sys.exit(main())
