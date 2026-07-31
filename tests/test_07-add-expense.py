"""
Tests for Step 7: Add Expense.

Spec: .claude/specs/07-add-expense.md

These tests validate behavior only (routes, form validation, DB writes,
redirects, and how the new expense is reflected on /profile) — not
implementation details of app.py/db.py. Fixtures (`app`, `client`,
`registered_user`, `auth_client`) come from tests/conftest.py.
"""

import pytest

import database.db as db


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


VALID_PAYLOAD = {
    "amount": "42.50",
    "category": "Food",
    "date": "2026-03-15",
    "description": "Groceries for the week",
}


class TestAuthGuard:
    """GET and POST to /expenses/add while logged out redirect to /login."""

    def test_get_requires_login(self, client):
        resp = client.get("/expenses/add")
        assert resp.status_code == 302, "Expected redirect for unauthenticated GET"
        assert "/login" in resp.headers.get("Location", ""), (
            "Expected unauthenticated GET /expenses/add to redirect to /login"
        )

    def test_post_requires_login(self, client):
        resp = client.post("/expenses/add", data=VALID_PAYLOAD)
        assert resp.status_code == 302, "Expected redirect for unauthenticated POST"
        assert "/login" in resp.headers.get("Location", ""), (
            "Expected unauthenticated POST /expenses/add to redirect to /login"
        )

    def test_post_while_logged_out_does_not_insert_row(self, client):
        before = _count_all_expenses()
        client.post("/expenses/add", data=VALID_PAYLOAD)
        after = _count_all_expenses()
        assert after == before, (
            "Unauthenticated POST must not insert an expense row"
        )


class TestGetRendersForm:
    """GET /expenses/add while logged in renders the add-expense form."""

    def test_get_returns_200(self, auth_client):
        resp = auth_client.get("/expenses/add")
        assert resp.status_code == 200, "Expected 200 for logged-in GET /expenses/add"

    def test_get_renders_form_landmarks(self, auth_client):
        resp = auth_client.get("/expenses/add")
        body = resp.data.decode()
        assert "<form" in body, "Expected an HTML form on the add-expense page"
        assert 'name="amount"' in body, "Expected an amount input field"
        assert 'name="category"' in body, "Expected a category input field"
        assert 'name="date"' in body, "Expected a date input field"
        assert 'name="description"' in body, "Expected a description input field"

    def test_get_lists_all_categories(self, auth_client):
        resp = auth_client.get("/expenses/add")
        body = resp.data.decode()
        for category in db.CATEGORIES:
            assert category in body, f"Expected category '{category}' to appear in the form"


class TestHappyPath:
    """A valid POST creates an expense for the current user and redirects
    to /profile, where it appears in recent expenses, summary totals, and
    category breakdown."""

    def test_valid_post_redirects_to_profile(self, auth_client):
        resp = auth_client.post("/expenses/add", data=VALID_PAYLOAD)
        assert resp.status_code == 302, "Expected redirect on successful submission"
        assert resp.headers.get("Location", "").endswith("/profile"), (
            "Expected successful add-expense submission to redirect to /profile"
        )

    def test_valid_post_inserts_row_for_current_user(self, auth_client, registered_user):
        before = _count_all_expenses()
        auth_client.post("/expenses/add", data=VALID_PAYLOAD)
        after = _count_all_expenses()
        assert after == before + 1, "Expected exactly one new row to be inserted"

        rows = _all_expenses_for(registered_user["id"])
        assert len(rows) == 1
        row = rows[0]
        assert row["user_id"] == registered_user["id"]
        assert row["amount"] == pytest.approx(42.50)
        assert row["category"] == "Food"
        assert row["date"] == "2026-03-15"
        assert row["description"] == "Groceries for the week"

    def test_valid_post_appears_in_profile_recent_expenses(self, auth_client):
        auth_client.post("/expenses/add", data=VALID_PAYLOAD)
        resp = auth_client.get("/profile")
        body = resp.data.decode()
        assert "Groceries for the week" in body, (
            "Expected newly added expense to appear in recent expenses on /profile"
        )

    def test_valid_post_reflected_in_summary_total(self, auth_client):
        auth_client.post("/expenses/add", data=VALID_PAYLOAD)
        resp = auth_client.get("/profile")
        body = resp.data.decode()
        assert "42.50" in body, (
            "Expected the new expense's amount to be reflected in the summary total"
        )

    def test_valid_post_reflected_in_category_breakdown(self, auth_client):
        auth_client.post("/expenses/add", data=VALID_PAYLOAD)
        resp = auth_client.get("/profile")
        body = resp.data.decode()
        assert "Food" in body, (
            "Expected the new expense's category to appear in the category breakdown"
        )

    def test_follow_redirect_lands_on_profile_page(self, auth_client):
        resp = auth_client.post(
            "/expenses/add", data=VALID_PAYLOAD, follow_redirects=True
        )
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Groceries for the week" in body


class TestEmptyDescription:
    """Submitting with an empty description succeeds without error."""

    def test_empty_description_succeeds(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "description": ""}
        resp = auth_client.post("/expenses/add", data=payload)
        assert resp.status_code == 302, (
            "Expected successful redirect even with an empty description"
        )
        assert resp.headers.get("Location", "").endswith("/profile")

        rows = _all_expenses_for(registered_user["id"])
        assert len(rows) == 1
        assert rows[0]["description"] in (None, ""), (
            "Expected empty description to be stored consistently as None/empty"
        )


class TestValidationErrors:
    """Invalid submissions re-render the form with an error and insert
    no row."""

    def _post_and_assert_rejected(self, auth_client, registered_user, payload):
        before = _count_all_expenses()
        resp = auth_client.post("/expenses/add", data=payload)
        assert resp.status_code == 200, (
            "Expected the form to be re-rendered (200) on validation failure, "
            "not a redirect"
        )
        body = resp.data.decode()
        assert "error" in body.lower(), (
            "Expected an error message in the re-rendered form"
        )
        after = _count_all_expenses()
        assert after == before, (
            "Validation failure must not insert an expense row"
        )
        assert len(_all_expenses_for(registered_user["id"])) == 0

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

    def test_missing_category(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "category": ""}
        self._post_and_assert_rejected(auth_client, registered_user, payload)

    def test_invalid_category(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "category": "NotARealCategory"}
        self._post_and_assert_rejected(auth_client, registered_user, payload)

    def test_missing_date(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "date": ""}
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
    def test_invalid_date(self, auth_client, registered_user, bad_date):
        payload = {**VALID_PAYLOAD, "date": bad_date}
        self._post_and_assert_rejected(auth_client, registered_user, payload)

    def test_rejected_form_redisplays_submitted_values(self, auth_client, registered_user):
        payload = {**VALID_PAYLOAD, "amount": "-5"}
        resp = auth_client.post("/expenses/add", data=payload)
        body = resp.data.decode()
        assert "Groceries for the week" in body, (
            "Expected submitted description to be redisplayed on validation failure"
        )


class TestUserIsolation:
    """The new expense is always inserted with user_id = session['user_id'],
    never another user's id."""

    def test_expense_belongs_only_to_current_user(
        self, auth_client, registered_user, second_auth_client, second_user
    ):
        # First user adds an expense.
        auth_client.post("/expenses/add", data=VALID_PAYLOAD)

        # Second user adds a different expense.
        second_payload = {
            "amount": "99.99",
            "category": "Transport",
            "date": "2026-04-01",
            "description": "Second user's ride",
        }
        second_auth_client.post("/expenses/add", data=second_payload)

        first_rows = _all_expenses_for(registered_user["id"])
        second_rows = _all_expenses_for(second_user["id"])

        assert len(first_rows) == 1
        assert len(second_rows) == 1
        assert first_rows[0]["user_id"] == registered_user["id"]
        assert second_rows[0]["user_id"] == second_user["id"]
        assert first_rows[0]["description"] == "Groceries for the week"
        assert second_rows[0]["description"] == "Second user's ride"

    def test_second_users_profile_does_not_show_first_users_expense(
        self, auth_client, second_auth_client
    ):
        auth_client.post("/expenses/add", data=VALID_PAYLOAD)

        resp = second_auth_client.get("/profile")
        body = resp.data.decode()
        assert "Groceries for the week" not in body, (
            "A second user's profile must not show another user's expense"
        )
