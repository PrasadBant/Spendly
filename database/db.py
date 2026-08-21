import calendar
import os
import sqlite3
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

# Resolve DB path relative to project root (parent of database/), not cwd.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "expense_tracker.db")

CATEGORIES = [
    "Food", "Transport", "Bills", "Health",
    "Entertainment", "Shopping", "Other",
]

CURRENCIES = ["INR", "USD", "EUR", "GBP", "JPY", "AUD"]

CURRENCY_SYMBOLS = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "AUD": "A$",
}


def create_user(name, email, password):
    conn = get_db()
    try:
        password_hash = generate_password_hash(password)
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_user_by_email(email):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()


def create_expense(user_id, amount, category, date, description, currency="INR"):
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description, currency) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, amount, category, date, description, currency),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_expense_by_id(expense_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
    finally:
        conn.close()


def update_expense(expense_id, amount, category, date, description, currency="INR"):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE expenses SET amount = ?, category = ?, date = ?, description = ?, "
            "currency = ? WHERE id = ?",
            (amount, category, date, description, currency, expense_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_expense_by_id(expense_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        conn.commit()
    finally:
        conn.close()


def _add_one_month(d):
    # Advance by one calendar month, clamping to the target month's last
    # day (Jan 31 -> Feb 28/29) instead of overflowing into the next month.
    month = d.month + 1
    year = d.year
    if month > 12:
        month = 1
        year += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _advance_interval(d, interval):
    # Note: each advance is computed from the previous occurrence, not the
    # original start date, so a monthly template started on the 31st drifts
    # (31 -> 28 -> 28 -> 28...) rather than jumping back to 31 in months
    # that have one. Accepted trade-off — avoids a python-dateutil dependency.
    if interval == "weekly":
        return d + timedelta(weeks=1)
    return _add_one_month(d)


def create_recurring_expense(
    user_id, amount, category, description, interval, start_date, currency="INR"
):
    conn = get_db()
    try:
        # start_date becomes the template's first next_run_date — the date
        # sync_due_recurring_expenses() will treat as the first occurrence due.
        cursor = conn.execute(
            "INSERT INTO recurring_expenses "
            "(user_id, amount, category, description, interval, next_run_date, currency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, amount, category, description, interval, start_date, currency),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_recurring_expenses(user_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM recurring_expenses WHERE user_id = ? "
            "ORDER BY next_run_date ASC, id DESC",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


def get_recurring_expense_by_id(recurring_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM recurring_expenses WHERE id = ?", (recurring_id,)
        ).fetchone()
    finally:
        conn.close()


def delete_recurring_expense_by_id(recurring_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM recurring_expenses WHERE id = ?", (recurring_id,))
        conn.commit()
    finally:
        conn.close()


def sync_due_recurring_expenses(user_id):
    # Lazy generation: called on every /profile load. Backfills every
    # missed occurrence (not just one) so a user who hasn't logged in for
    # months gets caught up in a single pass, then is a no-op until the
    # next occurrence comes due.
    today = date.today()
    conn = get_db()
    try:
        templates = conn.execute(
            "SELECT * FROM recurring_expenses WHERE user_id = ?", (user_id,)
        ).fetchall()

        for template in templates:
            next_run = datetime.strptime(
                template["next_run_date"], "%Y-%m-%d"
            ).date()
            while next_run <= today:
                # Inserted on this same connection (not via create_expense(),
                # which opens/commits its own connection) so every backfilled
                # expense and the next_run_date advance below commit together
                # — a mid-backfill crash can't leave rows generated without
                # next_run_date having moved past them.
                conn.execute(
                    "INSERT INTO expenses "
                    "(user_id, amount, category, date, description, currency) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        template["user_id"],
                        template["amount"],
                        template["category"],
                        next_run.strftime("%Y-%m-%d"),
                        template["description"],
                        template["currency"],
                    ),
                )
                next_run = _advance_interval(next_run, template["interval"])

            if next_run.strftime("%Y-%m-%d") != template["next_run_date"]:
                conn.execute(
                    "UPDATE recurring_expenses SET next_run_date = ? WHERE id = ?",
                    (next_run.strftime("%Y-%m-%d"), template["id"]),
                )
        conn.commit()
    finally:
        conn.close()


def _date_filter_clause(user_id, start_date, end_date):
    # params is a list (not a tuple, unlike the static param sets elsewhere
    # in this file) because we conditionally append to it below.
    clause = "user_id = ?"
    params = [user_id]
    if start_date is not None:
        clause += " AND date >= ?"
        params.append(start_date)
    if end_date is not None:
        clause += " AND date <= ?"
        params.append(end_date)
    return clause, params


def get_user_expense_summary(user_id, start_date=None, end_date=None):
    conn = get_db()
    try:
        # where_clause is assembled from static fragments only ("user_id = ?",
        # "AND date >= ?", ...) — all actual values stay in params as ? placeholders.
        where_clause, params = _date_filter_clause(user_id, start_date, end_date)
        return conn.execute(
            f"""
            SELECT COUNT(*) AS expense_count,
                   COALESCE(SUM(amount), 0) AS total_amount
            FROM expenses
            WHERE {where_clause}
            """,
            params,
        ).fetchone()
    finally:
        conn.close()


def get_user_expenses(user_id, limit=None, start_date=None, end_date=None):
    conn = get_db()
    try:
        where_clause, params = _date_filter_clause(user_id, start_date, end_date)
        query = f"SELECT * FROM expenses WHERE {where_clause} ORDER BY date DESC, id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def get_category_breakdown(user_id, start_date=None, end_date=None):
    conn = get_db()
    try:
        where_clause, params = _date_filter_clause(user_id, start_date, end_date)
        return conn.execute(
            f"""
            SELECT category, COALESCE(SUM(amount), 0) AS total
            FROM expenses
            WHERE {where_clause}
            GROUP BY category
            ORDER BY total DESC
            """,
            params,
        ).fetchall()
    finally:
        conn.close()


def _search_filter_clause(
    user_id, q=None, category=None, min_amount=None, max_amount=None,
    start_date=None, end_date=None,
):
    # Builds on _date_filter_clause instead of duplicating its date logic —
    # every value still stays in params as a ? placeholder, only static SQL
    # fragments get appended to clause.
    clause, params = _date_filter_clause(user_id, start_date, end_date)
    if q is not None:
        clause += " AND description LIKE ?"
        params.append(f"%{q}%")
    if category is not None:
        clause += " AND category = ?"
        params.append(category)
    if min_amount is not None:
        clause += " AND amount >= ?"
        params.append(min_amount)
    if max_amount is not None:
        clause += " AND amount <= ?"
        params.append(max_amount)
    return clause, params


def search_user_expenses(
    user_id, q=None, category=None, min_amount=None, max_amount=None,
    start_date=None, end_date=None,
):
    conn = get_db()
    try:
        where_clause, params = _search_filter_clause(
            user_id, q=q, category=category, min_amount=min_amount,
            max_amount=max_amount, start_date=start_date, end_date=end_date,
        )
        return conn.execute(
            f"SELECT * FROM expenses WHERE {where_clause} ORDER BY date DESC, id DESC",
            params,
        ).fetchall()
    finally:
        conn.close()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recurring_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                interval TEXT NOT NULL,
                next_run_date TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS exchange_rates (
                currency TEXT PRIMARY KEY,
                rate_to_inr REAL NOT NULL
            )
        """)

        # Older DB files created before multi-currency support (Step 13) predate
        # these columns — CREATE TABLE IF NOT EXISTS above is a no-op against
        # them, so backfill via ALTER TABLE. SQLite has no "ADD COLUMN IF NOT
        # EXISTS", so each statement is individually guarded: it fails harmlessly
        # on a DB where the column already exists (either a fresh DB created with
        # the up-to-date CREATE TABLE above, or a DB already migrated once).
        migrations = [
            "ALTER TABLE users ADD COLUMN preferred_currency TEXT NOT NULL DEFAULT 'INR'",
            "ALTER TABLE expenses ADD COLUMN currency TEXT NOT NULL DEFAULT 'INR'",
            "ALTER TABLE recurring_expenses ADD COLUMN currency TEXT NOT NULL DEFAULT 'INR'",
        ]
        for statement in migrations:
            try:
                conn.execute(statement)
            except sqlite3.OperationalError:
                pass

        conn.commit()
    finally:
        conn.close()


def seed_exchange_rates():
    # Separate from seed_db(), which only ever runs once (guarded on `users`
    # being empty) and would never seed rates on an already-seeded real DB.
    # Rates are static/illustrative — manually maintained, not a live feed —
    # see templates/exchange_rates.html for the user-facing disclaimer.
    conn = get_db()
    try:
        existing = conn.execute("SELECT COUNT(*) AS n FROM exchange_rates").fetchone()
        if existing["n"] > 0:
            return

        rates = [
            ("INR", 1.0),
            ("USD", 83.0),
            ("EUR", 90.0),
            ("GBP", 105.0),
            ("JPY", 0.56),
            ("AUD", 55.0),
        ]
        conn.executemany(
            "INSERT INTO exchange_rates (currency, rate_to_inr) VALUES (?, ?)",
            rates,
        )
        conn.commit()
    finally:
        conn.close()


def get_exchange_rates():
    conn = get_db()
    try:
        return conn.execute("SELECT * FROM exchange_rates").fetchall()
    finally:
        conn.close()


def seed_db():
    conn = get_db()
    try:
        existing = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        if existing["n"] > 0:
            return

        password_hash = generate_password_hash("demo123")
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Demo User", "demo@spendly.com", password_hash),
        )
        user_id = cursor.lastrowid

        year_month = datetime.now().strftime("%Y-%m")
        sample_expenses = [
            (user_id, 12.50, "Food", f"{year_month}-03", "Grocery shopping"),
            (user_id, 45.00, "Transport", f"{year_month}-05", "Gas fill-up"),
            (user_id, 89.99, "Bills", f"{year_month}-07", "Electricity bill"),
            (user_id, 25.00, "Health", f"{year_month}-10", "Pharmacy"),
            (user_id, 15.00, "Entertainment", f"{year_month}-14", "Movie tickets"),
            (user_id, 60.00, "Shopping", f"{year_month}-18", "New shoes"),
            (user_id, 10.00, "Other", f"{year_month}-21", "Miscellaneous"),
            (user_id, 32.75, "Food", f"{year_month}-25", "Dinner out"),
        ]
        conn.executemany(
            """INSERT INTO expenses (user_id, amount, category, date, description)
               VALUES (?, ?, ?, ?, ?)""",
            sample_expenses,
        )
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Profile management helpers                                         #
# ------------------------------------------------------------------ #

# --- update_user (Subagent 1) ---
def update_user(user_id, name, email, preferred_currency):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET name = ?, email = ?, preferred_currency = ? WHERE id = ?",
            (name, email, preferred_currency, user_id),
        )
        conn.commit()
    finally:
        conn.close()

# --- update_user_password (Subagent 2) ---
def update_user_password(user_id, password_hash):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )
        conn.commit()
    finally:
        conn.close()

# --- delete_user (Subagent 3) ---
def delete_user(user_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM expenses WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
