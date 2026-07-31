import os
import sqlite3
from datetime import datetime

from werkzeug.security import generate_password_hash

# Resolve DB path relative to project root (parent of database/), not cwd.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "expense_tracker.db")

CATEGORIES = [
    "Food", "Transport", "Bills", "Health",
    "Entertainment", "Shopping", "Other",
]


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


def create_expense(user_id, amount, category, date, description):
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, date, description),
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


def update_expense(expense_id, amount, category, date, description):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE expenses SET amount = ?, category = ?, date = ?, description = ? "
            "WHERE id = ?",
            (amount, category, date, description, expense_id),
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
        conn.commit()
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
def update_user(user_id, name, email):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET name = ?, email = ? WHERE id = ?",
            (name, email, user_id),
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
