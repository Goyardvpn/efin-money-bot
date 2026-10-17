import database
from tests.base import DbTestCase

USER = 1


def add(operation_id, trigger, status, advance, settlement, created_at):
    return database.add_earning(
        USER, operation_id, trigger, "Банк", status,
        advance, settlement, advance + settlement, created_at, "текст",
    )


class EarningsTests(DbTestCase):
    def test_duplicate_application_is_not_added_twice(self):
        self.assertTrue(add("ХА0988802", "ХА", "заявка принята", 300, 100, "2026-10-10 10:00:00"))
        self.assertFalse(add("ХА0988802", "ХА", "заявка принята", 300, 100, "2026-10-10 10:00:00"))
        self.assertEqual(database.get_earnings_stats(USER)["count"], 1)

    def test_month_income_is_grouped_by_application_month(self):
        add("ХА0000001", "ХА", "заявка принята", 300, 100, "2026-10-10 10:00:00")
        add("ХА0000002", "ХА", "заявка принята", 300, 100, "2026-10-31 23:00:00")
        add("ХА0000003", "ХА", "заявка принята", 300, 100, "2026-11-01 00:10:00")

        october = database.get_month_income(USER, 2026, 10)
        november = database.get_month_income(USER, 2026, 11)

        self.assertEqual((october["count"], october["total"]), (2, 800))
        self.assertEqual((november["count"], november["total"]), (1, 400))


class RecalculateTests(DbTestCase):
    def test_payable_refusal_statuses_survive_recalculation(self):
        add("ХА0988802", "ХА", "выполнена, банк отказал", 300, 100, "2026-10-10 10:00:00")
        add("ЯФ0254407", "ЯФ", "отрицательное решение банка", 300, 100, "2026-10-10 10:50:26")
        add("МБ0000002", "МБ", "неизвестный статус", 0, 0, "2026-10-10 11:00:00")

        result = database.recalculate_earnings()

        self.assertEqual(result["updated"], 0)
        self.assertEqual(database.get_earnings_stats(USER)["total"], 800)

    def test_new_tariff_is_applied_to_refusal_statuses(self):
        add("ХА0988802", "ХА", "выполнена, банк отказал", 300, 100, "2026-10-10 10:00:00")
        database.update_tariff("ХА", advance=350)

        database.recalculate_earnings()

        totals = {e["operation_id"]: e["total"] for e in database.get_user_earnings(USER)}
        self.assertEqual(totals["ХА0988802"], 450)

    def test_unpayable_status_stays_zero(self):
        add("МБ0000002", "МБ", "неизвестный статус", 0, 0, "2026-10-10 11:00:00")

        database.recalculate_earnings()

        self.assertEqual(database.get_earnings_stats(USER)["total"], 0)

    def test_every_payable_status_is_in_shared_list(self):
        for status in ("заявка принята", "успешно подписана", "успешно выдана",
                       "выполнена, банк отказал", "отрицательное решение банка"):
            self.assertIn(status, database.PAYABLE_STATUSES)
        self.assertNotIn("неизвестный статус", database.PAYABLE_STATUSES)
