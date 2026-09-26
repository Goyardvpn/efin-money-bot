import asyncio
import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from knowledge import get_projects, get_project_files

TOKENBOM_API_URL = "https://tokenbom.com/v1/chat/completions"
TOKENBOM_MODEL = "gpt-5.6-luna"
MEDIA_DIR = Path("data/knowledge_media")
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = """Ты — Efin AI, внутренний помощник компании EFIN.
Отвечай на русском языке, понятно и по делу.
База знаний EFIN — главный источник для внутренних вопросов.

Правила:
1. Не выдумывай внутренние правила, тарифы, выплаты, инструкции или условия.
2. Используй материалы всех файлов проекта, а не только первого файла.
3. Если вопрос относится к конкретному проекту, опирайся на материалы этого проекта.
4. Если пользователь просит фото, скриншот, изображение или пример, используй только реально подходящие изображения.
5. Нельзя считать изображение подходящим только потому, что оно находится в той же памятке.
6. Если подходящего изображения нет, честно скажи, что его нет в переданных материалах.
7. Если подходящее изображение есть, добавь в конце ответа ровно [SEND_IMAGES].
8. Если подходящего изображения нет, НЕ добавляй [SEND_IMAGES].
9. Не утверждай, что изображено то, чего нельзя подтвердить по самому изображению.
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


def _media_dir(project_id, file_key):
    directory = MEDIA_DIR / str(project_id) / str(file_key)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _save_image(project_id, file_key, index, image_bytes, suffix, name, context="", page=None):
    suffix = suffix.lower() if suffix else ".png"
    if not suffix.startswith("."):
        suffix = "." + suffix
    path = _media_dir(project_id, file_key) / f"{index:03d}{suffix}"
    path.write_bytes(image_bytes)
    return {"path": str(path), "name": name or path.name, "context": context or "", "page": page, "description": ""}


def _extract_pdf(data, project_id, file_key):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    text_parts, images = [], []
    image_index = 0
    for page_number, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            text_parts.append(f"Страница {page_number}:\n{text}")
        try:
            for image in page.images:
                image_index += 1
                name = image.name or f"page_{page_number}_{image_index}.png"
                suffix = Path(name).suffix.lower() or ".png"
                images.append(_save_image(project_id, file_key, image_index, image.data, suffix, f"Страница {page_number} — {name}", text, page_number))
        except Exception as exc:
            print(f"[Efin AI] Ошибка извлечения изображений PDF: {exc}")
    return "\n\n".join(text_parts), images


def _extract_pptx(data, project_id, file_key):
    from pptx import Presentation
    presentation = Presentation(io.BytesIO(data))
    text_parts, images = [], []
    image_index = 0
    for slide_number, slide in enumerate(presentation.slides, 1):
        slide_text = []
        for shape in slide.shapes:
            try:
                if getattr(shape, "has_text_frame", False) and shape.text.strip():
                    slide_text.append(shape.text.strip())
            except Exception:
                pass
        context = "\n".join(slide_text)
        if context:
            text_parts.append(f"Слайд {slide_number}:\n{context}")
        for shape in slide.shapes:
            if getattr(shape, "shape_type", None) != 13:
                continue
            try:
                image_index += 1
                ext = "." + (shape.image.ext or "png").lower().lstrip(".")
                images.append(_save_image(project_id, file_key, image_index, shape.image.blob, ext, f"Слайд {slide_number} — изображение {image_index}", context, slide_number))
            except Exception as exc:
                print(f"[Efin AI] Ошибка извлечения изображения PPTX: {exc}")
    return "\n\n".join(text_parts), images


def _extract(data, file_name, mime_type, project_id, file_key):
    name = (file_name or "").lower()
    mime = (mime_type or "").lower()
    if name.endswith(".txt") or "text/plain" in mime:
        return _decode(data), []
    if name.endswith(".pdf") or "application/pdf" in mime:
        return _extract_pdf(data, project_id, file_key)
    if name.endswith(".pptx") or "presentationml.presentation" in mime:
        return _extract_pptx(data, project_id, file_key)
    if name.endswith(".docx") or "wordprocessingml.document" in mime:
        from docx import Document
        document = Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs if p.text.strip()), []
    if name.endswith((".jpg", ".jpeg", ".png", ".webp")) or mime.startswith("image/"):
        suffix = Path(name).suffix.lower() or ".jpg"
        return "Изображение из базы знаний.", [_save_image(project_id, file_key, 1, data, suffix, file_name or "изображение", "Изображение из базы знаний EFIN.")]
    return _decode(data), []


def _image_data_url(path):
    data = Path(path).read_bytes()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(Path(path).suffix.lower(), "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _request(payload, api_key, timeout=90):
    request = urllib.request.Request(
        TOKENBOM_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TokenBom API HTTP {exc.code}: {body[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Не удалось подключиться к TokenBom API: {exc.reason}") from exc


def _analyse_image_sync(image, api_key):
    if not api_key:
        return ""
    try:
        prompt = f"""Проанализируй изображение из внутренней базы знаний EFIN.
Создай точное поисковое описание для сотрудника.
Текст рядом с изображением:
{image.get('context','')[:5000]}

Обязательно укажи только подтверждаемое:
- что именно изображено;
- есть ли человек и является ли это примером фотографии клиента;
- документ, карта, телефон, экран, QR/штрихкод, логотип или другой объект;
- ключевые слова, по которым сотрудник может искать это изображение.
Не придумывай отсутствующие детали. Ответь на русском одним структурированным описанием."""
        payload = {
            "model": TOKENBOM_MODEL,
            "messages": [
                {"role": "system", "content": "Ты анализируешь изображения. Описывай только подтверждаемое."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _image_data_url(image["path"])}},
                ]},
            ],
            "max_tokens": 600,
        }
        data = _request(payload, api_key)
        return str(data["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:
        print(f"[Efin AI] Ошибка анализа изображения {image.get('name')}: {exc}")
        return ""


async def _analyse_images(images, api_key):
    tasks = [asyncio.to_thread(_analyse_image_sync, image, api_key) for image in images if not image.get("description")]
    if not tasks:
        return images
    results = await asyncio.gather(*tasks, return_exceptions=True)
    index = 0
    for image in images:
        if image.get("description"):
            continue
        result = results[index]
        index += 1
        image["description"] = "" if isinstance(result, Exception) else (result or "")
    return images


async def _load_one_file(bot, project, file_row):
    cache_key = (project["id"], file_row["id"], file_row["file_id"])
    if cache_key in _CACHE:
        return _CACHE[cache_key]
    telegram_file = await bot.get_file(file_row["file_id"])
    data = bytes(await telegram_file.download_as_bytearray())
    text, images = _extract(data, file_row["file_name"], file_row["mime_type"], project["id"], file_row["id"])
    api_key = os.getenv("TOKENBOOM_API_KEY")
    if images:
        images = await _analyse_images(images, api_key)
    result = {"file_id": file_row["file_id"], "file_name": file_row["file_name"], "text": text.strip(), "images": images}
    _CACHE[cache_key] = result
    return result


async def _project_data(bot, project):
    files = get_project_files(project["id"])
    all_text, all_images = [], []
    for file_row in files:
        try:
            data = await _load_one_file(bot, project, file_row)
            all_text.append(f"=== ФАЙЛ: {file_row['file_name']} ===\n{data['text']}")
            all_images.extend(data["images"])
        except Exception as exc:
            print(f"[Efin AI] Не удалось прочитать файл {file_row['file_name']}: {exc}")
    print(f"[Efin AI] Проект {project['name']}: обработано файлов {len(files)}, изображений {len(all_images)}")
    return {"text": "\n\n".join(all_text), "images": all_images}


def _words(text):
    return set(re.findall(r"[а-яa-z0-9ё-]{3,}", (text or "").lower()))


def _relevant(text, query, limit=6000):
    if not text:
        return ""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    words = _words(query)
    scored = []
    for index, paragraph in enumerate(paragraphs):
        low = paragraph.lower()
        score = sum(1 for word in words if word in low)
        scored.append((score, index, paragraph))
    scored.sort(key=lambda x: (-x[0], x[1]))
    selected = [x for x in scored if x[0] > 0][:20] or scored[:8]
    result, total = [], 0
    for _, index, paragraph in selected:
        block = f"Фрагмент {index + 1}:\n{paragraph}"
        if total + len(block) > limit:
            break
        result.append(block)
        total += len(block)
    return "\n\n".join(result)


def _visual_query(query):
    text = (query or "").lower()
    return any(token in text for token in (
        "фото", "фотограф", "фотографию", "фотография", "сфот", "изображ", "картин",
        "пример", "скрин", "скриншот", "снимок", "покажи", "пришли", "показывай",
        "как выглядит", "как правильно", "камера", "визуал"
    ))


def _score_image(image, query):
    words = _words(query)
    searchable = " ".join([
        image.get("name", ""),
        image.get("context", ""),
        image.get("description", ""),
    ]).lower()
    if not words or not searchable:
        return 0
    score = 0
    for word in words:
        if word in searchable:
            score += 1
            if len(word) >= 6:
                score += 2
    # Extra weight for common visual intent terms.
    for group in (("клиент", "клиента", "клиентом"), ("фото", "фотография", "изображение"), ("пример", "образец"), ("карта", "документ")):
        if any(w in words for w in group) and any(w in searchable for w in group):
            score += 4
    return score


def _select_images(images, query, max_images=6):
    if not images or not _visual_query(query):
        return []
    scored = sorted(((_score_image(img, query), i, img) for i, img in enumerate(images)), key=lambda x: (-x[0], x[1]))
    return [item[2] for item in scored if item[0] > 0][:max_images]


async def build_knowledge_context(bot, user_text):
    projects = get_projects()
    if not projects:
        return "База знаний EFIN пока пуста.", []
    parts, selected_images = [], []
    for project in projects:
        try:
            data = await _project_data(bot, project)
            relevant = _relevant(data["text"], user_text)
            if relevant:
                parts.append(f"=== ПРОЕКТ: {project['name']} ===\n{relevant}")
            selected_images.extend(_select_images(data["images"], user_text))
        except Exception as exc:
            print(f"[Efin AI] Не удалось прочитать проект {project['name']}: {exc}")
    unique = []
    seen = set()
    for image in selected_images:
        if image["path"] not in seen:
            seen.add(image["path"])
            unique.append(image)
    context = "\n\n".join(parts)[:18000]
    if not context:
        context = "В базе знаний EFIN нет найденного текстового фрагмента по этому вопросу."
    print(f"[Efin AI] Контекст базы: {len(context)} символов; релевантных изображений: {len(unique[:6])}")
    return context, unique[:6]


async def ask_efin_ai(bot, user_text):
    api_key = os.getenv("TOKENBOOM_API_KEY")
    if not api_key:
        raise RuntimeError("Не задана переменная окружения TOKENBOOM_API_KEY")
    knowledge, images = await build_knowledge_context(bot, user_text)
    system_text = SYSTEM_PROMPT + "\n\nБАЗА ЗНАНИЙ EFIN:\n" + knowledge
    user_content = [{"type": "text", "text": user_text}]
    for index, image in enumerate(images, 1):
        user_content.append({"type": "text", "text": f"Изображение {index}. Файл/страница: {image['name']}.\nОписание AI: {image.get('description','')[:3500]}\nТекст рядом: {image.get('context','')[:2000]}"})
        user_content.append({"type": "image_url", "image_url": {"url": _image_data_url(image["path"])}})
    payload = {
        "model": TOKENBOM_MODEL,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 1400,
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
    send_images = "[SEND_IMAGES]" in answer
    clean = answer.replace("[SEND_IMAGES]", "").strip()
    if send_images and not images:
        send_images = False
    return {"answer": clean, "images": images if send_images else []}
