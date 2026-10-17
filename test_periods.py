import unittest
from datetime import date, datetime

from database import calculate_periods


class CalculatePeriodsTests(unittest.TestCase):
    def test_saturday_application(self):
        periods = calculate_periods("2026-10-10 10:50:26")

        self.assertEqual(periods["week_start"], date(2026, 10, 5))
        self.assertEqual(periods["week_end"], date(2026, 10, 11))
        # Аванс: с понедельника по пятницу следующей недели.
        self.assertEqual(periods["advance_payout_start"], date(2026, 10, 12))
        self.assertEqual(periods["advance_payout_end"], date(2026, 10, 16))
        # Сверка: с 25-го следующего месяца по 5-е месяца после него.
        self.assertEqual(periods["settlement_month"], date(2026, 10, 1))
        self.assertEqual(periods["settlement_payout_start"], date(2026, 11, 25))
        self.assertEqual(periods["settlement_payout_end"], date(2026, 12, 5))

    def test_monday_and_sunday_belong_to_same_week(self):
        monday = calculate_periods("2026-10-05 00:00:00")
        sunday = calculate_periods("2026-10-11 23:59:59")

        self.assertEqual(monday["week_start"], sunday["week_start"])
        self.assertEqual(monday["advance_payout_start"], sunday["advance_payout_start"])

    def test_november_settlement_crosses_into_next_year(self):
        periods = calculate_periods("2026-11-20 12:00:00")

        self.assertEqual(periods["settlement_payout_start"], date(2026, 12, 25))
        self.assertEqual(periods["settlement_payout_end"], date(2027, 1, 5))

    def test_december_application(self):
        periods = calculate_periods("2026-12-15 12:00:00")

        self.assertEqual(periods["settlement_month"], date(2026, 12, 1))
        self.assertEqual(periods["settlement_payout_start"], date(2027, 1, 25))
        self.assertEqual(periods["settlement_payout_end"], date(2027, 2, 5))

    def test_accepts_datetime_and_date_objects(self):
        expected = calculate_periods("2026-10-10 10:50:26")

        self.assertEqual(calculate_periods(datetime(2026, 10, 10, 10, 50, 26)), expected)
        self.assertEqual(calculate_periods(date(2026, 10, 10)), expected)

    def test_garbage_returns_none(self):
        self.assertIsNone(calculate_periods(None))
        self.assertIsNone(calculate_periods(""))
        self.assertIsNone(calculate_periods("не дата"))
