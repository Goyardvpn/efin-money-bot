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

ВАЖНО ДЛЯ ИЗОБРАЖЕНИЙ:
- Изображения с номерами прикреплены к конкретным страницам PDF или слайдам PPTX.
- В описании каждого изображения указан текст страницы/слайда, из которого оно взято.
- Если пользователь просит фото, скриншот, схему или визуальный пример, выбирай ТОЛЬКО изображения, которые действительно соответствуют запросу.
- Нельзя выбирать изображение только потому, что оно находится в том же проекте.
- Если подходящего изображения среди переданных нет, НЕ добавляй маркер отправки изображения.
- Если подходящее изображение есть, в конце ответа добавь ровно один маркер вида [SEND_IMAGES: 1] или [SEND_IMAGES: 1,3]. Номера должны соответствовать изображениям из сообщения.
- Если пользователь НЕ просит изображение, маркер [SEND_IMAGES: ...] не добавляй.

При выборе изображения ориентируйся прежде всего на смысл текста страницы/слайда и подпись изображения.
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


def _save_image(project_id, index, image_bytes, suffix, source_name, context=""):
    directory = _safe_media_dir(project_id)
    path = directory / f"{index:03d}{suffix}"
    path.write_bytes(image_bytes)
    return {
        "path": str(path),
        "name": source_name or path.name,
        "context": context.strip(),
    }


def _extract_pptx(data, project_id):
    from pptx import Presentation

    presentation = Presentation(io.BytesIO(data))
    text_parts = []
    images = []
    image_index = 0

    for slide_number, slide in enumerate(presentation.slides, start=1):
        slide_text = []

        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                value = shape.text.strip()
                if value:
                    slide_text.append(value)

        slide_context = " ".join(slide_text).strip()
        if slide_context:
            text_parts.append(f"Слайд {slide_number}:\n{slide_context}")

        for shape in slide.shapes:
            if getattr(shape, "shape_type", None) != 13:
                continue
            try:
                image_index += 1
                ext = "." + (shape.image.ext or "png").lower().lstrip(".")
                images.append(
                    _save_image(
                        project_id,
                        image_index,
                        shape.image.blob,
                        ext,
                        f"Слайд {slide_number} — изображение {image_index}",
                        f"Проект/слайд: Слайд {slide_number}. Текст слайда: {slide_context}",
                    )
                )
            except Exception as exc:
                print(f"[Efin AI] Не удалось извлечь изображение со слайда {slide_number}: {exc}")

    return "\n\n".join(text_parts), images


def _extract_pdf(data, project_id):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    text_parts = []
    images = []
    image_index = 0

    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        page_context = text

        if page_context:
            text_parts.append(f"Страница {page_number}:\n{page_context}")

        try:
            for image in page.images:
                image_index += 1
                name = image.name or f"page_{page_number}_{image_index}.png"
                suffix = Path(name).suffix.lower() or ".png"
                images.append(
                    _save_image(
                        project_id,
                        image_index,
                        image.data,
                        suffix,
                        f"Страница {page_number} — {name}",
                        f"Проект/страница: Страница {page_number}. Текст страницы: {page_context}",
                    )
                )
        except Exception as exc:
            print(f"[Efin AI] Не удалось извлечь изображения со страницы {page_number}: {exc}")

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
        return (
            "Изображение из базы знаний.",
            [_save_image(project_id, 1, data, suffix, file_name or "изображение", "Отдельное изображение из базы знаний.")],
        )

    return _decode(data), []


async def _project_data(bot, project):
    cached = _CACHE.get(project["id"])
    if cached and cached["file_id"] == project["file_id"]:
        return cached

    telegram_file = await bot.get_file(project["file_id"])
    data = bytes(await telegram_file.download_as_bytearray())
    text, images = _extract(
        data,
        project["file_name"],
        project["mime_type"],
        project["id"],
    )

    result = {
        "file_id": project["file_id"],
        "text": text.strip(),
        "images": images,
        "project_name": project["name"],
    }
    _CACHE[project["id"]] = result
    return result


def _query_words(query):
    return set(re.findall(r"[а-яa-z0-9ё-]{3,}", (query or "").lower()))


def _relevant(text, query, limit=4500):
    if not text:
        return ""

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    words = _query_words(query)
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


def _visual_query(query):
    words = (query or "").lower()
    return any(
        token in words
        for token in (
            "фото",
            "фотограф",
            "сфот",
            "изображ",
            "картин",
            "пример",
            "скрин",
            "снимок",
            "покажи",
            "пришли",
            "показывай",
            "как выглядит",
            "как правильно",
            "визуал",
            "камера",
        )
    )


def _score_image(image, query, project_name=""):
    query_words = _query_words(query)
    haystack = " ".join(
        [
            image.get("name", ""),
            image.get("context", ""),
            project_name,
        ]
    ).lower()

    score = sum(1 for word in query_words if word in haystack)

    # Дополнительный вес для слов, особенно важных для поиска фото.
    important = (
        "клиент",
        "клиента",
        "фото",
        "фотограф",
        "фотографировать",
        "сфотографировать",
        "пример",
        "камера",
        "паспорт",
        "лицо",
        "карта",
    )
    for word in important:
        if word in query_words and word in haystack:
            score += 3

    return score


async def build_knowledge_context(bot, user_text):
    projects = get_projects()
    if not projects:
        return "База знаний EFIN пока пуста.", []

    parts = []
    image_candidates = []
    visual = _visual_query(user_text)

    for project in projects:
        try:
            data = await _project_data(bot, project)
            relevant = _relevant(data["text"], user_text)

            if relevant:
                parts.append(f"=== ПРОЕКТ: {project['name']} ===\n{relevant}")

            if visual and data["images"]:
                for image in data["images"]:
                    candidate = dict(image)
                    candidate["project_name"] = project["name"]
                    candidate["score"] = _score_image(image, user_text, project["name"])
                    image_candidates.append(candidate)

        except Exception as exc:
            print(f"[Efin AI] Не удалось прочитать {project['name']}: {exc}")

    context = "\n\n".join(parts)[:12000]

    if visual:
        # Не отправляем модели случайные картинки. Сначала отбираем наиболее
        # подходящие по тексту страницы/слайда и названию изображения.
        image_candidates.sort(key=lambda item: item["score"], reverse=True)
        image_candidates = [item for item in image_candidates if item["score"] > 0][:6]

    return (
        context or "В базе знаний EFIN нет найденного текстового фрагмента по этому вопросу.",
        image_candidates,
    )


def _image_data_url(path):
    data = Path(path).read_bytes()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(Path(path).suffix.lower(), "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


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


def _parse_image_selection(answer, max_images):
    match = re.search(r"\[SEND_IMAGES:\s*([0-9,\s]+)\]", answer or "")
    if not match:
        return []

    result = []
    for value in match.group(1).split(","):
        try:
            index = int(value.strip())
        except ValueError:
            continue
        if 1 <= index <= max_images and index not in result:
            result.append(index)

    return result


async def ask_efin_ai(bot, user_text):
    api_key = os.getenv("TOKENBOOM_API_KEY")
    if not api_key:
        raise RuntimeError("Не задана переменная окружения TOKENBOOM_API_KEY")

    knowledge, images = await build_knowledge_context(bot, user_text)
    visual = _visual_query(user_text)
    print(f"[Efin AI] Контекст базы: {len(knowledge)} символов; кандидатов изображений: {len(images)}")

    system_text = SYSTEM_PROMPT + "\n\nБАЗА ЗНАНИЙ EFIN:\n" + knowledge
    user_content = [{"type": "text", "text": user_text}]

    if visual and images:
        user_content.append(
            {
                "type": "text",
                "text": (
                    "Ниже переданы кандидаты изображений из базы знаний. "
                    "Для каждого изображения указан его номер и источник. "
                    "Сопоставь запрос пользователя с текстом страницы/слайда и самим изображением. "
                    "Отправляй изображение только при прямом соответствии."
                ),
            }
        )

        for index, image in enumerate(images, start=1):
            user_content.append(
                {
                    "type": "text",
                    "text": (
                        f"ИЗОБРАЖЕНИЕ {index}\n"
                        f"Проект: {image.get('project_name', '')}\n"
                        f"Источник: {image.get('name', '')}\n"
                        f"Контекст страницы/слайда: {image.get('context', '')}"
                    ),
                }
            )
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _image_data_url(image["path"])},
                }
            )
    elif visual:
        user_content.append(
            {
                "type": "text",
                "text": "В базе знаний не найдено подходящих изображений. Не добавляй маркер [SEND_IMAGES].",
            }
        )

    payload = {
        "model": TOKENBOM_MODEL,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_content},
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

    selected_numbers = _parse_image_selection(answer, len(images))
    clean_answer = re.sub(r"\s*\[SEND_IMAGES:\s*[0-9,\s]+\]", "", answer).strip()

    selected_images = [images[index - 1] for index in selected_numbers]

    print(
        f"[Efin AI] Выбраны изображения: "
        f"{[image.get('name') for image in selected_images]}"
    )

    return {
        "answer": clean_answer,
        "images": selected_images,
    }
