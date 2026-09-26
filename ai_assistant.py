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

База знаний EFIN является главным источником информации.

КРИТИЧЕСКИ ВАЖНО:

1. Не выдумывай внутренние правила, тарифы, выплаты, инструкции или условия проектов.

2. Если информации нет в базе знаний, прямо скажи, что в базе её нет.

3. Если пользователь спрашивает про конкретный проект, используй информацию именно этого проекта.

4. Если пользователь просит фото, изображение, скриншот, пример или визуальную инструкцию, используй только действительно подходящие изображения.

5. Нельзя считать изображение подходящим только потому, что оно находится в той же памятке.

6. Логотип, QR-код, штрихкод, банковский бланк или декоративная картинка НЕ являются фотографией клиента.

7. Если пользователь просит фотографию клиента, отправляй только изображение, на котором действительно присутствует человек и которое по содержанию является фотографией клиента.

8. Если подходящего изображения нет, НЕ добавляй [SEND_IMAGES].

9. Если подходящее изображение есть, добавь в конце ответа ровно маркер [SEND_IMAGES].

10. Не подменяй отсутствующую фотографию клиента логотипом, QR-кодом, штрихкодом, документом или скриншотом.

11. Не делай вывод о содержании изображения только по тексту рядом с ним.

12. Если пользователь просит показать конкретный визуальный пример, сначала проверь, существует ли именно такой пример среди переданных материалов.

13. Если такого примера нет, прямо сообщи об отсутствии подходящего материала.

14. Не отправляй случайные изображения из памятки.

15. Если пользователь просит фотографию клиента МТС Банка, а среди материалов есть только логотип, QR-код, штрихкод или заявление, нужно сообщить, что фотографии клиента в базе нет.
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

```
return data.decode("utf-8", errors="replace")
```

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

```
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
}
```

def _extract_pptx(data, project_id):
from pptx import Presentation

```
presentation = Presentation(
    io.BytesIO(data)
)

text_parts = []
images = []
image_index = 0

for slide_number, slide in enumerate(
    presentation.slides,
    start=1,
):
    slide_text = []

    for shape in slide.shapes:
        try:
            if getattr(
                shape,
                "has_text_frame",
                False,
            ):
                value = shape.text.strip()

                if value:
                    slide_text.append(value)

        except Exception:
            pass

    slide_context = "\n".join(
        slide_text
    ).strip()

    if slide_context:
        text_parts.append(
            f"Слайд {slide_number}:\n"
            f"{slide_context}"
        )

    for shape in slide.shapes:
        if getattr(
            shape,
            "shape_type",
            None,
        ) != 13:
            continue

        try:
            image_index += 1

            ext = (
                "."
                + (
                    shape.image.ext
                    or "png"
                )
                .lower()
                .lstrip(".")
            )

            images.append(
                _save_image(
                    project_id=project_id,
                    index=image_index,
                    image_bytes=shape.image.blob,
                    suffix=ext,
                    source_name=(
                        f"Слайд {slide_number} — "
                        f"изображение {image_index}"
                    ),
                    context=slide_context,
                    page_number=slide_number,
                )
            )

        except Exception as exc:
            print(
                "[Efin AI] Ошибка извлечения "
                f"изображения PPTX: {exc}"
            )

return "\n\n".join(text_parts), images
```

def _extract_pdf(data, project_id):
from pypdf import PdfReader

```
reader = PdfReader(
    io.BytesIO(data)
)

text_parts = []
images = []
image_index = 0

for page_number, page in enumerate(
    reader.pages,
    start=1,
):
    text = page.extract_text() or ""
    text = text.strip()

    if text:
        text_parts.append(
            f"Страница {page_number}:\n"
            f"{text}"
        )

    try:
        for image in page.images:
            image_index += 1

            name = (
                image.name
                or (
                    f"page_{page_number}_"
                    f"{image_index}.png"
                )
            )

            suffix = (
                Path(name)
                .suffix
                .lower()
                or ".png"
            )

            images.append(
                _save_image(
                    project_id=project_id,
                    index=image_index,
                    image_bytes=image.data,
                    suffix=suffix,
                    source_name=(
                        f"Страница {page_number} — "
                        f"{name}"
                    ),
                    context=text,
                    page_number=page_number,
                )
            )

    except Exception as exc:
        print(
            "[Efin AI] Ошибка извлечения "
            f"изображений PDF, страница "
            f"{page_number}: {exc}"
        )

return "\n\n".join(text_parts), images
```

def _extract(
data,
file_name,
mime_type,
project_id,
):
name = (
file_name or ""
).lower()

```
mime = (
    mime_type or ""
).lower()

if (
    name.endswith(".txt")
    or "text/plain" in mime
):
    return _decode(data), []

if (
    name.endswith(".pdf")
    or "application/pdf" in mime
):
    return _extract_pdf(
        data,
        project_id,
    )

if (
    name.endswith(".docx")
    or "wordprocessingml.document" in mime
):
    from docx import Document

    document = Document(
        io.BytesIO(data)
    )

    text = "\n".join(
        paragraph.text
        for paragraph in document.paragraphs
        if paragraph.text.strip()
    )

    return text, []

if (
    name.endswith(".pptx")
    or "presentationml.presentation" in mime
):
    return _extract_pptx(
        data,
        project_id,
    )

if (
    name.endswith(
        (
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        )
    )
    or mime.startswith("image/")
):
    suffix = (
        Path(name).suffix.lower()
        or ".jpg"
    )

    return (
        "Изображение из базы знаний.",
        [
            _save_image(
                project_id=project_id,
                index=1,
                image_bytes=data,
                suffix=suffix,
                source_name=(
                    file_name
                    or "изображение"
                ),
                context=(
                    "Изображение из базы "
                    "знаний EFIN."
                ),
            )
        ],
    )

return _decode(data), []
```

def _image_data_url(path):
data = Path(path).read_bytes()

```
mime = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}.get(
    Path(path).suffix.lower(),
    "image/jpeg",
)

return (
    f"data:{mime};base64,"
    f"{base64.b64encode(data).decode('ascii')}"
)
```

def _request(
payload,
api_key,
timeout=90,
):
request = urllib.request.Request(
TOKENBOM_API_URL,
data=json.dumps(
payload
).encode("utf-8"),
headers={
"Authorization":
f"Bearer {api_key}",
"Content-Type":
"application/json",
},
method="POST",
)

```
try:
    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:
        return json.loads(
            response.read().decode(
                "utf-8"
            )
        )

except urllib.error.HTTPError as exc:
    body = exc.read().decode(
        "utf-8",
        errors="replace",
    )

    raise RuntimeError(
        f"TokenBom API HTTP "
        f"{exc.code}: "
        f"{body[:1000]}"
    ) from exc

except urllib.error.URLError as exc:
    raise RuntimeError(
        "Не удалось подключиться "
        f"к TokenBom API: "
        f"{exc.reason}"
    ) from exc
```

def _analyse_image_sync(
image,
api_key,
):
"""
Создаёт строгое описание изображения.
Это описание используется для поиска.
"""

```
if not api_key:
    return ""

try:
    image_url = _image_data_url(
        image["path"]
    )

    context = image.get(
        "context",
        "",
    )

    page = image.get(
        "page"
    )

    location = ""

    if page:
        location = (
            f"Страница или слайд: {page}\n"
        )

    prompt = f"""
```

Проанализируй изображение из внутренней
базы знаний EFIN.

Твоя задача — определить, ЧТО ФАКТИЧЕСКИ
ИЗОБРАЖЕНО НА КАРТИНКЕ.

{location}

Текст рядом с изображением:
{context[:6000]}

Определи:

* есть ли человек;
* есть ли клиент;
* является ли это фотографией человека;
* является ли это примером фотографии клиента;
* есть ли банковская карта;
* есть ли логотип;
* есть ли QR-код;
* есть ли штрихкод;
* есть ли документ;
* есть ли заявление;
* есть ли телефон;
* есть ли экран приложения;
* есть ли скриншот;
* есть ли схема;
* есть ли другой визуальный пример.

ОСОБО ВАЖНО:

Если человека на изображении НЕТ,
напиши:
"Человека на изображении нет."

Если это логотип, напиши:
"Это логотип."

Если это QR-код, напиши:
"Это QR-код."

Если это штрихкод, напиши:
"Это штрихкод."

Если это документ без человека, напиши:
"Это документ без фотографии клиента."

Если это действительно фотография человека,
напиши:
"На изображении есть человек."

Если по самому изображению нельзя подтвердить,
что человек является клиентом, НЕ называй его
клиентом.

Не используй текст рядом с картинкой как доказательство
того, что изображено на самой картинке.

Не придумывай.

В конце обязательно дай строку:

ТИП: ...

Например:

ТИП: ФОТО КЛИЕНТА

или

ТИП: ЛОГОТИП

или

ТИП: QR-КОД

или

ТИП: ШТРИХКОД

или

ТИП: ДОКУМЕНТ

или

ТИП: СКРИНШОТ

или

ТИП: ДРУГОЕ
"""

```
    payload = {
        "model": TOKENBOM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты анализируешь изображения "
                    "для точного поиска. "
                    "Нельзя выдумывать людей "
                    "или объекты."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url
                        },
                    },
                ],
            },
        ],
        "max_tokens": 700,
    }

    response = _request(
        payload,
        api_key,
        timeout=90,
    )

    description = (
        response["choices"][0]
        ["message"]["content"]
    )

    return (
        description
        or ""
    ).strip()

except Exception as exc:
    print(
        "[Efin AI] Ошибка анализа "
        f"{image.get('name')}: {exc}"
    )

    return ""
```

async def _analyse_images(
images,
api_key,
):
if not images or not api_key:
return images

```
tasks = []

for image in images:
    if image.get("description"):
        continue

    tasks.append(
        asyncio.to_thread(
            _analyse_image_sync,
            image,
            api_key,
        )
    )

if not tasks:
    return images

descriptions = await asyncio.gather(
    *tasks,
    return_exceptions=True,
)

index = 0

for image in images:
    if image.get("description"):
        continue

    result = descriptions[index]
    index += 1

    if isinstance(
        result,
        Exception,
    ):
        image["description"] = ""
    else:
        image["description"] = (
            result or ""
        )

return images
```

async def _project_data(
bot,
project,
):
cached = _CACHE.get(
project["id"]
)

```
if (
    cached
    and cached["file_id"]
    == project["file_id"]
):
    return cached

telegram_file = await bot.get_file(
    project["file_id"]
)

data = bytes(
    await telegram_file.download_as_bytearray()
)

text, images = _extract(
    data,
    project["file_name"],
    project["mime_type"],
    project["id"],
)

api_key = os.getenv(
    "TOKENBOOM_API_KEY"
)

if images:
    print(
        "[Efin AI] Найдено "
        f"{len(images)} изображений "
        f"в проекте "
        f"{project['name']}. "
        "Запускаю анализ..."
    )

    images = await _analyse_images(
        images,
        api_key,
    )

    for image in images:
        description = image.get(
            "description",
            "",
        )

        print(
            "[Efin AI] Изображение: "
            f"{image.get('name')}"
        )

        print(
            "[Efin AI] Анализ: "
            f"{description[:300]}"
        )

result = {
    "file_id": project["file_id"],
    "text": text.strip(),
    "images": images,
}

_CACHE[
    project["id"]
] = result

return result
```

def _query_words(query):
return set(
re.findall(
r"[а-яa-z0-9ё-]{3,}",
(
query or ""
).lower(),
)
)

def _relevant(
text,
query,
limit=4500,
):
if not text:
return ""

```
paragraphs = [
    paragraph.strip()
    for paragraph in re.split(
        r"\n\s*\n|\n",
        text,
    )
    if paragraph.strip()
]

words = _query_words(query)

scored = []

for index, paragraph in enumerate(
    paragraphs
):
    low = paragraph.lower()

    score = sum(
        1
        for word in words
        if word in low
    )

    scored.append(
        (
            score,
            index,
            paragraph,
        )
    )

scored.sort(
    key=lambda item: (
        -item[0],
        item[1],
    )
)

selected = [
    item
    for item in scored
    if item[0] > 0
][:15]

if not selected:
    selected = scored[:6]

result = []
total = 0

for _, index, paragraph in selected:
    block = (
        f"Фрагмент {index + 1}:\n"
        f"{paragraph}"
    )

    if (
        total + len(block)
        > limit
    ):
        break

    result.append(block)
    total += len(block)

return "\n\n".join(
    result
)
```

def _visual_query(query):
text = (
query or ""
).lower()

```
visual_words = (
    "фото",
    "фотограф",
    "фотографию",
    "фотография",
    "сфот",
    "изображ",
    "картин",
    "пример",
    "скрин",
    "скриншот",
    "снимок",
    "покажи",
    "пришли",
    "скинь",
    "отправь фото",
    "показывай",
    "как выглядит",
    "как правильно",
    "визуал",
    "камера",
    "сфотографировать",
    "фотографировать",
    "клиент",
)

return any(
    token in text
    for token in visual_words
)
```

def _wants_client_photo(query):
text = (
query or ""
).lower()

```
return (
    (
        "фото" in text
        or "фотограф" in text
        or "сфот" in text
    )
    and "клиент" in text
)
```

def _is_client_photo(description):
text = (
description or ""
).lower()

```
if "тип: фото клиента" in text:
    return True

return False
```

def _is_definitely_not_client_photo(
description,
):
text = (
description or ""
).lower()

```
bad_types = (
    "тип: логотип",
    "тип: qr-код",
    "тип: штрихкод",
    "тип: документ",
    "тип: скриншот",
)

if any(
    value in text
    for value in bad_types
):
    return True

bad_words = (
    "человека на изображении нет",
    "документ без фотографии клиента",
    "это логотип",
    "это qr-код",
    "это штрихкод",
)

return any(
    value in text
    for value in bad_words
)
```

def _score_general_image(
image,
query,
):
words = _query_words(
query
)

```
searchable = " ".join(
    [
        image.get(
            "name",
            "",
        ),
        image.get(
            "context",
            "",
        ),
        image.get(
            "description",
            "",
        ),
    ]
).lower()

if not searchable:
    return 0

score = 0

for word in words:
    if word in searchable:
        score += 1

return score
```

def _select_relevant_images(
images,
query,
max_images=4,
):
if not images:
return []

```
wants_client_photo = (
    _wants_client_photo(
        query
    )
)

if wants_client_photo:
    print(
        "[Efin AI] Запрос требует "
        "именно фотографию клиента."
    )

    selected = []

    for image in images:
        description = image.get(
            "description",
            "",
        )

        if _is_definitely_not_client_photo(
            description
        ):
            print(
                "[Efin AI] Отклонено: "
                f"{image.get('name')} — "
                "это не фото клиента."
            )
            continue

        if _is_client_photo(
            description
        ):
            print(
                "[Efin AI] Подтверждено фото "
                f"клиента: {image.get('name')}"
            )
            selected.append(
                image
            )

    return selected[:max_images]

scored = []

for index, image in enumerate(
    images
):
    score = _score_general_image(
        image,
        query,
    )

    scored.append(
        (
            score,
            index,
            image,
        )
    )

scored.sort(
    key=lambda item: (
        -item[0],
        item[1],
    )
)

return [
    item[2]
    for item in scored
    if item[0] > 0
][:max_images]
```

async def build_knowledge_context(
bot,
user_text,
):
projects = get_projects()

```
if not projects:
    return (
        "База знаний EFIN пока пуста.",
        [],
    )

parts = []
selected_images = []

visual = _visual_query(
    user_text
)

for project in projects:
    try:
        data = await _project_data(
            bot,
            project,
        )

        relevant = _relevant(
            data["text"],
            user_text,
        )

        if relevant:
            parts.append(
                f"=== ПРОЕКТ: "
                f"{project['name']} ===\n"
                f"{relevant}"
            )

        if visual:
            project_images = (
                _select_relevant_images(
                    data["images"],
                    user_text,
                    max_images=4,
                )
            )

            if project_images:
                print(
                    "[Efin AI] В проекте "
                    f"{project['name']} "
                    f"найдено подтверждённых "
                    f"изображений: "
                    f"{len(project_images)}"
                )
            else:
                print(
                    "[Efin AI] В проекте "
                    f"{project['name']} "
                    "нет подтверждённого "
                    "подходящего изображения."
                )

            selected_images.extend(
                project_images
            )

    except Exception as exc:
        print(
            "[Efin AI] Не удалось "
            f"прочитать "
            f"{project['name']}: "
            f"{exc}"
        )

context = "\n\n".join(
    parts
)

context = context[:12000]

unique_images = []
seen_paths = set()

for image in selected_images:
    path = image["path"]

    if path in seen_paths:
        continue

    seen_paths.add(path)
    unique_images.append(
        image
    )

return (
    context
    or (
        "В базе знаний EFIN "
        "нет найденного текстового "
        "фрагмента по этому вопросу."
    ),
    unique_images[:6],
)
```

async def ask_efin_ai(
bot,
user_text,
):
api_key = os.getenv(
"TOKENBOOM_API_KEY"
)

```
if not api_key:
    raise RuntimeError(
        "Не задана переменная "
        "окружения "
        "TOKENBOOM_API_KEY"
    )

knowledge, images = (
    await build_knowledge_context(
        bot,
        user_text,
    )
)

print(
    "[Efin AI] Контекст базы: "
    f"{len(knowledge)} символов; "
    f"релевантных изображений: "
    f"{len(images)}"
)

system_text = (
    SYSTEM_PROMPT
    + "\n\n"
    + "БАЗА ЗНАНИЙ EFIN:\n"
    + knowledge
)

user_content = [
    {
        "type": "text",
        "text": user_text,
    }
]

for index, image in enumerate(
    images,
    start=1,
):
    image_context = image.get(
        "context",
        "",
    )

    image_description = image.get(
        "description",
        "",
    )

    page = image.get(
        "page"
    )

    location = ""

    if page:
        location = (
            f"Страница/слайд: "
            f"{page}.\n"
        )

    user_content.append(
        {
            "type": "text",
            "text": (
                f"ПОДТВЕРЖДЁННОЕ "
                f"ИЗОБРАЖЕНИЕ {index}.\n"
                f"{location}"
                f"Название: "
                f"{image['name']}\n\n"
                f"Описание:\n"
                f"{image_description[:5000]}\n\n"
                f"Текст рядом:\n"
                f"{image_context[:3000]}"
            ),
        }
    )

    user_content.append(
        {
            "type": "image_url",
            "image_url": {
                "url": _image_data_url(
                    image["path"]
                )
            },
        }
    )

payload = {
    "model": TOKENBOM_MODEL,
    "messages": [
        {
            "role": "system",
            "content": system_text,
        },
        {
            "role": "user",
            "content": user_content,
        },
    ],
    "max_tokens": 1200,
}

started = (
    asyncio
    .get_running_loop()
    .time()
)

data = await asyncio.to_thread(
    _request,
    payload,
    api_key,
)

elapsed = (
    asyncio
    .get_running_loop()
    .time()
    - started
)

print(
    "[Efin AI] TokenBom ответил "
    f"за {elapsed:.2f} сек."
)

try:
    answer = (
        data["choices"][0]
        ["message"]["content"]
    )

except (
    KeyError,
    IndexError,
    TypeError,
) as exc:
    raise RuntimeError(
        "TokenBom API вернул "
        "неожиданный формат ответа"
    ) from exc

if (
    not answer
    or not answer.strip()
):
    raise RuntimeError(
        "TokenBom API вернул "
        "пустой ответ"
    )

send_images = (
    "[SEND_IMAGES]"
    in answer
)

clean_answer = (
    answer
    .replace(
        "[SEND_IMAGES]",
        "",
    )
    .strip()
)

if (
    send_images
    and not images
):
    print(
        "[Efin AI] AI запросил "
        "изображения, но код не "
        "нашёл подтверждённых "
        "подходящих изображений."
    )

    send_images = False

return {
    "answer": clean_answer,
    "images": (
        images
        if send_images
        else []
    ),
}
```
