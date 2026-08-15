"""
Tests for Step 10: Recurring Expenses.

Spec: .claude/specs/10-recurring-expenses.md

These tests validate behavior only (routes, form validation, DB writes,
lazy-generation-on-/profile-load semantics, ownership, and idempotency) —
not implementation details of app.py/database/db.py. Fixtures (`app`,
`client`, `registered_user`, `auth_client`) come from tests/conftest.py.
`second_user`/`second_auth_client` are defined locally, mirroring the
pattern in tests/test_07-add-expense.py, for cross-user isolation checks.
"""

from datetime import date, datetime, timedelta

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

def _all_recurring_for(user_id):
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT * FROM recurring_expenses WHERE user_id = ?", (user_id,)
        ).fetchall()
    finally:
        conn.close()


def _count_all_recurring():
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM recurring_expenses"
        ).fetchone()["n"]
    finally:
        conn.close()


def _get_recurring_by_id(recurring_id):
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT * FROM recurring_expenses WHERE id = ?", (recurring_id,)
        ).fetchone()
    finally:
        conn.close()


def _all_expenses_for(user_id):
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchall()
    finally:
        conn.close()


def _count_all_expenses():
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()["n"]
    finally:
        conn.close()


def _expenses_matching_description(user_id, description):
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT * FROM expenses WHERE user_id = ? AND description = ? "
            "ORDER BY date ASC, id ASC",
            (user_id, description),
        ).fetchall()
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Date helpers — everything computed relative to date.today() so the  #
# suite stays correct regardless of what day it actually runs on.     #
# ------------------------------------------------------------------ #

def _date_str(d):
    return d.strftime("%Y-%m-%d")


def _today_str():
    return _date_str(date.today())


def _days_from_today(delta_days):
    return _date_str(date.today() + timedelta(days=delta_days))


VALID_PAYLOAD = {
    "amount": "1200",
    "category": "Bills",
    "interval": "monthly",
    "start_date": "2026-01-01",
    "description": "Rent",
}


# ------------------------------------------------------------------ #
# Auth guard                                                          #
# ------------------------------------------------------------------ #

class TestAuthGuard:
    """All three recurring-expense routes redirect anonymous users to
    /login (spec: 'Routes' section + Definition of Done: 'All new routes
    redirect anonymous users to /login')."""

    def test_get_list_requires_login(self, client):
        resp = client.get("/expenses/recurring")
        assert resp.status_code == 302, "Expected redirect for unauthenticated GET"
        assert "/login" in resp.headers.get("Location", ""), (
            "Expected unauthenticated GET /expenses/recurring to redirect to /login"
        )

    def test_post_add_requires_login(self, client):
        resp = client.post("/expenses/recurring/add", data=VALID_PAYLOAD)
        assert resp.status_code == 302, "Expected redirect for unauthenticated POST"
        assert "/login" in resp.headers.get("Location", ""), (
            "Expected unauthenticated POST /expenses/recurring/add to redirect to /login"
        )

    def test_post_add_while_logged_out_does_not_insert_row(self, client):
        before = _count_all_recurring()
        client.post("/expenses/recurring/add", data=VALID_PAYLOAD)
        after = _count_all_recurring()
        assert after == before, (
            "Unauthenticated POST must not insert a recurring_expenses row"
        )

    def test_post_delete_requires_login(self, client):
        resp = client.post("/expenses/recurring/999999/delete")
        assert resp.status_code == 302, "Expected redirect for unauthenticated POST"
        assert "/login" in resp.headers.get("Location", ""), (
            "Expected unauthenticated POST /expenses/recurring/<id>/delete to redirect to /login"
        )


# ------------------------------------------------------------------ #
# GET /expenses/recurring — list page                                 #
# ------------------------------------------------------------------ #

class TestListPage:
    """GET /expenses/recurring while logged in renders the list of
    templates plus a 'New recurring expense' form (spec: Templates ->
    templates/expenses_recurring.html)."""

    def test_get_returns_200(self, auth_client):
        resp = auth_client.get("/expenses/recurring")
        assert resp.status_code == 200, "Expected 200 for logged-in GET /expenses/recurring"

    def test_get_renders_form_landmarks(self, auth_client):
        resp = auth_client.get("/expenses/recurring")
        body = resp.data.decode()
        assert "<form" in body, "Expected an HTML form on the recurring-expenses page"
        assert 'name="amount"' in body, "Expected an amount input field"
        assert 'name="category"' in body, "Expected a category input field"
        assert 'name="interval"' in body, "Expected an interval input field"
        assert 'name="start_date"' in body, "Expected a start_date input field"
        assert 'name="description"' in body, "Expected a description input field"

    def test_get_lists_all_categories(self, auth_client):
        resp = auth_client.get("/expenses/recurring")
        body = resp.data.decode()
        for category in db.CATEGORIES:
            assert category in body, f"Expected category '{category}' to appear in the form"

    def test_get_with_no_templates_does_not_error(self, auth_client):
        resp = auth_client.get("/expenses/recurring")
        assert resp.status_code == 200, (
            "Expected the list page to render fine with zero recurring templates"
        )

    def test_get_lists_created_template(self, auth_client):
        auth_client.post("/expenses/recurring/add", data=VALID_PAYLOAD)
        resp = auth_client.get("/expenses/recurring")
        body = resp.data.decode()
        assert "Rent" in body, "Expected the created template's description to appear in the list"
        assert "Bills" in body, "Expected the created template's category to appear in the list"
        assert "monthly" in body.lower(), "Expected the created template's interval to appear in the list"


# ------------------------------------------------------------------ #
# POST /expenses/recurring/add — happy path                           #
# ------------------------------------------------------------------ #

class TestCreateHappyPath:
    """A valid POST creates a recurring_expenses row for the current user
    with next_run_date set correctly (spec Definition of Done: 'Creating a
    recurring expense ... saves a row in recurring_expenses with
    next_run_date set correctly')."""

    def test_valid_post_redirects(self, auth_client):
        resp = auth_client.post("/expenses/recurring/add", data=VALID_PAYLOAD)
        assert resp.status_code == 302, "Expected redirect on successful submission"

    def test_valid_post_inserts_row_for_current_user(self, auth_client, registered_user):
        before = _count_all_recurring()
        auth_client.post("/expenses/recurring/add", data=VALID_PAYLOAD)
        after = _count_all_recurring()
        assert after == before + 1, "Expected exactly one new recurring_expenses row"

        rows = _all_recurring_for(registered_user["id"])
        assert len(rows) == 1
        row = rows[0]
        assert row["user_id"] == registered_user["id"]
        assert row["amount"] == pytest.approx(1200.0)
        assert row["category"] == "Bills"
        assert row["interval"] == "monthly"
        assert row["description"] == "Rent"

    def test_valid_post_sets_next_run_date_to_start_date(self, auth_client, registered_user):
        auth_client.post("/expenses/recurring/add", data=VALID_PAYLOAD)
        rows = _all_recurring_for(registered_user["id"])
        assert rows[0]["next_run_date"] == VALID_PAYLOAD["start_date"], (
            "Expected next_run_date to be set to the submitted start_date on creation"
        )

    def test_weekly_interval_accepted(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "interval": "weekly", "description": "Weekly coffee"}
        resp = auth_client.post("/expenses/recurring/add", data=payload)
        assert resp.status_code == 302
        rows = _all_recurring_for(registered_user["id"])
        assert len(rows) == 1
        assert rows[0]["interval"] == "weekly"

    def test_empty_description_succeeds(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "description": ""}
        resp = auth_client.post("/expenses/recurring/add", data=payload)
        assert resp.status_code == 302, (
            "Expected successful redirect even with an empty description"
        )
        rows = _all_recurring_for(registered_user["id"])
        assert len(rows) == 1
        assert rows[0]["description"] in (None, ""), (
            "Expected empty description to be stored consistently as None/empty"
        )


# ------------------------------------------------------------------ #
# POST /expenses/recurring/add — validation                           #
# ------------------------------------------------------------------ #

class TestCreateValidationErrors:
    """Invalid submissions re-render the form with an error and insert no
    row (spec: 'Amount/date validation on the recurring-add form must reuse
    the same checks as add_expense'; 'interval validated against an
    explicit allow-list (weekly, monthly)')."""

    def _post_and_assert_rejected(self, auth_client, registered_user, payload):
        before = _count_all_recurring()
        resp = auth_client.post("/expenses/recurring/add", data=payload)
        assert resp.status_code == 200, (
            "Expected the form to be re-rendered (200) on validation failure, "
            "not a redirect"
        )
        body = resp.data.decode()
        assert "error" in body.lower(), (
            "Expected an error message in the re-rendered form"
        )
        after = _count_all_recurring()
        assert after == before, (
            "Validation failure must not insert a recurring_expenses row"
        )
        assert len(_all_recurring_for(registered_user["id"])) == 0

    def test_missing_amount(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "amount": ""}
        self._post_and_assert_rejected(auth_client, registered_user, payload)

    def test_non_numeric_amount(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "amount": "abc"}
        self._post_and_assert_rejected(auth_client, registered_user, payload)

    def test_zero_amount(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "amount": "0"}
        self._post_and_assert_rejected(auth_client, registered_user, payload)

    def test_negative_amount(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "amount": "-5"}
        self._post_and_assert_rejected(auth_client, registered_user, payload)

    def test_non_finite_amount(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "amount": "inf"}
        self._post_and_assert_rejected(auth_client, registered_user, payload)

    def test_missing_category(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "category": ""}
        self._post_and_assert_rejected(auth_client, registered_user, payload)

    def test_invalid_category(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "category": "NotARealCategory"}
        self._post_and_assert_rejected(auth_client, registered_user, payload)

    def test_missing_interval(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "interval": ""}
        self._post_and_assert_rejected(auth_client, registered_user, payload)

    @pytest.mark.parametrize(
        "bad_interval",
        [
            "daily",
            "yearly",
            "monsthly",   # common typo — must NOT be silently accepted as "monthly"
            "Monthly",    # allow-list match must be exact, not case-insensitive
            "WEEKLY",
        ],
    )
    def test_invalid_interval(self, auth_client, registered_user, bad_interval):
        payload = {**VALID_PAYLOAD, "interval": bad_interval}
        self._post_and_assert_rejected(auth_client, registered_user, payload)

    def test_missing_start_date(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "start_date": ""}
        self._post_and_assert_rejected(auth_client, registered_user, payload)

    @pytest.mark.parametrize(
        "bad_date",
        [
            "not-a-date",
            "03/15/2026",
            "2026-13-40",
            "2026/03/15",
        ],
    )
    def test_invalid_start_date(self, auth_client, registered_user, bad_date):
        payload = {**VALID_PAYLOAD, "start_date": bad_date}
        self._post_and_assert_rejected(auth_client, registered_user, payload)

    def test_rejected_form_redisplays_submitted_values(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "amount": "-5"}
        resp = auth_client.post("/expenses/recurring/add", data=payload)
        body = resp.data.decode()
        assert "Rent" in body, (
            "Expected submitted description to be redisplayed on validation failure"
        )


# ------------------------------------------------------------------ #
# /profile lazy-generation sync                                       #
# ------------------------------------------------------------------ #

class TestProfileSyncGeneration:
    """Visiting /profile calls the sync helper before reading expense data,
    so due occurrences appear immediately (spec: 'GET /profile is modified
    ... to call the sync helper before reading expense data')."""

    def test_due_template_generates_expense_on_profile_load(self, auth_client, registered_user):
        payload = {
            "amount": "1200",
            "category": "Bills",
            "interval": "monthly",
            "start_date": _today_str(),
            "description": "Rent due today",
        }
        auth_client.post("/expenses/recurring/add", data=payload)

        before = _count_all_expenses()
        auth_client.get("/profile")
        after = _count_all_expenses()

        assert after == before + 1, (
            "Expected exactly one expense row to be generated for a template "
            "due today on /profile load"
        )
        rows = _expenses_matching_description(registered_user["id"], "Rent due today")
        assert len(rows) == 1
        assert rows[0]["amount"] == pytest.approx(1200.0)
        assert rows[0]["category"] == "Bills"
        assert rows[0]["date"] == _today_str()

    def test_due_template_generated_expense_visible_in_profile_page(self, auth_client):
        payload = {
            "amount": "50",
            "category": "Food",
            "interval": "weekly",
            "start_date": _today_str(),
            "description": "Weekly groceries",
        }
        auth_client.post("/expenses/recurring/add", data=payload)
        resp = auth_client.get("/profile")
        body = resp.data.decode()
        assert "Weekly groceries" in body, (
            "Expected the newly generated recurring occurrence to appear in "
            "/profile's recent expenses"
        )

    def test_due_template_advances_next_run_date(self, auth_client, registered_user):
        payload = {
            "amount": "1200",
            "category": "Bills",
            "interval": "monthly",
            "start_date": _today_str(),
            "description": "Rent advance check",
        }
        auth_client.post("/expenses/recurring/add", data=payload)
        template_id = _all_recurring_for(registered_user["id"])[0]["id"]

        auth_client.get("/profile")

        updated = _get_recurring_by_id(template_id)
        assert updated["next_run_date"] != _today_str(), (
            "Expected next_run_date to advance past today after generating "
            "today's due occurrence"
        )
        next_run = datetime.strptime(updated["next_run_date"], "%Y-%m-%d").date()
        assert next_run > date.today(), (
            "Expected next_run_date to be strictly in the future after sync"
        )

    def test_future_template_does_not_generate_on_profile_load(self, auth_client, registered_user):
        payload = {
            "amount": "300",
            "category": "Shopping",
            "interval": "monthly",
            "start_date": _days_from_today(10),
            "description": "Future subscription",
        }
        auth_client.post("/expenses/recurring/add", data=payload)

        before = _count_all_expenses()
        auth_client.get("/profile")
        after = _count_all_expenses()

        assert after == before, (
            "A recurring template whose next_run_date is in the future must "
            "not generate an expense on /profile load"
        )
        rows = _all_recurring_for(registered_user["id"])
        assert rows[0]["next_run_date"] == payload["start_date"], (
            "Expected next_run_date to remain unchanged when not yet due"
        )

    def test_repeated_profile_loads_do_not_duplicate_generation(self, auth_client, registered_user):
        payload = {
            "amount": "1200",
            "category": "Bills",
            "interval": "monthly",
            "start_date": _today_str(),
            "description": "Idempotency rent",
        }
        auth_client.post("/expenses/recurring/add", data=payload)

        auth_client.get("/profile")
        count_after_first_sync = len(
            _expenses_matching_description(registered_user["id"], "Idempotency rent")
        )
        assert count_after_first_sync == 1, (
            "Expected exactly one generated occurrence after the first sync"
        )

        # Repeated loads, with nothing newly due, must not create duplicates.
        auth_client.get("/profile")
        auth_client.get("/profile")
        auth_client.get("/profile")

        count_after_repeated_syncs = len(
            _expenses_matching_description(registered_user["id"], "Idempotency rent")
        )
        assert count_after_repeated_syncs == 1, (
            "Repeated /profile loads without any newly-due occurrence must not "
            "create duplicate expense rows"
        )

    def test_backfill_generates_all_missed_weekly_occurrences(self, auth_client, registered_user):
        # Start far enough in the past that multiple weekly occurrences are
        # overdue by "today" — the sync helper must backfill all of them in
        # a single /profile load, not just the most recent one.
        weeks_missed = 5
        start = date.today() - timedelta(weeks=weeks_missed)
        start_str = _date_str(start)

        expected_count = 0
        cursor = start
        while cursor <= date.today():
            expected_count += 1
            cursor += timedelta(weeks=1)
        assert expected_count >= 2, "Test setup should guarantee multiple missed occurrences"

        payload = {
            "amount": "20",
            "category": "Food",
            "interval": "weekly",
            "start_date": start_str,
            "description": "Backfilled weekly coffee",
        }
        auth_client.post("/expenses/recurring/add", data=payload)

        auth_client.get("/profile")

        rows = _expenses_matching_description(registered_user["id"], "Backfilled weekly coffee")
        assert len(rows) == expected_count, (
            f"Expected {expected_count} backfilled occurrences for a template "
            f"{weeks_missed} weeks overdue, got {len(rows)}"
        )
        # First backfilled occurrence must be the original start date.
        assert rows[0]["date"] == start_str

        # A second /profile load with nothing newly due must not add more.
        auth_client.get("/profile")
        rows_after_second_load = _expenses_matching_description(
            registered_user["id"], "Backfilled weekly coffee"
        )
        assert len(rows_after_second_load) == expected_count, (
            "A second /profile load must not generate additional backfilled rows"
        )


# ------------------------------------------------------------------ #
# Month-end date clamping                                             #
# ------------------------------------------------------------------ #

class TestMonthEndClamping:
    """A monthly template starting on a month-end date (e.g. Jan 31) must
    keep generating valid calendar dates rather than overflowing into the
    next month (e.g. "Feb 31" does not exist and must clamp to Feb 28/29)."""

    def test_monthly_from_jan_31_clamps_to_valid_february_date(self, auth_client, registered_user):
        # 2026-01-31 is in the past relative to the test environment's date,
        # so it is immediately due and will backfill through subsequent
        # months up to "today".
        payload = {
            "amount": "100",
            "category": "Bills",
            "interval": "monthly",
            "start_date": "2026-01-31",
            "description": "Month-end rent clamp test",
        }
        auth_client.post("/expenses/recurring/add", data=payload)
        auth_client.get("/profile")

        rows = _expenses_matching_description(
            registered_user["id"], "Month-end rent clamp test"
        )
        dates = [r["date"] for r in rows]

        assert dates, "Expected at least the initial occurrence to be generated"
        assert dates[0] == "2026-01-31", "Expected the first occurrence to be the start date itself"

        # Every generated date must be a genuinely valid calendar date — this
        # is what would fail loudly (ValueError) if the app naively did
        # "day 31 in every month" without clamping.
        for d in dates:
            datetime.strptime(d, "%Y-%m-%d")

        if len(dates) >= 2:
            assert dates[1] == "2026-02-28", (
                "Expected the monthly advance from Jan 31 to clamp to the last "
                "valid day of February (28, since 2026 is not a leap year) "
                "rather than overflowing into March"
            )

    def test_monthly_from_jan_31_does_not_crash_sync(self, auth_client):
        payload = {
            "amount": "100",
            "category": "Bills",
            "interval": "monthly",
            "start_date": "2026-01-31",
            "description": "No crash on clamp",
        }
        auth_client.post("/expenses/recurring/add", data=payload)
        resp = auth_client.get("/profile")
        assert resp.status_code == 200, (
            "Expected /profile to load successfully even when backfilling a "
            "recurring template that started on a month-end date"
        )


# ------------------------------------------------------------------ #
# Ownership / user isolation                                          #
# ------------------------------------------------------------------ #

class TestOwnershipAndIsolation:
    """/expenses/recurring lists only the logged-in user's own templates;
    POST /expenses/recurring/<id>/delete for another user's template
    returns 404, matching edit_expense/delete_expense (spec Definition of
    Done)."""

    def test_list_shows_only_own_templates(
        self, auth_client, registered_user, second_auth_client, second_user
    ):
        auth_client.post(
            "/expenses/recurring/add",
            data={**VALID_PAYLOAD, "description": "First user rent"},
        )
        second_auth_client.post(
            "/expenses/recurring/add",
            data={**VALID_PAYLOAD, "description": "Second user rent"},
        )

        resp = auth_client.get("/expenses/recurring")
        body = resp.data.decode()
        # Plain strings (no apostrophes) so this comparison isn't affected by
        # Jinja2's default HTML autoescaping of the rendered description.
        assert "First user rent" in body
        assert "Second user rent" not in body, (
            "A user's recurring-expenses list must not show another user's templates"
        )

        first_rows = _all_recurring_for(registered_user["id"])
        second_rows = _all_recurring_for(second_user["id"])
        assert len(first_rows) == 1
        assert len(second_rows) == 1

    def test_delete_another_users_template_returns_404(
        self, auth_client, second_auth_client, second_user
    ):
        second_auth_client.post(
            "/expenses/recurring/add",
            data={**VALID_PAYLOAD, "description": "Not yours"},
        )
        other_template = _all_recurring_for(second_user["id"])[0]

        resp = auth_client.post(f"/expenses/recurring/{other_template['id']}/delete")
        assert resp.status_code == 404, (
            "Expected 404 (not a redirect) when deleting another user's "
            "recurring template"
        )

        # The other user's template must remain untouched.
        assert _get_recurring_by_id(other_template["id"]) is not None, (
            "Another user's recurring template must not be deleted by a "
            "non-owner's delete request"
        )

    def test_delete_nonexistent_template_returns_404(self, auth_client):
        resp = auth_client.post("/expenses/recurring/999999/delete")
        assert resp.status_code == 404

    def test_delete_own_template_succeeds(self, auth_client, registered_user):
        auth_client.post("/expenses/recurring/add", data=VALID_PAYLOAD)
        template = _all_recurring_for(registered_user["id"])[0]

        resp = auth_client.post(f"/expenses/recurring/{template['id']}/delete")
        assert resp.status_code == 302, "Expected redirect after successfully cancelling own template"

        assert _get_recurring_by_id(template["id"]) is None, (
            "Expected the recurring template to be deleted from the database"
        )
        assert len(_all_recurring_for(registered_user["id"])) == 0


# ------------------------------------------------------------------ #
# Cancel does not delete already-generated expenses                   #
# ------------------------------------------------------------------ #

class TestCancelDoesNotDeleteGeneratedExpenses:
    """Cancelling a recurring template stops future generation but does not
    delete already-generated expenses rows (spec Definition of Done)."""

    def test_cancel_preserves_already_generated_expense(self, auth_client, registered_user):
        payload = {
            "amount": "1200",
            "category": "Bills",
            "interval": "monthly",
            "start_date": _today_str(),
            "description": "Rent to be cancelled",
        }
        auth_client.post("/expenses/recurring/add", data=payload)

        # Generate today's due occurrence.
        auth_client.get("/profile")
        generated_before = _expenses_matching_description(
            registered_user["id"], "Rent to be cancelled"
        )
        assert len(generated_before) == 1, "Expected one occurrence generated before cancelling"

        template = _all_recurring_for(registered_user["id"])[0]
        resp = auth_client.post(f"/expenses/recurring/{template['id']}/delete")
        assert resp.status_code == 302

        # The already-generated expense row must still exist after cancelling.
        generated_after = _expenses_matching_description(
            registered_user["id"], "Rent to be cancelled"
        )
        assert len(generated_after) == 1, (
            "Cancelling a recurring template must not delete already-generated "
            "expenses rows"
        )
        assert generated_after[0]["id"] == generated_before[0]["id"]

    def test_cancel_stops_future_generation(self, auth_client, registered_user):
        payload = {
            "amount": "1200",
            "category": "Bills",
            "interval": "monthly",
            "start_date": _today_str(),
            "description": "Rent stop generation",
        }
        auth_client.post("/expenses/recurring/add", data=payload)
        auth_client.get("/profile")  # generates today's occurrence

        template = _all_recurring_for(registered_user["id"])[0]
        auth_client.post(f"/expenses/recurring/{template['id']}/delete")

        before = _count_all_expenses()
        # Further /profile loads must not generate anything more for the
        # now-cancelled template.
        auth_client.get("/profile")
        auth_client.get("/profile")
        after = _count_all_expenses()

        assert after == before, (
            "A cancelled recurring template must not generate further "
            "expenses on subsequent /profile loads"
        )
