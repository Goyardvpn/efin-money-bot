from parser import parse_message

import database
from tests.base import DbTestCase

PAID_REFUSAL_XA = (
    "Заявка ХА0988802 выполнена. Банком клиенту отказано. "
    "Карта остается у клиента в любом случае - оплата такая же 300+ 100"
)
PAID_REFUSAL_YF = (
    "По заявке - ЯФ_ИВАНОВ ИВАН ИВАНОВИЧ, ЯФ0254407 от 10.10.2026 10:50:26 "
    "принято отрицательное решение банка, карту НЕ выдавать - оплата 300+100"
)


class PaidRefusalTests(DbTestCase):
    def test_xa_refusal_with_card_staying_is_paid(self):
        result = parse_message(PAID_REFUSAL_XA)

        self.assertTrue(result["is_payable"])
        self.assertEqual(result["operation_id"], "ХА0988802")
        self.assertEqual(result["trigger"], "ХА")
        self.assertEqual(result["status"], "выполнена, банк отказал")
        self.assertEqual((result["advance"], result["settlement"], result["total"]), (300, 100, 400))
        self.assertIsNone(result["created_at"])

    def test_negative_bank_decision_is_paid_and_date_is_parsed(self):
        result = parse_message(PAID_REFUSAL_YF)

        self.assertTrue(result["is_payable"])
        self.assertEqual(result["operation_id"], "ЯФ0254407")
        self.assertEqual(result["status"], "отрицательное решение банка")
        self.assertEqual(result["total"], 400)
        self.assertEqual(str(result["created_at"]), "2026-10-10 10:50:26")

    def test_line_breaks_yo_and_nbsp_do_not_matter(self):
        text = (
            "Заявка ХА0988802 выполнена.\nБанком клиенту отказано.\n"
            "Карта остаётся  у клиента в любом случае —  оплата такая же\xa0300+100"
        )
        self.assertTrue(parse_message(text)["is_payable"])

    def test_refusal_without_explicit_payment_is_not_paid(self):
        cases = {
            "обычный отказ": "Заявка ХА1234567. Банком клиенту отказано.",
            "оплата не производится": (
                "По заявке ХА1234567 принято отрицательное решение банка, "
                "карту не выдавать, оплата не производится"
            ),
            "без оплаты": (
                "Заявка ХА1234567 выполнена. Банком клиенту отказано. "
                "Карта остается у клиента без оплаты"
            ),
            "доплата вместо оплаты": "Заявка ХА1234567: банком клиенту отказано, доплата 300",
            "просто слово отказ": "Заявка ХА1234567 - отказ",
        }
        for name, text in cases.items():
            with self.subTest(name):
                result = parse_message(text)
                self.assertFalse(result["is_payable"])
                self.assertEqual(result["total"], 0)


class ExistingStatusTests(DbTestCase):
    def test_previous_statuses_are_unchanged(self):
        cases = [
            ("ТП0798263 от 25.09.2026 14:32:10 Заявка принята", "заявка принята", True),
            ("ОК6929630 успешно подписана через маркетплейс", "успешно подписана", True),
            ("СД0226280 успешно выдана по безбумажному процессу", "успешно выдана", True),
            ("МБ0000001 ожидает подписания", "ожидает подписания", False),
            ("МБ0000002 что-то непонятное", "неизвестный статус", False),
        ]
        for text, status, payable in cases:
            with self.subTest(status):
                result = parse_message(text)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["is_payable"], payable)

    def test_amount_comes_from_tariff_not_from_text(self):
        database.update_tariff("ХА", advance=350)

        result = parse_message(PAID_REFUSAL_XA)

        self.assertEqual((result["advance"], result["settlement"]), (350, 100))


class NotRecognizedTests(DbTestCase):
    def test_empty_or_without_number(self):
        self.assertIsNone(parse_message(""))
        self.assertIsNone(parse_message(None))
        self.assertIsNone(parse_message("просто текст без номера заявки"))

    def test_unknown_tariff_code(self):
        self.assertIsNone(parse_message("ЩЩ1234567 заявка принята"))

    def test_name_with_tariff_letters_is_not_taken_as_number(self):
        result = parse_message(PAID_REFUSAL_YF)
        self.assertEqual(result["operation_id"], "ЯФ0254407")
