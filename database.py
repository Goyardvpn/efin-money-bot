import sqlite3
from pathlib import Path
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo


DB_PATH = Path("data/efin.db")
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def get_moscow_now():
    return datetime.now(MOSCOW_TZ)


def get_moscow_today():
    return get_moscow_now().date()


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                operation_id TEXT NOT NULL,
                trigger TEXT NOT NULL,
                bank TEXT NOT NULL,
                status TEXT NOT NULL,
                advance INTEGER NOT NULL DEFAULT 0,
                settlement INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP,
                original_text TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, operation_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_blocked INTEGER NOT NULL DEFAULT 0
            )
        """)

        conn.commit()


def register_user(user_id, username="", first_name="", last_name=""):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (
                user_id, username, first_name, last_name
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                last_seen = CURRENT_TIMESTAMP
            """,
            (user_id, username, first_name, last_name),
        )
        conn.commit()


def calculate_periods(created_at):
    if not created_at:
        return None

    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at)
        except ValueError:
            try:
                created_at = datetime.strptime(
                    created_at,
                    "%Y-%m-%d %H:%M:%S",
                )
            except ValueError:
                return None

    if isinstance(created_at, datetime):
        application_date = created_at.date()
    elif isinstance(created_at, date):
        application_date = created_at
    else:
        return None

    week_start = application_date - timedelta(
        days=application_date.weekday()
    )
    week_end = week_start + timedelta(days=6)

    advance_payout_start = week_end + timedelta(days=1)
    advance_payout_end = advance_payout_start + timedelta(days=4)

    settlement_month_start = application_date.replace(day=1)

    if settlement_month_start.month == 12:
        next_month = settlement_month_start.replace(
            year=settlement_month_start.year + 1,
            month=1,
            day=1,
        )
    else:
        next_month = settlement_month_start.replace(
            month=settlement_month_start.month + 1,
            day=1,
        )

    settlement_payout_start = next_month.replace(day=25)

    if next_month.month == 12:
        settlement_payout_end = next_month.replace(
            year=next_month.year + 1,
            month=1,
            day=5,
        )
    else:
        settlement_payout_end = next_month.replace(
            month=next_month.month + 1,
            day=5,
        )

    return {
        "week_start": week_start,
        "week_end": week_end,
        "advance_payout_start": advance_payout_start,
        "advance_payout_end": advance_payout_end,
        "settlement_month": settlement_month_start,
        "settlement_payout_start": settlement_payout_start,
        "settlement_payout_end": settlement_payout_end,
    }


def add_earning(
    user_id,
    operation_id,
    trigger,
    bank,
    status,
    advance,
    settlement,
    total,
    created_at=None,
    original_text="",
):
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO earnings (
                    user_id, operation_id, trigger, bank, status,
                    advance, settlement, total, created_at, original_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    operation_id,
                    trigger,
                    bank,
                    status,
                    advance,
                    settlement,
                    total,
                    created_at,
                    original_text,
                ),
            )
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False


def earning_exists(user_id, operation_id):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT 1 FROM earnings
            WHERE user_id = ? AND operation_id = ?
            LIMIT 1
            """,
            (user_id, operation_id),
        )
        return cursor.fetchone() is not None


def get_earnings_stats(user_id):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(advance), 0),
                   COALESCE(SUM(settlement), 0),
                   COALESCE(SUM(total), 0)
            FROM earnings
            WHERE user_id = ?
            """,
            (user_id,),
        )
        row = cursor.fetchone()

        return {
            "count": row[0],
            "advance": row[1],
            "settlement": row[2],
            "total": row[3],
        }


def get_today_stats(user_id):
    today = get_moscow_today()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(advance), 0),
                   COALESCE(SUM(settlement), 0),
                   COALESCE(SUM(total), 0)
            FROM earnings
            WHERE user_id = ?
              AND date(created_at) = ?
            """,
            (user_id, today.isoformat()),
        )

        row = cursor.fetchone()

        return {
            "count": row[0],
            "advance": row[1],
            "settlement": row[2],
            "total": row[3],
        }


def get_user_earnings(user_id):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, operation_id, trigger, bank, status,
                   advance, settlement, total,
                   created_at, original_text
            FROM earnings
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (user_id,),
        )

        rows = cursor.fetchall()
        earnings = []

        for row in rows:
            earnings.append({
                "id": row[0],
                "operation_id": row[1],
                "trigger": row[2],
                "bank": row[3],
                "status": row[4],
                "advance": row[5],
                "settlement": row[6],
                "total": row[7],
                "created_at": row[8],
                "original_text": row[9] or "",
            })

        return earnings


def get_next_advance(user_id):
    earnings = get_user_earnings(user_id)
    today = get_moscow_today()
    groups = {}

    for earning in earnings:
        periods = calculate_periods(earning["created_at"])

        if not periods:
            continue

        payout_start = periods["advance_payout_start"]
        payout_end = periods["advance_payout_end"]

        if payout_end < today:
            continue

        key = (payout_start, payout_end)

        if key not in groups:
            groups[key] = {
                "payout_start": payout_start,
                "payout_end": payout_end,
                "week_start": periods["week_start"],
                "week_end": periods["week_end"],
                "count": 0,
                "amount": 0,
            }

        groups[key]["count"] += 1
        groups[key]["amount"] += earning["advance"]

    if not groups:
        return None

    return sorted(
        groups.values(),
        key=lambda item: item["payout_start"],
    )[0]


def get_next_settlement(user_id):
    earnings = get_user_earnings(user_id)
    today = get_moscow_today()
    groups = {}

    for earning in earnings:
        periods = calculate_periods(earning["created_at"])

        if not periods:
            continue

        payout_start = periods["settlement_payout_start"]
        payout_end = periods["settlement_payout_end"]

        if payout_end < today:
            continue

        key = (payout_start, payout_end)

        if key not in groups:
            groups[key] = {
                "payout_start": payout_start,
                "payout_end": payout_end,
                "month": periods["settlement_month"],
                "count": 0,
                "amount": 0,
            }

        groups[key]["count"] += 1
        groups[key]["amount"] += earning["settlement"]

    if not groups:
        return None

    return sorted(
        groups.values(),
        key=lambda item: item["payout_start"],
    )[0]


def get_week_income(user_id, week_start):
    week_end = week_start + timedelta(days=6)
    earnings = get_user_earnings(user_id)

    result = {
        "week_start": week_start,
        "week_end": week_end,
        "count": 0,
        "advance": 0,
        "settlement": 0,
        "total": 0,
    }

    for earning in earnings:
        periods = calculate_periods(earning["created_at"])

        if not periods or periods["week_start"] != week_start:
            continue

        result["count"] += 1
        result["advance"] += earning["advance"]
        result["settlement"] += earning["settlement"]
        result["total"] += earning["total"]

    return result


def get_month_income(user_id, year, month):
    earnings = get_user_earnings(user_id)

    result = {
        "year": year,
        "month": month,
        "count": 0,
        "advance": 0,
        "settlement": 0,
        "total": 0,
    }

    for earning in earnings:
        periods = calculate_periods(earning["created_at"])

        if not periods:
            continue

        settlement_month = periods["settlement_month"]

        if (
            settlement_month.year != year
            or settlement_month.month != month
        ):
            continue

        result["count"] += 1
        result["advance"] += earning["advance"]
        result["settlement"] += earning["settlement"]
        result["total"] += earning["total"]

    return result


def get_users():
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT user_id, username, first_name, last_name,
                   first_seen, last_seen, is_blocked
            FROM users
            ORDER BY first_seen ASC
            """
        )

        rows = cursor.fetchall()
        users = []

        for row in rows:
            users.append({
                "user_id": row[0],
                "username": row[1] or "",
                "first_name": row[2] or "",
                "last_name": row[3] or "",
                "first_seen": row[4],
                "last_seen": row[5],
                "is_blocked": row[6],
            })

        return users


def get_global_stats():
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(advance), 0),
                   COALESCE(SUM(settlement), 0),
                   COALESCE(SUM(total), 0)
            FROM earnings
            """
        )

        row = cursor.fetchone()

        cursor = conn.execute(
            "SELECT COUNT(*) FROM users"
        )

        users_count = cursor.fetchone()[0]

        return {
            "users": users_count,
            "count": row[0],
            "advance": row[1],
            "settlement": row[2],
            "total": row[3],
        }


def delete_all_user_earnings(user_id):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(total), 0)
            FROM earnings
            WHERE user_id = ?
            """,
            (user_id,),
        )

        count, total = cursor.fetchone()

        conn.execute(
            "DELETE FROM earnings WHERE user_id = ?",
            (user_id,),
        )

        conn.commit()

        return {
            "count": count,
            "total": total,
        }


def delete_user_earnings_by_date(user_id, selected_date):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(total), 0)
            FROM earnings
            WHERE user_id = ?
              AND date(created_at) = ?
            """,
            (user_id, selected_date.isoformat()),
        )

        count, total = cursor.fetchone()

        conn.execute(
            """
            DELETE FROM earnings
            WHERE user_id = ?
              AND date(created_at) = ?
            """,
            (user_id, selected_date.isoformat()),
        )

        conn.commit()

        return {
            "count": count,
            "total": total,
        }
