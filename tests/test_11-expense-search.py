"""
Tests for Step 11: Expense Search.

Spec: .claude/specs/11-expense-search.md

These tests validate behavior only (route auth guard, filter semantics,
empty/prompt states, validation errors, uncapped result set, edit/delete
links surfaced from search results, and cross-user isolation) — not
implementation details of app.py/database/db.py. Fixtures (`app`, `client`,
`registered_user`, `auth_client`) come from tests/conftest.py.
`second_user`/`second_auth_client` are defined locally, mirroring the
pattern in tests/test_10-recurring-expenses.py, for cross-user isolation
checks.
"""

import re

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

def _insert_expense(user_id, amount, category, date, description=""):
    """Insert an expense directly via a parameterized query (test helper only)."""
    conn = db.get_db()
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


def _all_expenses_for(user_id):
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchall()
    finally:
        conn.close()


def _extract_panel_empty_text(body):
    """Pulls the text of the .panel-empty paragraph out of a search-page
    response body, so tests can compare the two distinct empty states
    (no-filters-yet prompt vs no-match) without hardcoding exact copy."""
    match = re.search(r'<p class="panel-empty">(.*?)</p>', body, re.DOTALL)
    return match.group(1).strip() if match else None


# ------------------------------------------------------------------ #
# Seed data                                                           #
# ------------------------------------------------------------------ #

@pytest.fixture
def seeded_expenses(registered_user):
    """A deterministic set of expenses for the registered_user, covering
    distinct descriptions/categories/amounts/dates so every filter type can
    be asserted precisely."""
    user_id = registered_user["id"]
    expenses = [
        # (amount, category, date, description)
        (4.50, "Food", "2026-01-10", "Morning Coffee"),
        (12.00, "Food", "2026-01-15", "Coffee with client"),
        (30.00, "Transport", "2026-01-20", "Bus pass"),
        (100.00, "Bills", "2026-02-01", "Electricity bill"),
        (250.00, "Shopping", "2026-02-15", "New laptop"),
    ]
    ids = {}
    for amount, category, date, description in expenses:
        eid = _insert_expense(user_id, amount, category, date, description)
        ids[description] = eid
    return {"rows": expenses, "ids": ids}


# ------------------------------------------------------------------ #
# Auth guard                                                          #
# ------------------------------------------------------------------ #

class TestAuthGuard:
    """GET /expenses/search redirects anonymous users to /login (spec:
    'Routes' section — logged-in required)."""

    def test_get_without_params_requires_login(self, client):
        resp = client.get("/expenses/search")
        assert resp.status_code == 302, "Expected redirect for unauthenticated GET"
        assert "/login" in resp.headers.get("Location", ""), (
            "Expected unauthenticated GET /expenses/search to redirect to /login"
        )

    def test_get_with_filters_requires_login(self, client):
        resp = client.get("/expenses/search?q=coffee")
        assert resp.status_code == 302, (
            "Expected redirect for unauthenticated GET even with query params"
        )
        assert "/login" in resp.headers.get("Location", ""), (
            "Expected unauthenticated filtered GET /expenses/search to redirect to /login"
        )


# ------------------------------------------------------------------ #
# No-filters-yet prompt state                                         #
# ------------------------------------------------------------------ #

class TestNoFiltersPromptState:
    """With no query params, the page shows the filter form and a prompt
    state — not the user's full expense history (spec Definition of Done:
    'shows the filter form and a "enter a filter to search" prompt state,
    not the full expense list')."""

    def test_get_no_params_returns_200(self, auth_client, seeded_expenses):
        resp = auth_client.get("/expenses/search")
        assert resp.status_code == 200, "Expected 200 for logged-in GET /expenses/search"

    def test_get_no_params_shows_prompt_not_full_history(self, auth_client, seeded_expenses):
        resp = auth_client.get("/expenses/search")
        body = resp.data.decode()
        assert "panel-empty" in body, "Expected the prompt empty-state to render"
        assert "transactions-table" not in body, (
            "Expected no results table when no filters are applied"
        )
        for _, _, _, description in seeded_expenses["rows"]:
            assert description not in body, (
                f"Expected unfiltered search page NOT to dump '{description}' "
                f"from the user's full expense history"
            )

    def test_get_no_params_shows_filter_form(self, auth_client):
        resp = auth_client.get("/expenses/search")
        body = resp.data.decode()
        assert "<form" in body, "Expected a filter form on the search page"
        assert 'name="q"' in body, "Expected a description/q input field"
        assert 'name="category"' in body, "Expected a category input field"
        assert 'name="min_amount"' in body, "Expected a min_amount input field"
        assert 'name="max_amount"' in body, "Expected a max_amount input field"
        assert 'name="start_date"' in body, "Expected a start_date input field"
        assert 'name="end_date"' in body, "Expected an end_date input field"

    def test_get_no_params_lists_all_categories_in_form(self, auth_client):
        resp = auth_client.get("/expenses/search")
        body = resp.data.decode()
        for category in db.CATEGORIES:
            assert category in body, f"Expected category '{category}' to appear in the filter form"


# ------------------------------------------------------------------ #
# Keyword search on description                                       #
# ------------------------------------------------------------------ #

class TestKeywordSearch:
    """Searching by a description substring returns only expenses whose
    description contains it, case-insensitively (spec Definition of Done)."""

    def test_keyword_matches_substring_case_insensitively(self, auth_client, seeded_expenses):
        resp = auth_client.get("/expenses/search?q=coffee")
        body = resp.data.decode()
        assert "Morning Coffee" in body, "Expected case-insensitive substring match"
        assert "Coffee with client" in body, "Expected case-insensitive substring match"
        assert "Bus pass" not in body
        assert "Electricity bill" not in body
        assert "New laptop" not in body

    def test_keyword_uppercase_query_still_matches(self, auth_client, seeded_expenses):
        resp = auth_client.get("/expenses/search?q=COFFEE")
        body = resp.data.decode()
        assert "Morning Coffee" in body, (
            "Expected an uppercase query to case-insensitively match a "
            "lowercase-ish stored description"
        )
        assert "Coffee with client" in body

    def test_keyword_partial_word_matches(self, auth_client, seeded_expenses):
        resp = auth_client.get("/expenses/search?q=lect")
        body = resp.data.decode()
        assert "Electricity bill" in body, "Expected mid-word substring match"
        assert "Morning Coffee" not in body


# ------------------------------------------------------------------ #
# Category filter                                                     #
# ------------------------------------------------------------------ #

class TestCategoryFilter:
    """Filtering by category alone returns only that category's expenses
    (spec Definition of Done)."""

    def test_category_filter_returns_only_matching_category(self, auth_client, seeded_expenses):
        resp = auth_client.get("/expenses/search?category=Food")
        body = resp.data.decode()
        assert "Morning Coffee" in body
        assert "Coffee with client" in body
        assert "Bus pass" not in body
        assert "Electricity bill" not in body
        assert "New laptop" not in body

    def test_category_filter_other_category_excludes_everything_else(self, auth_client, seeded_expenses):
        resp = auth_client.get("/expenses/search?category=Shopping")
        body = resp.data.decode()
        assert "New laptop" in body
        assert "Morning Coffee" not in body
        assert "Bus pass" not in body


# ------------------------------------------------------------------ #
# Amount range filter                                                 #
# ------------------------------------------------------------------ #

class TestAmountRangeFilter:
    """Filtering by min/max amount returns only expenses in that range,
    inclusive of both boundaries (spec Definition of Done)."""

    def test_amount_range_excludes_outside_values(self, auth_client, seeded_expenses):
        resp = auth_client.get("/expenses/search?min_amount=50&max_amount=150")
        body = resp.data.decode()
        assert "Electricity bill" in body, "Expected 100.00 to fall within [50, 150]"
        assert "Morning Coffee" not in body
        assert "Bus pass" not in body
        assert "New laptop" not in body, "250.00 must be excluded above max_amount=150"

    def test_amount_range_lower_boundary_inclusive(self, auth_client, seeded_expenses):
        resp = auth_client.get("/expenses/search?min_amount=100&max_amount=100")
        body = resp.data.decode()
        assert "Electricity bill" in body, (
            "Expected an expense exactly equal to min_amount==max_amount to be included"
        )

    def test_amount_range_min_only(self, auth_client, seeded_expenses):
        resp = auth_client.get("/expenses/search?min_amount=100")
        body = resp.data.decode()
        assert "Electricity bill" in body
        assert "New laptop" in body
        assert "Morning Coffee" not in body
        assert "Bus pass" not in body

    def test_amount_range_max_only(self, auth_client, seeded_expenses):
        resp = auth_client.get("/expenses/search?max_amount=30")
        body = resp.data.decode()
        assert "Morning Coffee" in body
        assert "Coffee with client" in body
        assert "Bus pass" in body, "30.00 must be included at max_amount==30 (inclusive)"
        assert "Electricity bill" not in body
        assert "New laptop" not in body


# ------------------------------------------------------------------ #
# Date range filter                                                   #
# ------------------------------------------------------------------ #

class TestDateRangeFilter:
    """Filtering by date range is inclusive of both boundary dates (spec
    Definition of Done)."""

    def test_date_range_excludes_outside_dates(self, auth_client, seeded_expenses):
        resp = auth_client.get(
            "/expenses/search?start_date=2026-01-10&end_date=2026-01-20"
        )
        body = resp.data.decode()
        assert "Morning Coffee" in body
        assert "Coffee with client" in body
        assert "Bus pass" in body
        assert "Electricity bill" not in body
        assert "New laptop" not in body

    def test_date_range_boundaries_are_inclusive(self, auth_client, seeded_expenses):
        resp = auth_client.get(
            "/expenses/search?start_date=2026-01-10&end_date=2026-01-10"
        )
        body = resp.data.decode()
        assert "Morning Coffee" in body, "Boundary date should be inclusive"
        assert "Coffee with client" not in body
        assert "Bus pass" not in body


# ------------------------------------------------------------------ #
# Combined / AND filter semantics                                     #
# ------------------------------------------------------------------ #

class TestCombinedFilters:
    """Combining multiple filters ANDs them together correctly (spec
    Definition of Done)."""

    def test_category_and_min_amount_ands_together(self, auth_client, seeded_expenses):
        # Food category has two rows: Morning Coffee (4.50) and Coffee with
        # client (12.00). min_amount=10 should exclude the cheaper one.
        resp = auth_client.get("/expenses/search?category=Food&min_amount=10")
        body = resp.data.decode()
        assert "Coffee with client" in body
        assert "Morning Coffee" not in body, (
            "Expected AND semantics: matches category but fails min_amount"
        )
        assert "Bus pass" not in body, (
            "Expected AND semantics: matches min_amount but fails category"
        )

    def test_category_date_and_amount_combo(self, auth_client, seeded_expenses):
        resp = auth_client.get(
            "/expenses/search?category=Food&start_date=2026-01-01"
            "&end_date=2026-01-31&min_amount=10&max_amount=20"
        )
        body = resp.data.decode()
        assert "Coffee with client" in body
        assert "Morning Coffee" not in body
        assert "Bus pass" not in body
        assert "Electricity bill" not in body

    def test_keyword_and_category_combo_excludes_nonmatching_category(
        self, auth_client, seeded_expenses
    ):
        resp = auth_client.get("/expenses/search?q=coffee&category=Transport")
        body = resp.data.decode()
        assert "Morning Coffee" not in body
        assert "Coffee with client" not in body
        assert "Bus pass" not in body


# ------------------------------------------------------------------ #
# No-match empty state (distinct from no-filters-yet prompt state)    #
# ------------------------------------------------------------------ #

class TestNoMatchEmptyState:
    """A search that matches nothing shows a distinct 'no expenses matched'
    empty state, not an error, and not the same message as the
    no-filters-yet prompt (spec Definition of Done)."""

    def test_no_match_returns_200_not_error(self, auth_client, seeded_expenses):
        resp = auth_client.get("/expenses/search?q=zzzznonexistentzzzz")
        assert resp.status_code == 200, "A no-match search should not be an error"

    def test_no_match_shows_distinct_empty_state(self, auth_client, seeded_expenses):
        resp = auth_client.get("/expenses/search?q=zzzznonexistentzzzz")
        body = resp.data.decode()
        assert "panel-empty" in body, "Expected the no-match empty state to use panel-empty"
        assert "transactions-table" not in body, (
            "Expected no results table when nothing matched"
        )

        no_filter_resp = auth_client.get("/expenses/search")
        no_filter_text = _extract_panel_empty_text(no_filter_resp.data.decode())
        no_match_text = _extract_panel_empty_text(body)

        assert no_filter_text is not None and no_match_text is not None, (
            "Expected both the no-filters and no-match states to render a "
            "panel-empty message"
        )
        assert no_filter_text != no_match_text, (
            "Expected the 'no filters applied yet' prompt and the 'no "
            "expenses matched' empty state to show distinct messages"
        )

    def test_no_match_does_not_error_on_valid_but_empty_result_filters(
        self, auth_client, seeded_expenses
    ):
        resp = auth_client.get("/expenses/search?category=Health")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "panel-empty" in body
        assert "transactions-table" not in body


# ------------------------------------------------------------------ #
# Validation errors                                                   #
# ------------------------------------------------------------------ #

class TestValidationErrors:
    """min_amount/max_amount must be validated as optional finite numbers;
    min>max is rejected (spec: 'Rules for implementation' + Templates ->
    error rendering)."""

    @pytest.mark.parametrize("bad_min", ["abc", "-5", "inf", "nan"])
    def test_invalid_min_amount_shows_error(self, auth_client, seeded_expenses, bad_min):
        resp = auth_client.get(f"/expenses/search?min_amount={bad_min}")
        assert resp.status_code == 200, "Invalid min_amount must not crash (no 500)"
        body = resp.data.decode()
        assert "error" in body.lower(), "Expected an error message for invalid min_amount"
        assert "transactions-table" not in body, (
            "Expected no results table to render when min_amount validation fails"
        )

    @pytest.mark.parametrize("bad_max", ["abc", "-5", "inf", "nan"])
    def test_invalid_max_amount_shows_error(self, auth_client, seeded_expenses, bad_max):
        resp = auth_client.get(f"/expenses/search?max_amount={bad_max}")
        assert resp.status_code == 200, "Invalid max_amount must not crash (no 500)"
        body = resp.data.decode()
        assert "error" in body.lower(), "Expected an error message for invalid max_amount"
        assert "transactions-table" not in body, (
            "Expected no results table to render when max_amount validation fails"
        )

    def test_min_greater_than_max_shows_error(self, auth_client, seeded_expenses):
        resp = auth_client.get("/expenses/search?min_amount=100&max_amount=10")
        assert resp.status_code == 200, "min>max must not crash (no 500)"
        body = resp.data.decode()
        assert "error" in body.lower(), (
            "Expected an error message when min_amount exceeds max_amount"
        )
        assert "Electricity bill" not in body, (
            "Expected no results to be shown/queried when the range is invalid"
        )

    def test_empty_min_and_max_with_other_filter_is_valid(self, auth_client, seeded_expenses):
        # Empty amount bounds mean "no bound", not an error (unlike
        # add/edit expense's required amount field).
        resp = auth_client.get("/expenses/search?category=Food&min_amount=&max_amount=")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "error" not in body.lower() or "Morning Coffee" in body, (
            "Empty min_amount/max_amount must be treated as unbounded, not "
            "a validation error"
        )
        assert "Morning Coffee" in body
        assert "Coffee with client" in body


# ------------------------------------------------------------------ #
# Uncapped result count                                                #
# ------------------------------------------------------------------ #

class TestUncappedResults:
    """Results are not capped at 6 (unlike /profile's recent-expenses list)
    — a filter matching many expenses shows all of them (spec Definition of
    Done: 'a filter matching 20 expenses shows all 20')."""

    def test_more_than_six_matches_all_render(self, auth_client, registered_user):
        user_id = registered_user["id"]
        total = 20
        for i in range(total):
            _insert_expense(
                user_id, 5.00 + i, "Entertainment", "2026-03-01",
                f"Bulk expense number {i:02d}",
            )

        resp = auth_client.get("/expenses/search?category=Entertainment")
        assert resp.status_code == 200
        body = resp.data.decode()

        for i in range(total):
            assert f"Bulk expense number {i:02d}" in body, (
                f"Expected uncapped search results to include item {i}, "
                f"not just the first 6"
            )

        # Sanity check against the DB directly too.
        rows = [
            r for r in _all_expenses_for(user_id) if r["category"] == "Entertainment"
        ]
        assert len(rows) == total


# ------------------------------------------------------------------ #
# Edit/Delete links work from search results                          #
# ------------------------------------------------------------------ #

class TestEditDeleteLinksFromSearchResults:
    """Each result row's Edit/Delete links/routes work exactly as they do
    on /profile (spec Definition of Done + Templates section)."""

    def test_result_row_contains_edit_and_delete_links(self, app, auth_client, seeded_expenses):
        expense_id = seeded_expenses["ids"]["Morning Coffee"]
        with app.app_context():
            from flask import url_for
            edit_url = url_for("edit_expense", id=expense_id)
            delete_url = url_for("delete_expense", id=expense_id)

        resp = auth_client.get("/expenses/search", query_string={"q": "Morning Coffee"})
        body = resp.data.decode()
        assert edit_url in body, "Expected an Edit link to the existing edit_expense route"
        assert delete_url in body, (
            "Expected a Delete form/link to the existing delete_expense route"
        )

    def test_edit_link_from_search_results_loads_edit_page(self, app, auth_client, seeded_expenses):
        expense_id = seeded_expenses["ids"]["Morning Coffee"]
        with app.app_context():
            from flask import url_for
            edit_url = url_for("edit_expense", id=expense_id)

        resp = auth_client.get(edit_url)
        assert resp.status_code == 200, "Expected the Edit link surfaced by search to work"
        body = resp.data.decode()
        assert "Morning Coffee" in body, "Expected the edit form to be pre-filled"

    def test_delete_link_from_search_results_deletes_expense(self, app, auth_client, seeded_expenses):
        expense_id = seeded_expenses["ids"]["Morning Coffee"]
        with app.app_context():
            from flask import url_for
            delete_url = url_for("delete_expense", id=expense_id)

        resp = auth_client.post(delete_url)
        assert resp.status_code == 302, "Expected the Delete route surfaced by search to work"
        assert db.get_expense_by_id(expense_id) is None, (
            "Expected the expense to actually be deleted"
        )

        # It must also disappear from subsequent search results. Check the
        # results panel specifically rather than the whole page body — the
        # search form legitimately echoes the submitted "q" value back into
        # its own input's value="..." attribute, so a blind substring check
        # for the deleted expense's description would false-positive on the
        # re-echoed query string itself.
        resp = auth_client.get("/expenses/search", query_string={"q": "Morning Coffee"})
        body = resp.data.decode()
        assert "transactions-table" not in body
        assert "panel-empty" in body


# ------------------------------------------------------------------ #
# Cross-user isolation                                                 #
# ------------------------------------------------------------------ #

class TestCrossUserIsolation:
    """A second logged-in user's search never returns the first user's
    expenses, even with an identical query (spec Definition of Done +
    'Ownership is implicit and total')."""

    def test_identical_query_does_not_leak_other_users_expenses(
        self, auth_client, registered_user, second_auth_client, second_user
    ):
        _insert_expense(
            registered_user["id"], 12.00, "Food", "2026-01-15", "Coffee with client"
        )
        _insert_expense(
            second_user["id"], 12.00, "Food", "2026-01-15", "Coffee with client"
        )

        first_resp = auth_client.get("/expenses/search?q=coffee")
        second_resp = second_auth_client.get("/expenses/search?q=coffee")

        assert first_resp.status_code == 200
        assert second_resp.status_code == 200

        first_body = first_resp.data.decode()
        second_body = second_resp.data.decode()

        assert "Coffee with client" in first_body
        assert "Coffee with client" in second_body

        first_rows = _all_expenses_for(registered_user["id"])
        second_rows = _all_expenses_for(second_user["id"])
        first_ids = {r["id"] for r in first_rows}
        second_ids = {r["id"] for r in second_rows}
        assert first_ids.isdisjoint(second_ids), (
            "Test setup sanity check: the two users' expense rows must be distinct"
        )

    def test_second_users_empty_search_unaffected_by_first_user(
        self, auth_client, registered_user, second_auth_client, second_user
    ):
        _insert_expense(
            registered_user["id"], 99.00, "Bills", "2026-04-01", "First user only expense"
        )

        resp = second_auth_client.get("/expenses/search?category=Bills")
        body = resp.data.decode()
        assert "First user only expense" not in body, (
            "A second user's category search must not return the first "
            "user's expenses"
        )
        assert "panel-empty" in body, (
            "Expected the second user's search (matching nothing of their own) "
            "to show the no-match empty state"
        )

    def test_second_user_broad_category_search_only_sees_own_rows(
        self, auth_client, registered_user, second_auth_client, second_user
    ):
        _insert_expense(
            registered_user["id"], 20.00, "Transport", "2026-01-01", "First user transport"
        )
        _insert_expense(
            second_user["id"], 20.00, "Transport", "2026-01-01", "Second user transport"
        )

        resp = second_auth_client.get("/expenses/search?category=Transport")
        body = resp.data.decode()
        assert "Second user transport" in body
        assert "First user transport" not in body, (
            "Expected the second user's search to be scoped strictly to their own user_id"
        )
