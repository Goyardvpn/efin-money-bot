import asyncio
import json
import os
import urllib.error
import urllib.request

TOKENBOM_API_URL = "https://tokenbom.com/v1/chat/completions"
TOKENBOM_MODEL = "gpt-5.6-luna"

SYSTEM_PROMPT = """Ты — Efin AI, внутренний помощник компании EFIN.
Отвечай на русском языке, понятно и по делу.
Не выдумывай внутренние правила EFIN, тарифы, выплаты или условия проектов.
Если данных недостаточно, прямо скажи об этом.
"""


def _request(payload, api_key):
    request = urllib.request.Request(
        TOKENBOM_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TokenBom API HTTP {exc.code}: {body[:700]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Не удалось подключиться к TokenBom API: {exc.reason}") from exc


async def ask_efin_ai(bot, user_text: str, knowledge: str = "") -> str:
    api_key = os.getenv("TOKENBOOM_API_KEY")
    if not api_key:
        raise RuntimeError("Не задана переменная окружения TOKENBOOM_API_KEY")

    system = SYSTEM_PROMPT
    if knowledge:
        system += "\n\nБАЗА ЗНАНИЙ EFIN:\n" + knowledge[:12000]

    payload = {
        "model": TOKENBOM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": 1200,
    }

    started = asyncio.get_running_loop().time()
    data = await asyncio.to_thread(_request, payload, api_key)
    elapsed = asyncio.get_running_loop().time() - started
    print(f"[Efin AI] TokenBom ответил за {elapsed:.2f} сек.")

    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("TokenBom API вернул неожиданный формат ответа") from exc

    if not answer or not answer.strip():
        raise RuntimeError("TokenBom API вернул пустой ответ")
    return answer.strip()
