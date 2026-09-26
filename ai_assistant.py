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

База знаний EFIN — главный источник информации о внутренних проектах.
Нельзя придумывать правила, тарифы, выплаты, инструкции или содержание материалов.

ВАЖНЫЕ ПРАВИЛА:
1. Если вопрос относится к конкретному проекту, используй материалы именно этого проекта.
2. Если нужной информации в базе нет, прямо скажи об этом.
3. Не подменяй отсутствующий материал похожим материалом.
4. Если пользователь просит фотографию клиента, присылать можно только изображение, которое после визуального анализа определено как фотография человека и связано с нужным запросом.
5. Логотип, QR-код, штрихкод, банковский бланк, заявление, документ, скриншот интерфейса или декоративная картинка не являются фотографией клиента.
6. Текст рядом с изображением не доказывает, что изображено на самой картинке.
7. Не называй человека клиентом, если по самому изображению это подтвердить нельзя.
8. Если подходящего изображения нет, не добавляй [SEND_IMAGES].
9. Если подходящее изображение есть, добавь в конце ответа ровно [SEND_IMAGES].
10. Никогда не отправляй случайные изображения только потому, что они находятся в той же памятке.
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


def _save_image(
    project_id,
    index,
    image_bytes,
    suffix,
    source_name,
    context="",
    page_number=None,
):
    directory = _safe_media_dir(project_id)
    suffix = suffix.lower()
    if not suffix.startswith("."):
        suffix = "." + suffix

    path = directory / f"{index:03d}{suffix}"
    path.write_bytes(image_bytes)

    return {
        "path": str(path),
        "name": source_name or path.name,
        "context": context or "",
        "page": page_number,
        "description": "",
        "type": "",
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
            try:
                if getattr(shape, "has_text_frame", False):
                    value = shape.text.strip()
                    if value:
                        slide_text.append(value)
            except Exception:
                pass

        slide_context = "\n".join(slide_text).strip()
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
                        slide_context,
                        slide_number,
                    )
                )
            except Exception as exc:
                print(f"[Efin AI] Ошибка извлечения изображения PPTX: {exc}")

    return "\n\n".join(text_parts), images


def _extract_pdf(data, project_id):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    text_parts = []
    images = []
    image_index = 0

    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            text_parts.append(f"Страница {page_number}:\n{text}")

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
                        text,
                        page_number,
                    )
                )
        except Exception as exc:
            print(
                f"[Efin AI] Ошибка извлечения изображений PDF, "
                f"страница {page_number}: {exc}"
            )

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
        text = "\n".join(
            paragraph.text
            for paragraph in document.paragraphs
            if paragraph.text.strip()
        )
        return text, []

    if name.endswith(".pptx") or "presentationml.presentation" in mime:
        return _extract_pptx(data, project_id)

    if name.endswith((".jpg", ".jpeg", ".png", ".webp")) or mime.startswith("image/"):
        suffix = Path(name).suffix.lower() or ".jpg"
        return (
            "Изображение из базы знаний.",
            [
                _save_image(
                    project_id,
                    1,
                    data,
                    suffix,
                    file_name or "изображение",
                    "Изображение из базы знаний EFIN.",
                )
            ],
        )

    return _decode(data), []


def _image_data_url(path):
    data = Path(path).read_bytes()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(Path(path).suffix.lower(), "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _request(payload, api_key, timeout=90):
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"TokenBom API HTTP {exc.code}: {body[:1000]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Не удалось подключиться к TokenBom API: {exc.reason}"
        ) from exc


def _analyse_image_sync(image, api_key):
    """Определяет фактический тип изображения для точного поиска."""
    if not api_key:
        return ""

    try:
        prompt = f"""
Ты классифицируешь изображение из внутренней базы знаний EFIN.

Текст рядом с изображением НЕ является доказательством того, что изображено на картинке.
Смотри прежде всего на само изображение.

Текст рядом:
{image.get('context', '')[:5000]}

Определи фактическое содержимое изображения.

Обязательно выбери ОДИН тип:
- ФОТО ЧЕЛОВЕКА — если на изображении действительно виден человек как фотография.
- ФОТО КЛИЕНТА — только если само изображение явно является фотографией клиента или контекст однозначно связывает именно этого человека с клиентом.
- ЛОГОТИП — если это логотип/фирменный знак.
- QR-КОД — если это QR-код.
- ШТРИХКОД — если это штрихкод.
- ДОКУМЕНТ — если это бланк, заявление или другой документ без фотографии человека.
- СКРИНШОТ — если это экран приложения/сайта/телефона.
- КАРТА — если изображена банковская или иная карта.
- СХЕМА — если это схема/диаграмма.
- ДРУГОЕ — всё остальное.

Критически важно:
- Если человека нет, нельзя выбирать ФОТО ЧЕЛОВЕКА или ФОТО КЛИЕНТА.
- Логотип, QR-код, штрихкод и документ никогда не являются фотографией клиента.
- Если не можешь подтвердить, что человек является клиентом, выбери ФОТО ЧЕЛОВЕКА, а не ФОТО КЛИЕНТА.
- Не придумывай объекты.

Верни ровно в формате:
ТИП: ...
ОПИСАНИЕ: ...
КЛЮЧЕВЫЕ СЛОВА: ...
"""

        payload = {
            "model": TOKENBOM_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Ты строго классифицируешь изображения. "
                        "Не выдумывай людей или объекты."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": _image_data_url(image["path"])},
                        },
                    ],
                },
            ],
            "max_tokens": 500,
        }

        response = _request(payload, api_key, timeout=90)
        return (
            response["choices"][0]["message"]["content"] or ""
        ).strip()
    except Exception as exc:
        print(
            f"[Efin AI] Не удалось проанализировать изображение "
            f"{image.get('name')}: {exc}"
        )
        return ""


async def _analyse_images(images, api_key):
    if not images or not api_key:
        return images

    tasks = []
    positions = []

    for index, image in enumerate(images):
        if image.get("description"):
            continue
        positions.append(index)
        tasks.append(
            asyncio.to_thread(_analyse_image_sync, image, api_key)
        )

    if not tasks:
        return images

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for index, result in zip(positions, results):
        if isinstance(result, Exception):
            description = ""
        else:
            description = result or ""

        images[index]["description"] = description
        images[index]["type"] = _extract_image_type(description)

    return images


def _extract_image_type(description):
    match = re.search(r"ТИП:\s*([^\n]+)", description or "", re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).strip().upper()


def _project_data(bot, project):
    raise RuntimeError("internal")


async def _get_project_data(bot, project):
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

    api_key = os.getenv("TOKENBOOM_API_KEY")
    if images:
        print(
            f"[Efin AI] Найдено {len(images)} изображений в проекте "
            f"{project['name']}. Запускаю анализ..."
        )
        images = await _analyse_images(images, api_key)

        for image in images:
            print(
                f"[Efin AI] {project['name']} | "
                f"{image['name']} | тип: {image.get('type') or 'НЕ ОПРЕДЕЛЁН'}"
            )

    result = {
        "file_id": project["file_id"],
        "text": text.strip(),
        "images": images,
    }
    _CACHE[project["id"]] = result
    return result


def _query_words(query):
    return set(
        re.findall(r"[а-яa-z0-9ё-]{3,}", (query or "").lower())
    )


def _relevant(text, query, limit=4500):
    if not text:
        return ""

    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n|\n", text)
        if paragraph.strip()
    ]
    words = _query_words(query)
    scored = []

    for index, paragraph in enumerate(paragraphs):
        low = paragraph.lower()
        score = sum(1 for word in words if word in low)
        scored.append((score, index, paragraph))

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = [item for item in scored if item[0] > 0][:15]
    if not selected:
        selected = scored[:6]

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
    text = (query or "").lower()
    return any(
        token in text
        for token in (
            "фото",
            "фотограф",
            "фотографию",
            "фотография",
            "фотографию клиента",
            "фото клиента",
            "фотография клиента",
            "фотку",
            "сфот",
            "изображ",
            "картин",
            "пример",
            "скрин",
            "скриншот",
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


def _is_client_photo_request(query):
    text = (query or "").lower()
    photo_words = (
        "фото",
        "фотограф",
        "фотку",
        "сфот",
        "снимок",
        "изображ",
    )
    client_words = (
        "клиент",
        "клиента",
        "клиенту",
        "клиентом",
    )
    return any(x in text for x in photo_words) and any(
        x in text for x in client_words
    )


def _score_image(image, query):
    """Скоринг только для обычных визуальных запросов.

    Для запроса фотографии клиента используется отдельный строгий фильтр.
    """
    words = _query_words(query)
    searchable = " ".join(
        [
            image.get("name", ""),
            image.get("context", ""),
            image.get("description", ""),
        ]
    ).lower()

    if not words or not searchable:
        return 0

    score = 0
    for word in words:
        if word in searchable:
            score += 1
        if len(word) >= 6 and word in searchable:
            score += 2
    return score


def _select_relevant_images(images, query, max_images=4):
    if not images:
        return []

    if _is_client_photo_request(query):
        # Жёсткое правило: никакие документы, QR, штрихкоды и логотипы
        # не могут попасть в ответ на запрос фотографии клиента.
        candidates = [
            image
            for image in images
            if image.get("type") == "ФОТО КЛИЕНТА"
        ]

        if candidates:
            print(
                f"[Efin AI] Найдено {len(candidates)} фотографий клиента "
                "для запроса."
            )
        else:
            print(
                "[Efin AI] Фотографии клиента среди материалов нет."
            )
        return candidates[:max_images]

    scored = []
    for index, image in enumerate(images):
        score = _score_image(image, query)
        scored.append((score, index, image))

    scored.sort(key=lambda item: (-item[0], item[1]))
    relevant = [item for item in scored if item[0] > 0]

    if not relevant:
        return []

    return [item[2] for item in relevant[:max_images]]


async def build_knowledge_context(bot, user_text):
    projects = get_projects()
    if not projects:
        return "База знаний EFIN пока пуста.", []

    parts = []
    selected_images = []
    visual = _visual_query(user_text)

    for project in projects:
        try:
            data = await _get_project_data(bot, project)
            relevant = _relevant(data["text"], user_text)

            if relevant:
                parts.append(
                    f"=== ПРОЕКТ: {project['name']} ===\n{relevant}"
                )

            if visual:
                project_images = _select_relevant_images(
                    data["images"],
                    user_text,
                    max_images=4,
                )
                if project_images:
                    print(
                        f"[Efin AI] В проекте {project['name']} "
                        f"найдено подходящих изображений: {len(project_images)}"
                    )
                selected_images.extend(project_images)

        except Exception as exc:
            print(
                f"[Efin AI] Не удалось прочитать {project['name']}: {exc}"
            )

    unique_images = []
    seen_paths = set()
    for image in selected_images:
        path = image["path"]
        if path in seen_paths:
            continue
        seen_paths.add(path)
        unique_images.append(image)

    context = "\n\n".join(parts)[:12000]
    if not context:
        context = "В базе знаний EFIN нет найденного текстового фрагмента по этому вопросу."

    return context, unique_images[:6]


async def ask_efin_ai(bot, user_text):
    api_key = os.getenv("TOKENBOOM_API_KEY")
    if not api_key:
        raise RuntimeError("Не задана переменная окружения TOKENBOOM_API_KEY")

    knowledge, images = await build_knowledge_context(bot, user_text)

    print(
        f"[Efin AI] Контекст базы: {len(knowledge)} символов; "
        f"релевантных изображений: {len(images)}"
    )

    system_text = SYSTEM_PROMPT + "\n\nБАЗА ЗНАНИЙ EFIN:\n" + knowledge
    user_content = [{"type": "text", "text": user_text}]

    if images:
        user_content.append(
            {
                "type": "text",
                "text": (
                    "Ниже переданы ТОЛЬКО изображения, которые система предварительно "
                    "отобрала как подходящие. Не заменяй их другими изображениями.\n"
                ),
            }
        )

    for index, image in enumerate(images, start=1):
        user_content.append(
            {
                "type": "text",
                "text": (
                    f"Изображение {index}. Тип: {image.get('type', '')}. "
                    f"Название: {image['name']}.\n"
                    f"Описание: {image.get('description', '')[:3000]}\n"
                    f"Текст рядом: {image.get('context', '')[:2000]}"
                ),
            }
        )
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": _image_data_url(image["path"])},
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
    elapsed = asyncio.get_running_loop().time() - started
    print(f"[Efin AI] TokenBom ответил за {elapsed:.2f} сек.")

    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            "TokenBom API вернул неожиданный формат ответа"
        ) from exc

    if not answer or not answer.strip():
        raise RuntimeError("TokenBom API вернул пустой ответ")

    send_images = "[SEND_IMAGES]" in answer
    clean_answer = answer.replace("[SEND_IMAGES]", "").strip()

    # Дополнительная защита: для фото клиента отправляем только изображения,
    # которые классификатор определил как ФОТО КЛИЕНТА.
    if _is_client_photo_request(user_text):
        client_photos = [
            image
            for image in images
            if image.get("type") == "ФОТО КЛИЕНТА"
        ]
        images = client_photos
        if not images:
            send_images = False

    if send_images and not images:
        send_images = False

    return {
        "answer": clean_answer,
        "images": images if send_images else [],
    }
