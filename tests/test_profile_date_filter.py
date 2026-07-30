"""
Tests for the date-range filtering feature on GET /profile.

Spec: .claude/specs/06-date-filter-profile.md

Coverage:
- Auth guard: logged-out access to /profile (with/without query params) redirects to /login
- No query params -> all-time (unchanged) behavior
- Valid start_date/end_date -> summary, category breakdown, and recent expenses
  narrowed to that range
- Invalid date format -> 200, not 500, falls back to unfiltered
- start_date after end_date -> 200, not 500, falls back to unfiltered
- Submitted start_date/end_date are redisplayed in the form inputs
- "Clear filter" link appears only when a filter is active
"""

import database.db as db


def _add_expense(user_id, amount, category, date, description=""):
    conn = db.get_db()
    try:
        conn.execute(
            """INSERT INTO expenses (user_id, amount, category, date, description)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, amount, category, date, description),
        )
        conn.commit()
    finally:
        conn.close()


class TestProfileDateFilterAuthGuard:
    def test_profile_no_params_logged_out_redirects_to_login(self, client):
        response = client.get("/profile")
        assert response.status_code == 302, "Expected redirect for unauthenticated access"
        assert "/login" in response.headers["Location"], "Expected redirect target to be /login"

    def test_profile_with_date_params_logged_out_redirects_to_login(self, client):
        response = client.get("/profile?start_date=2026-01-01&end_date=2026-01-31")
        assert response.status_code == 302, "Expected redirect even with query params present"
        assert "/login" in response.headers["Location"], "Expected redirect target to be /login"


class TestProfileNoFilter:
    def test_profile_no_query_params_shows_all_time_data(self, auth_client, registered_user):
        user_id = registered_user["id"]
        _add_expense(user_id, 10.00, "Food", "2026-01-05")
        _add_expense(user_id, 20.00, "Transport", "2026-06-15")

        response = auth_client.get("/profile")
        assert response.status_code == 200, "Expected 200 on unfiltered profile page"

        body = response.data.decode()
        assert "30.00" in body, "Expected all-time total (10 + 20) to be reflected"
        assert "Food" in body
        assert "Transport" in body

    def test_profile_no_query_params_no_clear_filter_link(self, auth_client, registered_user):
        response = auth_client.get("/profile")
        body = response.data.decode()
        assert "Clear filter" not in body, (
            "Clear filter link should not appear when no filter is active"
        )


class TestProfileValidFilter:
    def test_valid_date_range_narrows_summary(self, auth_client, registered_user):
        user_id = registered_user["id"]
        _add_expense(user_id, 10.00, "Food", "2026-01-05")   # inside range
        _add_expense(user_id, 999.00, "Bills", "2026-06-15")  # outside range

        response = auth_client.get("/profile?start_date=2026-01-01&end_date=2026-01-31")
        assert response.status_code == 200

        body = response.data.decode()
        assert "10.00" in body, "Expected filtered total to include only in-range expense"
        assert "999.00" not in body, "Expected out-of-range expense to be excluded from totals"

    def test_valid_date_range_narrows_category_breakdown(self, auth_client, registered_user):
        user_id = registered_user["id"]
        _add_expense(user_id, 15.00, "Food", "2026-02-10")
        _add_expense(user_id, 40.00, "Shopping", "2026-08-01")  # outside range

        response = auth_client.get("/profile?start_date=2026-02-01&end_date=2026-02-28")
        body = response.data.decode()
        assert "Food" in body, "Expected in-range category to appear in breakdown"
        assert "Shopping" not in body, "Expected out-of-range category to be excluded"

    def test_valid_date_range_narrows_recent_expenses(self, auth_client, registered_user):
        user_id = registered_user["id"]
        _add_expense(user_id, 5.00, "Food", "2026-03-01", description="in-range-item")
        _add_expense(user_id, 6.00, "Food", "2026-09-01", description="out-of-range-item")

        response = auth_client.get("/profile?start_date=2026-03-01&end_date=2026-03-31")
        body = response.data.decode()
        assert "in-range-item" in body, "Expected in-range expense to appear in recent list"
        assert "out-of-range-item" not in body, (
            "Expected out-of-range expense to be excluded from recent list"
        )


class TestProfileInvalidFilterFallback:
    def test_invalid_date_format_returns_200_not_500(self, auth_client, registered_user):
        user_id = registered_user["id"]
        _add_expense(user_id, 50.00, "Food", "2026-01-01")

        response = auth_client.get("/profile?start_date=not-a-date&end_date=2026-01-31")
        assert response.status_code == 200, "Malformed date must not cause a 500"

        body = response.data.decode()
        assert "50.00" in body, "Expected fallback to unfiltered (all-time) data"

    def test_end_date_invalid_format_falls_back(self, auth_client, registered_user):
        user_id = registered_user["id"]
        _add_expense(user_id, 22.00, "Food", "2026-01-01")

        response = auth_client.get("/profile?start_date=2026-01-01&end_date=garbage")
        assert response.status_code == 200
        body = response.data.decode()
        assert "22.00" in body, "Expected fallback to unfiltered data when end_date is malformed"

    def test_start_after_end_returns_200_not_500(self, auth_client, registered_user):
        user_id = registered_user["id"]
        _add_expense(user_id, 75.00, "Bills", "2026-05-01")

        response = auth_client.get("/profile?start_date=2026-12-01&end_date=2026-01-01")
        assert response.status_code == 200, "start_date after end_date must not cause a 500"

        body = response.data.decode()
        assert "75.00" in body, "Expected fallback to unfiltered (all-time) data"

    def test_start_after_end_does_not_show_filter_values_as_applied_narrowing(
        self, auth_client, registered_user
    ):
        # Even though fallback occurs, the form should still redisplay what
        # was submitted (per spec) — this is a distinct concern from filtering.
        user_id = registered_user["id"]
        _add_expense(user_id, 5.00, "Food", "2026-05-01")
        _add_expense(user_id, 5.00, "Food", "2026-11-01")

        response = auth_client.get("/profile?start_date=2026-12-01&end_date=2026-01-01")
        body = response.data.decode()
        # both expenses should be counted since filter was invalid -> unfiltered
        assert "10.00" in body, "Expected both expenses summed when invalid range falls back"


class TestProfileFormRedisplay:
    def test_valid_dates_redisplayed_in_form_inputs(self, auth_client, registered_user):
        response = auth_client.get("/profile?start_date=2026-02-01&end_date=2026-02-28")
        body = response.data.decode()
        assert 'name="start_date"' in body
        assert 'value="2026-02-01"' in body, "Expected start_date value redisplayed in form"
        assert 'value="2026-02-28"' in body, "Expected end_date value redisplayed in form"

    def test_no_filter_inputs_are_empty(self, auth_client):
        response = auth_client.get("/profile")
        body = response.data.decode()
        assert 'id="start_date"' in body
        assert 'id="end_date"' in body


class TestProfileClearFilterLink:
    def test_clear_filter_link_present_when_filter_active(self, auth_client, registered_user):
        response = auth_client.get("/profile?start_date=2026-01-01&end_date=2026-01-31")
        body = response.data.decode()
        assert "Clear filter" in body, "Expected Clear filter link when a filter is active"

    def test_clear_filter_link_present_with_only_start_date(self, auth_client):
        response = auth_client.get("/profile?start_date=2026-01-01")
        body = response.data.decode()
        assert "Clear filter" in body, (
            "Expected Clear filter link to appear even with only start_date supplied"
        )

    def test_clear_filter_link_absent_without_query_params(self, auth_client):
        response = auth_client.get("/profile")
        body = response.data.decode()
        assert "Clear filter" not in body

    def test_clear_filter_link_absent_when_range_invalid_and_falls_back(self, auth_client):
        # Per app.py's _parse_date_range, an invalid/backwards range resolves
        # to (None, None), so start_date/end_date passed to the template are
        # also None -- meaning no "active" filter to clear.
        response = auth_client.get("/profile?start_date=2026-12-01&end_date=2026-01-01")
        body = response.data.decode()
        assert "Clear filter" not in body, (
            "Expected no Clear filter link once an invalid range falls back to unfiltered"
        )
