import asyncio
import io
import json
import os
import re
import urllib.error
import urllib.request

from knowledge import get_projects

TOKENBOM_API_URL = "https://tokenbom.com/v1/chat/completions"
TOKENBOM_MODEL = "gpt-5.6-luna"

SYSTEM_PROMPT = """Ты — Efin AI, внутренний помощник компании EFIN.
Отвечай на русском языке, понятно и по делу.
База знаний EFIN является главным источником для внутренних вопросов.
Не выдумывай внутренние правила, тарифы, выплаты или условия проектов.
Если нужной информации нет в переданной базе знаний, прямо скажи об этом.
"""

_CACHE = {}


def invalidate_knowledge_cache():
    _CACHE.clear()


def _decode(data):
    for encoding in ("utf-8", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def _extract(data, file_name, mime_type):
    name = (file_name or "").lower()
    mime = (mime_type or "").lower()
    if name.endswith(".txt") or "text/plain" in mime:
        return _decode(data)
    if name.endswith(".pdf") or "application/pdf" in mime:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    if name.endswith(".docx") or "wordprocessingml.document" in mime:
        from docx import Document
        document = Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs if p.text.strip())
    return _decode(data)


async def _project_text(bot, project):
    cached = _CACHE.get(project["id"])
    if cached and cached["file_id"] == project["file_id"]:
        return cached["text"]
    telegram_file = await bot.get_file(project["file_id"])
    data = bytes(await telegram_file.download_as_bytearray())
    text = _extract(data, project["file_name"], project["mime_type"]).strip()
    _CACHE[project["id"]] = {"file_id": project["file_id"], "text": text}
    return text


def _relevant(text, query, limit=4500):
    if not text:
        return ""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    words = set(re.findall(r"[а-яa-z0-9ё-]{3,}", query.lower()))
    scored = []
    for index, paragraph in enumerate(paragraphs):
        low = paragraph.lower()
        score = sum(1 for word in words if word in low)
        scored.append((score, index, paragraph))
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = [item for item in scored if item[0] > 0][:15] or scored[:6]
    result = []
    total = 0
    for _, index, paragraph in selected:
        block = f"Фрагмент {index + 1}:\n{paragraph}"
        if total + len(block) > limit:
            break
        result.append(block)
        total += len(block)
    return "\n\n".join(result)


async def build_knowledge_context(bot, user_text):
    projects = get_projects()
    if not projects:
        return "База знаний EFIN пока пуста."
    parts = []
    for project in projects:
        try:
            text = await _project_text(bot, project)
            relevant = _relevant(text, user_text)
            if relevant:
                parts.append(f"=== ПРОЕКТ: {project['name']} ===\n{relevant}")
        except Exception as exc:
            print(f"[Efin AI] Не удалось прочитать {project['name']}: {exc}")
    if not parts:
        return "В базе знаний EFIN нет найденного фрагмента по этому вопросу."
    return "\n\n".join(parts)[:12000]


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


async def ask_efin_ai(bot, user_text: str) -> str:
    api_key = os.getenv("TOKENBOOM_API_KEY")
    if not api_key:
        raise RuntimeError("Не задана переменная окружения TOKENBOOM_API_KEY")

    knowledge = await build_knowledge_context(bot, user_text)
    print(f"[Efin AI] Контекст базы: {len(knowledge)} символов")
    payload = {
        "model": TOKENBOM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\nБАЗА ЗНАНИЙ EFIN:\n" + knowledge},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": 1200,
    }
    started = asyncio.get_running_loop().time()
    data = await asyncio.to_thread(_request, payload, api_key)
    print(f"[Efin AI] TokenBom ответил за {asyncio.get_running_loop().time() - started:.2f} сек.")
    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("TokenBom API вернул неожиданный формат ответа") from exc
    if not answer or not answer.strip():
        raise RuntimeError("TokenBom API вернул пустой ответ")
    return answer.strip()
