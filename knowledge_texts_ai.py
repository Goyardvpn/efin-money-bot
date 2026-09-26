"""Подключает обычный текст из базы знаний к Efin AI."""

import ai_assistant
from knowledge import get_project_texts


_original_project_data = ai_assistant._project_data


async def _project_data_with_text(bot, project):
    data = await _original_project_data(bot, project)
    texts = get_project_texts(project["id"])
    if not texts:
        return data

    blocks = []
    for index, row in enumerate(texts, 1):
        value = (row["text"] or "").strip()
        if value:
            blocks.append(f"=== ТЕКСТОВЫЙ МАТЕРИАЛ {index} ===\n{value}")

    if not blocks:
        return data

    result = dict(data)
    current = result.get("text", "").strip()
    result["text"] = "\n\n".join(part for part in (current, *blocks) if part)
    print(f"[Efin AI] Проект «{project['name']}»: добавлено текстовых материалов {len(blocks)}")
    return result


def install():
    ai_assistant._project_data = _project_data_with_text
