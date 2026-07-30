"""
Tests for Step 6: Date Filter For Profile Page.

Spec: .claude/specs/06-date-filter-profile.md

These tests validate behavior only (query params, response content, DB
read-only guarantees) — not implementation details of app.py/db.py.
"""

import pytest

import database.db as db


def _insert_expense(user_id, amount, category, date, description=""):
    """Insert an expense directly via a parameterized query (test helper only)."""
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, date, description),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def seeded_expenses(registered_user):
    """A deterministic set of expenses spanning several months for the
    registered_user, so date-range filtering can be asserted precisely.
    """
    user_id = registered_user["id"]
    expenses = [
        # (amount, category, date, description)
        (10.00, "Food", "2026-01-05", "January food"),
        (20.00, "Transport", "2026-02-10", "February transport"),
        (30.00, "Bills", "2026-03-15", "March bills"),
        (40.00, "Food", "2026-04-20", "April food"),
        (50.00, "Health", "2026-05-25", "May health"),
    ]
    for amount, category, date, description in expenses:
        _insert_expense(user_id, amount, category, date, description)
    return expenses


class TestNoFilterUnchangedBehavior:
    """GET /profile with no query params -> unchanged all-time behavior."""

    def test_profile_no_params_shows_all_expenses(self, auth_client, seeded_expenses):
        resp = auth_client.get("/profile")
        assert resp.status_code == 200, "Expected 200 for logged-in /profile"
        body = resp.data.decode()
        # All-time total should be sum of all seeded amounts.
        total = sum(e[0] for e in seeded_expenses)
        assert f"{total:.2f}" in body or str(total) in body, (
            "Expected all-time total to reflect the sum of all expenses "
            "when no date filter is applied"
        )
        # All descriptions should be discoverable (only 5 expenses, well under
        # the 6-item recent-expenses limit).
        for _, _, _, description in seeded_expenses:
            assert description.encode() in resp.data, (
                f"Expected unfiltered /profile to include expense '{description}'"
            )

    def test_profile_no_params_no_clear_filter_link(self, auth_client, seeded_expenses):
        resp = auth_client.get("/profile")
        body = resp.data.decode()
        assert "Clear filter" not in body, (
            "Clear filter link should not appear when no filter is active"
        )


class TestValidDateRangeFilter:
    """GET /profile?start_date=...&end_date=... with a valid range narrows results."""

    def test_valid_range_narrows_recent_expenses(self, auth_client, seeded_expenses):
        # Range covers only February and March expenses.
        resp = auth_client.get("/profile?start_date=2026-02-01&end_date=2026-03-31")
        assert resp.status_code == 200
        body = resp.data.decode()

        assert "February transport" in body, "Expected in-range expense to be shown"
        assert "March bills" in body, "Expected in-range expense to be shown"
        assert "January food" not in body, "Expected out-of-range expense to be excluded"
        assert "April food" not in body, "Expected out-of-range expense to be excluded"
        assert "May health" not in body, "Expected out-of-range expense to be excluded"

    def test_valid_range_narrows_summary_total(self, auth_client, seeded_expenses):
        resp = auth_client.get("/profile?start_date=2026-02-01&end_date=2026-03-31")
        body = resp.data.decode()
        # Feb (20.00) + March (30.00) = 50.00
        assert "50.00" in body, (
            "Expected summary total to reflect only the expenses within "
            "the filtered date range (20.00 + 30.00 = 50.00)"
        )
        # Unfiltered total (150.00) should not appear as the headline total.
        assert "150.00" not in body

    def test_valid_range_narrows_category_breakdown(self, auth_client, seeded_expenses):
        resp = auth_client.get("/profile?start_date=2026-02-01&end_date=2026-03-31")
        body = resp.data.decode()
        assert "Transport" in body
        assert "Bills" in body
        # Categories entirely outside the range should not appear in the
        # breakdown at all.
        assert "Health" not in body, (
            "Category with no expenses in range should be excluded from breakdown"
        )

    def test_valid_range_boundaries_are_inclusive(self, auth_client, seeded_expenses):
        # Exact single-day range matching one expense's date exactly.
        resp = auth_client.get("/profile?start_date=2026-03-15&end_date=2026-03-15")
        body = resp.data.decode()
        assert "March bills" in body, "Boundary dates should be inclusive"
        assert "February transport" not in body
        assert "April food" not in body


class TestFilterFormRedisplay:
    """Filter form inputs redisplay the submitted start_date/end_date values."""

    def test_form_redisplays_submitted_dates(self, auth_client, seeded_expenses):
        resp = auth_client.get("/profile?start_date=2026-02-01&end_date=2026-03-31")
        body = resp.data.decode()
        assert "2026-02-01" in body, "Expected submitted start_date to be redisplayed"
        assert "2026-03-31" in body, "Expected submitted end_date to be redisplayed"

    def test_form_has_no_preset_dates_without_filter(self, auth_client, seeded_expenses):
        resp = auth_client.get("/profile")
        body = resp.data.decode()
        assert "2026-02-01" not in body
        assert "2026-03-31" not in body


class TestClearFilterLink:
    """Clear filter link appears only when a filter is active, links to /profile."""

    def test_clear_filter_link_appears_when_filter_active(self, auth_client, seeded_expenses):
        resp = auth_client.get("/profile?start_date=2026-02-01&end_date=2026-03-31")
        body = resp.data.decode()
        assert "Clear filter" in body, (
            "Expected 'Clear filter' link to appear when a date filter is active"
        )

    def test_clear_filter_link_points_to_plain_profile(self, auth_client, seeded_expenses):
        resp = auth_client.get("/profile?start_date=2026-02-01&end_date=2026-03-31")
        body = resp.data.decode()
        assert 'href="/profile"' in body, (
            "Expected 'Clear filter' link to point back to plain /profile"
        )
        # Ensure the clear link itself does not retain the query string.
        assert 'href="/profile?start_date' not in body


class TestInvalidDateHandling:
    """Invalid/malformed dates and start>end fall back to unfiltered, no 500."""

    @pytest.mark.parametrize(
        "start_date,end_date",
        [
            ("not-a-date", "2026-03-31"),
            ("2026-02-01", "not-a-date"),
            ("02/01/2026", "03/31/2026"),
            ("2026-13-40", "2026-14-50"),
        ],
    )
    def test_malformed_dates_fall_back_to_unfiltered(
        self, auth_client, seeded_expenses, start_date, end_date
    ):
        resp = auth_client.get(
            f"/profile?start_date={start_date}&end_date={end_date}"
        )
        assert resp.status_code == 200, "Malformed dates must not cause a 500"
        body = resp.data.decode()
        # Falls back to unfiltered -> all expenses visible.
        for _, _, _, description in seeded_expenses:
            assert description.encode() in resp.data, (
                f"Expected unfiltered fallback to include '{description}' "
                f"when dates are malformed"
            )

    def test_empty_start_date_is_treated_as_open_ended_not_malformed(
        self, auth_client, seeded_expenses
    ):
        # An empty start_date with a valid end_date is a one-sided range
        # (no lower bound), not a malformed input -- it should narrow results
        # to date <= end_date rather than falling back to fully unfiltered.
        resp = auth_client.get("/profile?start_date=&end_date=2026-03-31")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "January food" in body
        assert "February transport" in body
        assert "March bills" in body
        assert "April food" not in body
        assert "May health" not in body

    def test_malformed_dates_no_clear_filter_link(self, auth_client, seeded_expenses):
        resp = auth_client.get("/profile?start_date=garbage&end_date=garbage")
        body = resp.data.decode()
        assert "Clear filter" not in body, (
            "Since malformed dates fall back to unfiltered, no active filter "
            "should be indicated"
        )

    def test_start_after_end_falls_back_to_unfiltered(self, auth_client, seeded_expenses):
        resp = auth_client.get("/profile?start_date=2026-04-01&end_date=2026-01-01")
        assert resp.status_code == 200, "start_date after end_date must not cause a 500"
        body = resp.data.decode()
        for _, _, _, description in seeded_expenses:
            assert description.encode() in resp.data, (
                f"Expected unfiltered fallback to include '{description}' "
                f"when start_date is after end_date"
            )

    def test_start_after_end_no_clear_filter_link(self, auth_client, seeded_expenses):
        resp = auth_client.get("/profile?start_date=2026-04-01&end_date=2026-01-01")
        body = resp.data.decode()
        assert "Clear filter" not in body


class TestAuthGuard:
    """/profile (with or without query params) redirects to /login when logged out."""

    def test_profile_no_params_requires_login(self, client):
        resp = client.get("/profile")
        assert resp.status_code == 302, "Expected redirect for unauthenticated /profile"
        assert "/login" in resp.headers.get("Location", ""), (
            "Expected unauthenticated /profile to redirect to /login"
        )

    def test_profile_with_params_requires_login(self, client):
        resp = client.get("/profile?start_date=2026-02-01&end_date=2026-03-31")
        assert resp.status_code == 302, (
            "Expected redirect for unauthenticated /profile even with query params"
        )
        assert "/login" in resp.headers.get("Location", ""), (
            "Expected unauthenticated filtered /profile to redirect to /login"
        )


class TestHelpersAreReadOnly:
    """Date-filtering helpers must only read data, never mutate it, when
    called with a start_date/end_date range."""

    def test_get_user_expense_summary_does_not_mutate(self, app, registered_user, seeded_expenses):
        user_id = registered_user["id"]
        with app.app_context():
            before = db.get_user_expenses(user_id)
            db.get_user_expense_summary(user_id, start_date="2026-02-01", end_date="2026-03-31")
            after = db.get_user_expenses(user_id)
        assert len(before) == len(after) == len(seeded_expenses), (
            "get_user_expense_summary must not add/remove/modify expense rows"
        )

    def test_get_category_breakdown_does_not_mutate(self, app, registered_user, seeded_expenses):
        user_id = registered_user["id"]
        with app.app_context():
            before = db.get_user_expenses(user_id)
            db.get_category_breakdown(user_id, start_date="2026-02-01", end_date="2026-03-31")
            after = db.get_user_expenses(user_id)
        assert len(before) == len(after) == len(seeded_expenses), (
            "get_category_breakdown must not add/remove/modify expense rows"
        )

    def test_get_user_expenses_does_not_mutate(self, app, registered_user, seeded_expenses):
        user_id = registered_user["id"]
        with app.app_context():
            before = db.get_user_expenses(user_id)
            db.get_user_expenses(
                user_id, limit=6, start_date="2026-02-01", end_date="2026-03-31"
            )
            after = db.get_user_expenses(user_id)
        before_ids = {row["id"] for row in before}
        after_ids = {row["id"] for row in after}
        assert before_ids == after_ids, (
            "get_user_expenses must not add/remove expense rows when filtering"
        )
        assert len(before) == len(seeded_expenses), (
            "Expected expense row count to remain stable across filtered reads"
        )
