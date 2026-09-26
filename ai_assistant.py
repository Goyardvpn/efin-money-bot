import asyncio
import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from knowledge import get_projects

TOKENBOM_API_URL = "https://tokenbom.com/v1/chat/completions"
TOKENBOM_MODEL = "gpt-5.6-luna"
MEDIA_DIR = Path("data/knowledge_media")
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = """Ты — Efin AI, внутренний помощник компании EFIN.
Отвечай на русском языке, понятно и по делу.
База знаний EFIN является главным источником для внутренних вопросов.
Не выдумывай внутренние правила, тарифы, выплаты или условия проектов.
Если нужной информации нет в переданной базе знаний, прямо скажи об этом.
Если к запросу приложены изображения из памяток, используй их как источник информации.
Если пользователь просит показать/прислать фото, схему или пример, в конце ответа добавь ровно маркер [SEND_IMAGES].
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


def _safe_media_dir(project_id):
    directory = MEDIA_DIR / str(project_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _save_image(project_id, index, image_bytes, suffix, source_name):
    directory = _safe_media_dir(project_id)
    path = directory / f"{index:03d}{suffix}"
    path.write_bytes(image_bytes)
    return {"path": str(path), "name": source_name or path.name}


def _extract_pptx(data, project_id):
    from pptx import Presentation
    presentation = Presentation(io.BytesIO(data))
    text_parts, images = [], []
    image_index = 0
    for slide_number, slide in enumerate(presentation.slides, start=1):
        slide_text = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                value = shape.text.strip()
                if value:
                    slide_text.append(value)
            if getattr(shape, "shape_type", None) == 13:
                try:
                    image_index += 1
                    ext = "." + (shape.image.ext or "png").lower().lstrip(".")
                    images.append(_save_image(project_id, image_index, shape.image.blob, ext, f"Слайд {slide_number} — изображение {image_index}"))
                except Exception:
                    pass
        if slide_text:
            text_parts.append(f"Слайд {slide_number}:\n" + "\n".join(slide_text))
    return "\n\n".join(text_parts), images


def _extract_pdf(data, project_id):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    text_parts, images = [], []
    image_index = 0
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            text_parts.append(f"Страница {page_number}:\n{text.strip()}")
        try:
            for image in page.images:
                image_index += 1
                name = image.name or f"page_{page_number}_{image_index}.png"
                suffix = Path(name).suffix.lower() or ".png"
                images.append(_save_image(project_id, image_index, image.data, suffix, f"Страница {page_number} — {name}"))
        except Exception:
            pass
    return "\n\n".join(text_parts), images


def _extract(data, file_name, mime_type, project_id):
    name = (file_name or "").lower()
    mime = (mime_type or "").lower()
    if name.endswith(".txt") or "text/plain" in mime:
        return _decode(data), []
    if name.endswith(".pdf") or "application/pdf" in mime:
        return _extract_pdf(data, project_id)
    if name.endswith(".docx") or "wordprocessingml.document" in mime:
        from docx import Document
        document = Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs if p.text.strip()), []
    if name.endswith(".pptx") or "presentationml.presentation" in mime:
        return _extract_pptx(data, project_id)
    if name.endswith((".jpg", ".jpeg", ".png", ".webp")) or mime.startswith("image/"):
        suffix = Path(name).suffix.lower() or ".jpg"
        return "Изображение из базы знаний.", [_save_image(project_id, 1, data, suffix, file_name or "изображение")]
    return _decode(data), []


async def _project_data(bot, project):
    cached = _CACHE.get(project["id"])
    if cached and cached["file_id"] == project["file_id"]:
        return cached
    telegram_file = await bot.get_file(project["file_id"])
    data = bytes(await telegram_file.download_as_bytearray())
    text, images = _extract(data, project["file_name"], project["mime_type"], project["id"])
    result = {"file_id": project["file_id"], "text": text.strip(), "images": images}
    _CACHE[project["id"]] = result
    return result


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
    result, total = [], 0
    for _, index, paragraph in selected:
        block = f"Фрагмент {index + 1}:\n{paragraph}"
        if total + len(block) > limit:
            break
        result.append(block)
        total += len(block)
    return "\n\n".join(result)


def _visual_query(query):
    words = (query or "").lower()
    return any(token in words for token in ("фото", "фотограф", "сфот", "изображ", "картин", "пример", "скрин", "снимок", "покажи", "пришли", "показывай", "как выглядит", "как правильно", "визуал", "камера"))


async def build_knowledge_context(bot, user_text):
    projects = get_projects()
    if not projects:
        return "База знаний EFIN пока пуста.", []
    parts, selected_images = [], []
    visual = _visual_query(user_text)
    for project in projects:
        try:
            data = await _project_data(bot, project)
            relevant = _relevant(data["text"], user_text)
            if relevant:
                parts.append(f"=== ПРОЕКТ: {project['name']} ===\n{relevant}")
                if visual:
                    selected_images.extend(data["images"][:4])
            elif visual and data["images"]:
                selected_images.extend(data["images"][:2])
        except Exception as exc:
            print(f"[Efin AI] Не удалось прочитать {project['name']}: {exc}")
    context = "\n\n".join(parts)[:12000]
    return context or "В базе знаний EFIN нет найденного текстового фрагмента по этому вопросу.", selected_images[:6]


def _image_data_url(path):
    data = Path(path).read_bytes()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(Path(path).suffix.lower(), "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _request(payload, api_key):
    request = urllib.request.Request(TOKENBOM_API_URL, data=json.dumps(payload).encode("utf-8"), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TokenBom API HTTP {exc.code}: {body[:700]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Не удалось подключиться к TokenBom API: {exc.reason}") from exc


async def ask_efin_ai(bot, user_text):
    api_key = os.getenv("TOKENBOOM_API_KEY")
    if not api_key:
        raise RuntimeError("Не задана переменная окружения TOKENBOOM_API_KEY")
    knowledge, images = await build_knowledge_context(bot, user_text)
    print(f"[Efin AI] Контекст базы: {len(knowledge)} символов; изображений: {len(images)}")
    system_text = SYSTEM_PROMPT + "\n\nБАЗА ЗНАНИЙ EFIN:\n" + knowledge
    user_content = [{"type": "text", "text": user_text}]
    for index, image in enumerate(images, start=1):
        user_content.append({"type": "text", "text": f"Изображение {index}: {image['name']}"})
        user_content.append({"type": "image_url", "image_url": {"url": _image_data_url(image["path"])}})
    payload = {"model": TOKENBOM_MODEL, "messages": [{"role": "system", "content": system_text}, {"role": "user", "content": user_content}], "max_tokens": 1200}
    started = asyncio.get_running_loop().time()
    data = await asyncio.to_thread(_request, payload, api_key)
    print(f"[Efin AI] TokenBom ответил за {asyncio.get_running_loop().time() - started:.2f} сек.")
    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("TokenBom API вернул неожиданный формат ответа") from exc
    if not answer or not answer.strip():
        raise RuntimeError("TokenBom API вернул пустой ответ")
    send_images = "[SEND_IMAGES]" in answer
    return {"answer": answer.replace("[SEND_IMAGES]", "").strip(), "images": images if send_images else []}
