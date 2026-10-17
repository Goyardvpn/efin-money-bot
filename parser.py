import re
from datetime import datetime

from database import PAYABLE_STATUSES, get_tariff

# Банк может отказать клиенту, но заявка при этом всё равно оплачивается.
# Такие сообщения содержат явную фразу про оплату: «оплата такая же 300+100»,
# «оплата 300+100». Только вместе с ней отказ считается оплачиваемым,
# обычный отказ без этой фразы по-прежнему не оплачивается.
_PAYMENT_CLAUSE = re.compile(
    r"(?<![а-я])(?<!без\s)оплата\s+(?:такая\s+же|как\s+обычно|\d)"
)


def detect_paid_refusal(text: str):
    """Возвращает статус оплачиваемого отказа или None."""
    normalized = " ".join(text.lower().replace("ё", "е").split())

    if not _PAYMENT_CLAUSE.search(normalized):
        return None

    if (
        "карта остается у клиента" in normalized
        or "банком клиенту отказано" in normalized
    ):
        return "выполнена, банк отказал"

    if (
        "отрицательное решение банка" in normalized
        or "карту не выдавать" in normalized
    ):
        return "отрицательное решение банка"

    return None


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
    paid_refusal_status = detect_paid_refusal(text)

    if paid_refusal_status:
        status = paid_refusal_status

    elif "ожидает подписания" in text_lower:
        status = "ожидает подписания"

    elif "успешно подписана через маркетплейс" in text_lower:
        status = "успешно подписана"

    elif "успешно выдана по безбумажному процессу" in text_lower:
        status = "успешно выдана"

    elif "заявка принята" in text_lower:
        status = "заявка принята"

    else:
        status = "неизвестный статус"

    # Оплачиваемые статусы хранятся в database.PAYABLE_STATUSES,
    # чтобы перерасчёт по тарифам считал их так же, как этот разбор.
    is_payable = status in PAYABLE_STATUSES

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
