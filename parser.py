import re
from datetime import datetime

from database import get_tariff


def parse_message(text: str):
    if not text:
        return None

    # Ищем номер заявки:
    # ТП0798263, ОК6929630, СД0226280 и т.д.
    operation_match = re.search(
        r"(?<![А-ЯЁ])([А-ЯЁ]{2}\d{7})(?!\d)",
        text,
    )

    if not operation_match:
        return None

    operation_id = operation_match.group(1)
    trigger = operation_id[:2]

    # Тарифы хранятся в SQLite и могут изменяться
    # администратором прямо из Telegram.
    rate = get_tariff(trigger)

    if rate is None:
        return None

    text_lower = text.lower()

    # Определяем статус
    if "ожидает подписания" in text_lower:
        status = "ожидает подписания"

    elif "успешно подписана через маркетплейс" in text_lower:
        status = "успешно подписана"

    elif "успешно выдана по безбумажному процессу" in text_lower:
        status = "успешно выдана"

    elif "заявка принята" in text_lower:
        status = "заявка принята"

    else:
        status = "неизвестный статус"

    # Эти статусы оплачиваются
    payable_statuses = {
        "заявка принята",
        "успешно подписана",
        "успешно выдана",
    }

    is_payable = status in payable_statuses

    # Ищем дату заявки:
    # от 25.09.2026 14:32:10
    date_match = re.search(
        r"от\s+(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2}:\d{2})",
        text,
    )

    created_at = None

    if date_match:
        date_string = (
            f"{date_match.group(1)} "
            f"{date_match.group(2)}"
        )

        try:
            created_at = datetime.strptime(
                date_string,
                "%d.%m.%Y %H:%M:%S",
            )
        except ValueError:
            created_at = None

    advance = rate["advance"] if is_payable else 0
    settlement = rate["settlement"] if is_payable else 0
    total = advance + settlement

    return {
        "operation_id": operation_id,
        "trigger": trigger,
        "name": rate["name"],
        "status": status,
        "is_payable": is_payable,
        "advance": advance,
        "settlement": settlement,
        "total": total,
        "created_at": created_at,
        "original_text": text,
    }
