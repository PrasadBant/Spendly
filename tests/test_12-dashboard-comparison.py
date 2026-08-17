"""
Tests for Step 12: Dashboard Comparison.

Spec: .claude/specs/12-dashboard-comparison.md

These tests validate behavior only (auth guard, month-over-month totals,
division-by-zero guards, per-category inclusion/exclusion rules, currency
formatting, recurring-sync-before-summary ordering, nav active-state, and
cross-user isolation) — not implementation details of app.py's /analytics
route body. Fixtures (`app`, `client`, `registered_user`, `auth_client`)
come from tests/conftest.py. `second_user`/`second_auth_client` are defined
locally, mirroring the pattern in tests/test_10-recurring-expenses.py and
tests/test_11-expense-search.py, for cross-user isolation checks.

Month boundaries are never hardcoded to a specific calendar date: "this
month" data points always use date.today() itself (valid no matter what day
of the month it is, including the 1st), and "last month" data points use
the first/last day of the previous month, computed relative to
date.today(). This keeps the suite valid regardless of when it's run.
"""

import calendar
import re
from datetime import date, timedelta

import pytest

import database.db as db


# ------------------------------------------------------------------ #
# Local fixtures                                                      #
# ------------------------------------------------------------------ #

@pytest.fixture
def second_user(app):
    """A second, independent user for cross-contamination checks."""
    email = "seconduser@example.com"
    password = "otherpass123"
    user_id = db.create_user("Second User", email, password)
    return {"id": user_id, "email": email, "password": password}


@pytest.fixture
def second_auth_client(app, second_user):
    """A separate test client instance logged in as `second_user`."""
    c = app.test_client()
    c.post(
        "/login",
        data={"email": second_user["email"], "password": second_user["password"]},
    )
    return c


# ------------------------------------------------------------------ #
# DB helpers (test-side verification only — parameterised queries)    #
# ------------------------------------------------------------------ #

def _insert_expense(user_id, amount, category, expense_date, description=""):
    """Insert an expense directly via a parameterized query (test helper only)."""
    conn = db.get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, expense_date, description),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def _sum_amount_for_range(user_id, start_date, end_date):
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses "
            "WHERE user_id = ? AND date >= ? AND date <= ?",
            (user_id, start_date, end_date),
        ).fetchone()
        return row["total"]
    finally:
        conn.close()


def _count_expenses_matching(user_id, description):
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ? AND description = ?",
            (user_id, description),
        ).fetchone()
        return row["n"]
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Date helpers — everything computed relative to date.today() so the  #
# suite stays correct regardless of what day it actually runs on,     #
# including the 1st of the month (where "this month" is just today).  #
# ------------------------------------------------------------------ #

def _date_str(d):
    return d.strftime("%Y-%m-%d")


def _today_str():
    return _date_str(date.today())


def _current_month_range():
    """(first-of-month, today) as strings — a safe, always-valid range that
    covers every "this month" data point these tests insert (which are
    always dated exactly `today`)."""
    today = date.today()
    first = today.replace(day=1)
    return _date_str(first), _date_str(today)


def _last_day_of_previous_month():
    first_of_this_month = date.today().replace(day=1)
    return first_of_this_month - timedelta(days=1)


def _last_day_of_previous_month_str():
    return _date_str(_last_day_of_previous_month())


def _first_day_of_previous_month():
    return _last_day_of_previous_month().replace(day=1)


def _first_day_of_previous_month_str():
    return _date_str(_first_day_of_previous_month())


def _previous_month_range():
    return _first_day_of_previous_month_str(), _last_day_of_previous_month_str()


# ------------------------------------------------------------------ #
# HTML-parsing helpers (regex-based, tolerant of exact markup)        #
# ------------------------------------------------------------------ #

def _extract_percent_numbers(body):
    """Pulls every '<number>%' occurrence out of the page body so tests can
    check the computed percentage change without assuming exact formatting
    (decimal precision, a literal '+' prefix, etc.) beyond what the spec
    mandates."""
    return [float(m) for m in re.findall(r'(-?\d+(?:\.\d+)?)\s*%', body)]


def _snippet_after(body, marker, length=1200):
    """Returns a chunk of the body starting at `marker`, for scoping
    assertions to "near this category's row" without assuming exact table
    markup. Each category row renders two full comparison-bar-line blocks
    (this month + last month, each with a label, a bar div, and a value
    span) — length must be generous enough to reach the second block."""
    idx = body.find(marker)
    assert idx != -1, f"Expected '{marker}' to appear in the page at all"
    return body[idx: idx + length]


VALID_RECURRING_PAYLOAD = {
    "amount": "750",
    "category": "Bills",
    "interval": "monthly",
    "description": "Auto-generated rent",
}


# ------------------------------------------------------------------ #
# 1. Auth guard                                                       #
# ------------------------------------------------------------------ #

class TestAuthGuard:
    """Logged out -> GET /analytics redirects to /login (spec Definition
    of Done #1)."""

    def test_get_requires_login(self, client):
        resp = client.get("/analytics")
        assert resp.status_code == 302, "Expected redirect for unauthenticated GET /analytics"
        assert "/login" in resp.headers.get("Location", ""), (
            "Expected unauthenticated GET /analytics to redirect to /login"
        )

    def test_get_does_not_leak_data_while_logged_out(self, client, registered_user):
        # Even if some expenses exist for a real user, an anonymous request
        # must never render any dashboard content.
        _insert_expense(registered_user["id"], 500.00, "Food", _today_str(), "Should not leak")
        resp = client.get("/analytics")
        body = resp.data.decode()
        assert "Should not leak" not in body
        assert "500.00" not in body


# ------------------------------------------------------------------ #
# 2. No expenses at all                                               #
# ------------------------------------------------------------------ #

class TestNoExpensesEmptyState:
    """Logged in with no expenses at all: dashboard renders without error,
    both months show ₹0.00, % change shows 'N/A' (spec Definition of
    Done #2)."""

    def test_get_returns_200_with_no_expenses(self, auth_client):
        resp = auth_client.get("/analytics")
        assert resp.status_code == 200, (
            "Expected /analytics to render successfully (no crash) with zero expenses"
        )

    def test_both_month_totals_show_zero(self, auth_client):
        resp = auth_client.get("/analytics")
        body = resp.data.decode()
        assert body.count("₹0.00") >= 2, (
            "Expected both this-month and last-month totals to render as ₹0.00 "
            "when the user has no expenses at all"
        )

    def test_percent_change_shows_na_not_a_crash(self, auth_client):
        resp = auth_client.get("/analytics")
        assert resp.status_code == 200, "A zero-total comparison must not raise a 500"
        body = resp.data.decode()
        assert "N/A" in body, (
            "Expected an explicit 'N/A' state for % change when both months are "
            "₹0.00, not inf/NaN or a crash"
        )
        # A plain "nan" substring check false-positives on ordinary page text
        # (e.g. "finances" in the footer) — match "nan" only as a standalone
        # token so it actually targets a leaked float NaN, not incidental text.
        assert not re.search(r"(?<![a-z])nan(?![a-z])", body.lower()), (
            "Must not leak a raw NaN from a 0/0 computation"
        )


# ------------------------------------------------------------------ #
# 3. Expenses only in the current month                               #
# ------------------------------------------------------------------ #

class TestCurrentMonthOnlyExpenses:
    """Expenses only in the current month: current total correct, last
    month ₹0.00, % change shows 'New spending', not a divide-by-zero error
    (spec Definition of Done #3)."""

    def test_current_total_correct_and_last_month_zero(self, auth_client, registered_user):
        _insert_expense(registered_user["id"], 500.00, "Food", _today_str(), "Groceries")

        resp = auth_client.get("/analytics")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "₹500.00" in body, "Expected this month's total to be shown correctly"
        assert "₹0.00" in body, "Expected last month's total to show ₹0.00"

        db_total = _sum_amount_for_range(registered_user["id"], *_current_month_range())
        assert db_total == pytest.approx(500.00)

    def test_change_label_shows_new_spending(self, auth_client, registered_user):
        _insert_expense(registered_user["id"], 500.00, "Food", _today_str(), "Groceries")

        resp = auth_client.get("/analytics")
        assert resp.status_code == 200, (
            "Expected no crash (no 500/divide-by-zero) when last month's total is zero"
        )
        body = resp.data.decode()
        assert "New spending" in body, (
            "Expected an explicit 'New spending' state when last month is ₹0.00 "
            "and this month is greater than ₹0.00"
        )


# ------------------------------------------------------------------ #
# 4. Expenses in both months                                          #
# ------------------------------------------------------------------ #

class TestBothMonthsComparison:
    """Expenses in both this month and last month: both totals correct and
    % change calculated correctly, with sign matching direction (spec
    Definition of Done #4)."""

    def test_totals_correct_for_both_months(self, auth_client, registered_user):
        _insert_expense(registered_user["id"], 300.00, "Food", _today_str(), "This month spend")
        _insert_expense(
            registered_user["id"], 200.00, "Food", _last_day_of_previous_month_str(), "Last month spend"
        )

        resp = auth_client.get("/analytics")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "₹300.00" in body, "Expected this month's total to be shown correctly"
        assert "₹200.00" in body, "Expected last month's total to be shown correctly"

    def test_positive_percent_change_when_current_higher(self, auth_client, registered_user):
        _insert_expense(registered_user["id"], 300.00, "Food", _today_str(), "This month spend")
        _insert_expense(
            registered_user["id"], 200.00, "Food", _last_day_of_previous_month_str(), "Last month spend"
        )
        resp = auth_client.get("/analytics")
        body = resp.data.decode()

        expected_pct = (300.00 - 200.00) / 200.00 * 100  # +50.0%
        percents = _extract_percent_numbers(body)
        assert any(p > 0 and abs(p - expected_pct) < 1.0 for p in percents), (
            f"Expected a positive ~{expected_pct:.1f}% change on the page when this "
            f"month is higher than last month; found percentages: {percents}"
        )

    def test_negative_percent_change_when_current_lower(self, auth_client, registered_user):
        _insert_expense(registered_user["id"], 100.00, "Food", _today_str(), "This month spend")
        _insert_expense(
            registered_user["id"], 400.00, "Food", _last_day_of_previous_month_str(), "Last month spend"
        )
        resp = auth_client.get("/analytics")
        body = resp.data.decode()

        expected_pct = (100.00 - 400.00) / 400.00 * 100  # -75.0%
        percents = _extract_percent_numbers(body)
        assert any(p < 0 and abs(p - expected_pct) < 1.0 for p in percents), (
            f"Expected a negative ~{expected_pct:.1f}% change on the page when this "
            f"month is lower than last month; found percentages: {percents}"
        )


# ------------------------------------------------------------------ #
# 5. Recurring sync must run before the summary query                 #
# ------------------------------------------------------------------ #

class TestRecurringSyncBeforeSummary:
    """A recurring expense due today that hasn't been materialized yet
    still shows up in 'this month' total — sync_due_recurring_expenses
    must run before /analytics reads the summary, exactly like /profile
    does, without requiring a prior /profile visit (spec Definition of
    Done #5)."""

    def test_due_recurring_expense_included_without_visiting_profile_first(
        self, auth_client, registered_user
    ):
        payload = {**VALID_RECURRING_PAYLOAD, "start_date": _today_str()}
        create_resp = auth_client.post("/expenses/recurring/add", data=payload)
        assert create_resp.status_code == 302, (
            "Setup: expected recurring template creation to succeed"
        )

        before = _count_expenses_matching(registered_user["id"], "Auto-generated rent")
        assert before == 0, (
            "Setup sanity check: expected no materialized expense before /analytics is visited"
        )

        resp = auth_client.get("/analytics")
        assert resp.status_code == 200

        after = _count_expenses_matching(registered_user["id"], "Auto-generated rent")
        assert after == 1, (
            "Expected GET /analytics to call sync_due_recurring_expenses and "
            "materialize today's due occurrence before computing totals"
        )

        body = resp.data.decode()
        assert "₹750.00" in body, (
            "Expected the newly materialized recurring expense's amount to be "
            "reflected in this month's total on /analytics"
        )

        db_total = _sum_amount_for_range(registered_user["id"], *_current_month_range())
        assert db_total == pytest.approx(750.00), (
            "Expected the DB-side current-month sum to include the materialized "
            "recurring expense"
        )


# ------------------------------------------------------------------ #
# 6. Per-category panel includes spend in either month                #
# ------------------------------------------------------------------ #

class TestCategoryPanelInclusion:
    """Per-category panel shows every category with spend in either month,
    including a category with spend last month but none this month, shown
    as ₹0.00 this month rather than omitted (spec Definition of Done #6)."""

    def test_last_month_only_category_still_appears_with_zero_this_month(
        self, auth_client, registered_user
    ):
        _insert_expense(
            registered_user["id"], 1200.00, "Entertainment",
            _last_day_of_previous_month_str(), "Movie night",
        )
        _insert_expense(
            registered_user["id"], 100.00, "Food", _today_str(), "Groceries",
        )

        resp = auth_client.get("/analytics")
        assert resp.status_code == 200
        body = resp.data.decode()

        assert "Entertainment" in body, (
            "Expected a category with spend only last month to still appear "
            "in the per-category panel, not be silently dropped"
        )
        snippet = _snippet_after(body, "Entertainment")
        assert "1,200.00" in snippet, (
            "Expected last month's Entertainment total to be shown near the category"
        )
        assert "0.00" in snippet, (
            "Expected this month's Entertainment total to be shown as ₹0.00, not omitted"
        )

    def test_current_month_only_category_also_appears(self, auth_client, registered_user):
        _insert_expense(registered_user["id"], 75.00, "Transport", _today_str(), "Taxi")

        resp = auth_client.get("/analytics")
        body = resp.data.decode()
        assert "Transport" in body, (
            "Expected a category with spend only this month to appear in the panel"
        )
        snippet = _snippet_after(body, "Transport")
        assert "75.00" in snippet


# ------------------------------------------------------------------ #
# 7. Per-category panel excludes zero-in-both-months categories       #
# ------------------------------------------------------------------ #

class TestCategoryPanelExclusion:
    """Per-category panel does NOT show categories with ₹0.00 in both
    months (spec Definition of Done #7)."""

    def test_untouched_categories_are_not_listed(self, auth_client, registered_user):
        _insert_expense(registered_user["id"], 100.00, "Food", _today_str(), "Groceries")
        _insert_expense(
            registered_user["id"], 50.00, "Transport", _last_day_of_previous_month_str(), "Bus pass"
        )

        resp = auth_client.get("/analytics")
        assert resp.status_code == 200
        body = resp.data.decode()

        untouched_categories = [
            c for c in db.CATEGORIES if c not in ("Food", "Transport")
        ]
        assert untouched_categories, "Setup sanity check: expected other categories to test against"
        for category in untouched_categories:
            assert category not in body, (
                f"Category '{category}' has ₹0.00 in both months and must not "
                f"appear in the per-category panel"
            )


# ------------------------------------------------------------------ #
# 8. Currency formatting                                              #
# ------------------------------------------------------------------ #

class TestCurrencyFormatting:
    """All amounts formatted with a ₹ prefix, thousands separator, and 2
    decimals, matching the rest of the app (spec Definition of Done #8)."""

    def test_amount_uses_thousands_separator_and_two_decimals(self, auth_client, registered_user):
        _insert_expense(registered_user["id"], 12345.6, "Shopping", _today_str(), "Big purchase")
        _insert_expense(
            registered_user["id"], 999.99, "Food", _last_day_of_previous_month_str(), "Last month meal"
        )

        resp = auth_client.get("/analytics")
        assert resp.status_code == 200
        body = resp.data.decode()

        assert "₹12,345.60" in body, "Expected a large amount to use a thousands separator"
        assert "₹999.99" in body, "Expected a sub-thousand amount to render without a stray separator"

    def test_all_currency_values_match_app_wide_format(self, auth_client, registered_user):
        _insert_expense(registered_user["id"], 12345.6, "Shopping", _today_str(), "Big purchase")
        _insert_expense(
            registered_user["id"], 999.99, "Food", _last_day_of_previous_month_str(), "Last month meal"
        )

        resp = auth_client.get("/analytics")
        body = resp.data.decode()

        currency_values = re.findall(r'₹[\d,]+\.\d{2}', body)
        assert currency_values, "Expected at least one ₹-formatted currency value on the page"
        for value in currency_values:
            assert re.fullmatch(r'₹\d{1,3}(,\d{3})*\.\d{2}', value), (
                f"Currency value '{value}' does not match the app-wide "
                f"'₹{{:,.2f}}' format used elsewhere (profile.html, expenses_search.html)"
            )


# ------------------------------------------------------------------ #
# 9. Cross-user isolation                                             #
# ------------------------------------------------------------------ #

class TestCrossUserIsolation:
    """A second logged-in user sees only their own totals, never another
    user's data (spec Definition of Done #9)."""

    def test_each_user_sees_only_own_totals(
        self, auth_client, registered_user, second_auth_client, second_user
    ):
        _insert_expense(registered_user["id"], 555.00, "Food", _today_str(), "User1 current")
        _insert_expense(
            registered_user["id"], 111.00, "Food", _last_day_of_previous_month_str(), "User1 last month"
        )
        _insert_expense(second_user["id"], 8888.00, "Shopping", _today_str(), "User2 current")
        _insert_expense(
            second_user["id"], 2222.00, "Shopping", _last_day_of_previous_month_str(), "User2 last month"
        )

        first_resp = auth_client.get("/analytics")
        second_resp = second_auth_client.get("/analytics")
        assert first_resp.status_code == 200
        assert second_resp.status_code == 200

        first_body = first_resp.data.decode()
        second_body = second_resp.data.decode()

        assert "₹555.00" in first_body
        assert "₹111.00" in first_body
        assert "₹8,888.00" not in first_body, "User1 must never see User2's totals"
        assert "₹2,222.00" not in first_body, "User1 must never see User2's totals"

        assert "₹8,888.00" in second_body
        assert "₹2,222.00" in second_body
        assert "₹555.00" not in second_body, "User2 must never see User1's totals"
        assert "₹111.00" not in second_body, "User2 must never see User1's totals"

        first_db_total = _sum_amount_for_range(registered_user["id"], *_current_month_range())
        second_db_total = _sum_amount_for_range(second_user["id"], *_current_month_range())
        assert first_db_total == pytest.approx(555.00)
        assert second_db_total == pytest.approx(8888.00)

    def test_second_users_category_panel_excludes_first_users_category(
        self, auth_client, registered_user, second_auth_client, second_user
    ):
        _insert_expense(registered_user["id"], 300.00, "Health", _today_str(), "User1 only category")

        resp = second_auth_client.get("/analytics")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Health" not in body, (
            "A category that only the first user spent in must not leak into "
            "the second user's per-category panel"
        )


# ------------------------------------------------------------------ #
# 10. Nav "Analytics" link                                            #
# ------------------------------------------------------------------ #

class TestNavAnalyticsLink:
    """Nav 'Analytics' link points to /analytics and gets the active class
    on this page (spec Definition of Done #10)."""

    def test_nav_link_points_to_analytics_route(self, app, auth_client):
        with app.app_context():
            from flask import url_for
            analytics_url = url_for("analytics")

        resp = auth_client.get(analytics_url)
        body = resp.data.decode()
        assert analytics_url in body, "Expected the nav to link to the /analytics route"

    def test_nav_link_has_active_class_on_analytics_page(self, app, auth_client):
        with app.app_context():
            from flask import url_for
            analytics_url = url_for("analytics")

        resp = auth_client.get(analytics_url)
        body = resp.data.decode()
        match = re.search(r'<a[^>]*href="' + re.escape(analytics_url) + r'"[^>]*>', body)
        assert match is not None, "Expected an anchor tag linking to /analytics in the nav"
        assert "active" in match.group(0), (
            "Expected the Analytics nav link to carry the 'active' class while on /analytics"
        )

    def test_nav_link_not_active_on_other_pages(self, app, auth_client):
        with app.app_context():
            from flask import url_for
            analytics_url = url_for("analytics")

        resp = auth_client.get("/profile")
        body = resp.data.decode()
        match = re.search(r'<a[^>]*href="' + re.escape(analytics_url) + r'"[^>]*>', body)
        assert match is not None, "Expected the Analytics nav link to still be present on /profile"
        assert "active" not in match.group(0), (
            "Expected the Analytics nav link to NOT carry the 'active' class on /profile"
        )
