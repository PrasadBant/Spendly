"""
Tests for Step 13: Multi Currency.

Spec: .claude/specs/13-multi-currency.md

These tests validate behavior only (routes, form validation, DB writes,
currency-aware conversion of displayed amounts, the documented
original-currency search-filter trade-off, and cross-user isolation) — not
implementation details of app.py/database/db.py. Fixtures (`app`, `client`,
`registered_user`, `auth_client`) come from tests/conftest.py.
`second_user`/`second_auth_client` are defined locally, mirroring the
pattern in tests/test_07-add-expense.py, tests/test_10-recurring-expenses.py
and tests/test_12-dashboard-comparison.py, for cross-user isolation checks.

Generic auth-guard coverage for /expenses/add, /expenses/<id>/edit,
/expenses/recurring/add, and /expenses/search already exists in
test_07/test_08/test_10/test_11 — this file only adds an auth guard for the
two routes with no prior coverage (/exchange-rates, /profile/edit) and
otherwise focuses on the currency-specific behavior those routes gained in
this step.

Exchange rates are seeded once at app-import time via
`with app.app_context(): init_db(); seed_db(); seed_exchange_rates()` in
app.py, but that runs against the *real* DB_PATH before conftest's `app`
fixture monkeypatches it to an isolated per-test file. conftest's `app`
fixture intentionally only calls `init_db()` (not `seed_db()`/
`seed_exchange_rates()`), so a local autouse fixture below seeds the
`exchange_rates` table for every test in this file — without it, every
converted-amount assertion would silently fall back to a 1:1 rate.

Conversion expectations are computed with the spec's own documented
formula (`amount * rate(from->INR) / rate(target->INR)`) using rates
fetched at test time via the public `get_exchange_rates()` helper — never
hardcoded rate numbers — so these tests stay valid regardless of the
specific illustrative rate values seeded.
"""

import re
from datetime import date, timedelta

import pytest

import database.db as db


# ------------------------------------------------------------------ #
# Local fixtures                                                      #
# ------------------------------------------------------------------ #

@pytest.fixture(autouse=True)
def _seeded_exchange_rates(app):
    """Ensures the exchange_rates table is populated for every test in this
    file (see module docstring for why conftest's `app` fixture alone isn't
    enough)."""
    with app.app_context():
        db.seed_exchange_rates()


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

def _insert_expense(user_id, amount, category, expense_date, description="", currency="INR"):
    """Insert an expense directly via a parameterized query (test helper only)."""
    conn = db.get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description, currency) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, amount, category, expense_date, description, currency),
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


def _count_all_expenses():
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()["n"]
    finally:
        conn.close()


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


def _rates_map():
    """{currency_code: rate_to_inr} fetched live via the spec-mandated
    get_exchange_rates() helper — never a hardcoded literal."""
    return {row["currency"]: row["rate_to_inr"] for row in db.get_exchange_rates()}


def _expected_conversion(amount, from_currency, to_currency, rates):
    """Implements the spec's documented one-hop-through-INR conversion
    formula (Rules for implementation): amount_in_target =
    amount * rate(from->INR) / rate(target->INR)."""
    if from_currency == to_currency:
        return amount
    return amount * rates[from_currency] / rates[to_currency]


def _fmt(amount):
    """App-wide currency amount format (comma thousands separator, 2
    decimals) as already asserted against in test_12-dashboard-comparison.py."""
    return "{:,.2f}".format(amount)


def _selected_option_value(body, select_name):
    """Extracts the currently-selected <option>'s value from the named
    <select> block, tolerant of exact attribute ordering (mirrors the
    'active' nav-class regex technique already used in
    test_12-dashboard-comparison.py). Returns None if nothing is selected."""
    select_match = re.search(
        rf'<select[^>]*name="{select_name}".*?</select>', body, re.DOTALL
    )
    assert select_match, f'Expected a <select name="{select_name}"> on the page'
    select_html = select_match.group(0)
    option_match = re.search(r'<option\s+value="([^"]*)"[^>]*\bselected\b', select_html)
    return option_match.group(1) if option_match else None


# ------------------------------------------------------------------ #
# Date helpers                                                        #
# ------------------------------------------------------------------ #

def _date_str(d):
    return d.strftime("%Y-%m-%d")


def _today_str():
    return _date_str(date.today())


def _last_day_of_previous_month_str():
    first_of_this_month = date.today().replace(day=1)
    return _date_str(first_of_this_month - timedelta(days=1))


# ------------------------------------------------------------------ #
# Shared payloads                                                     #
# ------------------------------------------------------------------ #

VALID_EXPENSE_PAYLOAD = {
    "amount": "42.50",
    "category": "Food",
    "currency": "INR",
    "date": "2026-03-15",
    "description": "Currency test expense",
}

VALID_RECURRING_PAYLOAD = {
    "amount": "1200",
    "category": "Bills",
    "currency": "INR",
    "interval": "monthly",
    "start_date": "2026-01-01",
    "description": "Currency test rent",
}


def _profile_edit_payload(registered_user, preferred_currency, name="Test User"):
    return {
        "name": name,
        "email": registered_user["email"],
        "preferred_currency": preferred_currency,
    }


# ------------------------------------------------------------------ #
# Database defaults for pre-existing rows (spec: Database changes)    #
# ------------------------------------------------------------------ #

class TestSchemaDefaults:
    """New columns default to 'INR' (spec: 'users: add column
    preferred_currency TEXT NOT NULL DEFAULT 'INR''; same for
    expenses.currency / recurring_expenses.currency)."""

    def test_new_user_defaults_to_inr_preferred_currency(self, registered_user):
        user = db.get_user_by_id(registered_user["id"])
        assert user["preferred_currency"] == "INR", (
            "Expected a newly registered user's preferred_currency to default to 'INR'"
        )

    def test_expense_inserted_without_currency_defaults_to_inr(self, registered_user):
        conn = db.get_db()
        try:
            cursor = conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (registered_user["id"], 10.0, "Food", "2026-01-01", "No currency given"),
            )
            conn.commit()
            expense_id = cursor.lastrowid
        finally:
            conn.close()

        row = db.get_expense_by_id(expense_id)
        assert row["currency"] == "INR", (
            "Expected an expense row inserted without an explicit currency to "
            "default to 'INR'"
        )


# ------------------------------------------------------------------ #
# /exchange-rates                                                     #
# ------------------------------------------------------------------ #

class TestExchangeRatesAuthGuard:
    """GET /exchange-rates redirects anonymous users to /login (spec:
    Routes -> 'logged-in')."""

    def test_get_requires_login(self, client):
        resp = client.get("/exchange-rates")
        assert resp.status_code == 302, "Expected redirect for unauthenticated GET"
        assert "/login" in resp.headers.get("Location", ""), (
            "Expected unauthenticated GET /exchange-rates to redirect to /login"
        )


class TestExchangeRatesPage:
    """/exchange-rates renders a table of every CURRENCIES entry with its
    rate to INR (spec Definition of Done)."""

    def test_get_returns_200(self, auth_client):
        resp = auth_client.get("/exchange-rates")
        assert resp.status_code == 200, "Expected 200 for logged-in GET /exchange-rates"

    def test_lists_every_supported_currency(self, auth_client):
        resp = auth_client.get("/exchange-rates")
        body = resp.data.decode()
        for currency in db.CURRENCIES:
            assert currency in body, (
                f"Expected supported currency '{currency}' to be listed on /exchange-rates"
            )

    def test_lists_each_currencys_rate_to_inr(self, auth_client):
        resp = auth_client.get("/exchange-rates")
        body = resp.data.decode()
        rates = _rates_map()
        assert rates, "Setup sanity check: expected exchange_rates to be seeded"
        for currency, rate in rates.items():
            candidates = [
                f"{rate:.2f}", f"{rate:.4f}", f"{rate:.1f}", str(int(rate))
                if float(rate).is_integer() else f"{rate:g}",
            ]
            assert any(c in body for c in candidates), (
                f"Expected some numeric rendering of {currency}'s rate ({rate}) "
                f"to appear on /exchange-rates"
            )

    def test_inr_rate_is_one(self, auth_client):
        rates = _rates_map()
        assert rates.get("INR") == pytest.approx(1.0), (
            "Expected INR to be the base currency with rate_to_inr == 1.0"
        )


class TestExchangeRatesNavLink:
    """/exchange-rates is reachable from the nav (spec Templates:
    'base.html — add nav link to /exchange-rates')."""

    def test_nav_link_present_on_other_pages(self, app, auth_client):
        with app.app_context():
            from flask import url_for
            rates_url = url_for("exchange_rates")

        resp = auth_client.get("/profile")
        body = resp.data.decode()
        assert rates_url in body, "Expected a nav link to /exchange-rates on /profile"

    def test_nav_link_active_on_exchange_rates_page(self, app, auth_client):
        with app.app_context():
            from flask import url_for
            rates_url = url_for("exchange_rates")

        resp = auth_client.get(rates_url)
        body = resp.data.decode()
        match = re.search(r'<a[^>]*href="' + re.escape(rates_url) + r'"[^>]*>', body)
        assert match is not None, "Expected an anchor tag linking to /exchange-rates in the nav"
        assert "active" in match.group(0), (
            "Expected the Rates nav link to carry the 'active' class while on /exchange-rates"
        )


# ------------------------------------------------------------------ #
# GET/POST /expenses/add — currency field                             #
# ------------------------------------------------------------------ #

class TestAddExpenseCurrencyForm:
    """GET /expenses/add includes a currency select defaulting to the
    logged-in user's preferred_currency (spec: Routes)."""

    def test_get_shows_currency_field(self, auth_client):
        resp = auth_client.get("/expenses/add")
        body = resp.data.decode()
        assert 'name="currency"' in body, "Expected a currency select field"

    def test_get_lists_all_currencies(self, auth_client):
        resp = auth_client.get("/expenses/add")
        body = resp.data.decode()
        for currency in db.CURRENCIES:
            assert currency in body, f"Expected currency '{currency}' to appear in the form"

    def test_get_default_currency_is_inr_for_new_user(self, auth_client):
        resp = auth_client.get("/expenses/add")
        body = resp.data.decode()
        assert _selected_option_value(body, "currency") == "INR", (
            "Expected the currency select to default to the user's preferred_currency "
            "(INR for a newly registered user)"
        )

    def test_get_default_currency_follows_updated_preferred_currency(
        self, auth_client, registered_user
    ):
        auth_client.post(
            "/profile/edit", data=_profile_edit_payload(registered_user, "EUR")
        )
        resp = auth_client.get("/expenses/add")
        body = resp.data.decode()
        assert _selected_option_value(body, "currency") == "EUR", (
            "Expected the add-expense currency select to default to the user's "
            "newly updated preferred_currency (EUR)"
        )


class TestAddExpenseCurrencyHappyPath:
    """A valid POST persists the selected currency on the new expense row
    (spec Definition of Done: 'the saved row's currency column matches the
    selection')."""

    @pytest.mark.parametrize("currency", db.CURRENCIES)
    def test_valid_currency_persists(self, auth_client, registered_user, currency):
        payload = {**VALID_EXPENSE_PAYLOAD, "currency": currency}
        resp = auth_client.post("/expenses/add", data=payload)
        assert resp.status_code == 302, f"Expected successful redirect for currency={currency}"

        rows = _all_expenses_for(registered_user["id"])
        assert len(rows) == 1
        assert rows[0]["currency"] == currency


class TestAddExpenseCurrencyValidation:
    """An invalid/tampered currency value re-renders the form with an error
    and inserts no row (spec Rules for implementation + Definition of
    Done)."""

    @pytest.mark.parametrize(
        "bad_currency",
        ["", "XXX", "inr", "usd", "NotACurrency", "INR; DROP TABLE expenses;--"],
    )
    def test_invalid_currency_rejected(self, auth_client, registered_user, bad_currency):
        before = _count_all_expenses()
        payload = {**VALID_EXPENSE_PAYLOAD, "currency": bad_currency}
        resp = auth_client.post("/expenses/add", data=payload)
        assert resp.status_code == 200, (
            "Expected the form to be re-rendered (200) on invalid currency, not a redirect"
        )
        body = resp.data.decode()
        assert "error" in body.lower(), "Expected an error message for an invalid currency"

        after = _count_all_expenses()
        assert after == before, "Invalid currency must not insert an expense row"
        assert len(_all_expenses_for(registered_user["id"])) == 0


# ------------------------------------------------------------------ #
# GET/POST /expenses/<id>/edit — currency field                       #
# ------------------------------------------------------------------ #

class TestEditExpenseCurrencyForm:
    """GET /expenses/<id>/edit pre-fills the currency select from the
    existing expense (spec: Routes)."""

    def test_get_prefills_existing_currency(self, auth_client, registered_user):
        expense_id = _insert_expense(
            registered_user["id"], 20.0, "Food", "2026-01-01", "Sushi", currency="JPY"
        )
        resp = auth_client.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert _selected_option_value(body, "currency") == "JPY", (
            "Expected the edit form's currency select to be pre-filled from the "
            "expense being edited"
        )


class TestEditExpenseCurrencyHappyPath:
    """Editing an expense's currency persists the change (spec Definition
    of Done)."""

    def test_changing_currency_persists(self, auth_client, registered_user):
        expense_id = _insert_expense(
            registered_user["id"], 20.0, "Food", "2026-01-01", "Sushi", currency="INR"
        )
        payload = {
            "amount": "20.00", "category": "Food", "currency": "JPY",
            "date": "2026-01-01", "description": "Sushi",
        }
        resp = auth_client.post(f"/expenses/{expense_id}/edit", data=payload)
        assert resp.status_code == 302, "Expected redirect on successful currency update"

        row = db.get_expense_by_id(expense_id)
        assert row["currency"] == "JPY", "Expected the updated currency to persist"

    def test_currency_can_be_changed_again(self, auth_client, registered_user):
        expense_id = _insert_expense(
            registered_user["id"], 20.0, "Food", "2026-01-01", "Sushi", currency="JPY"
        )
        payload = {
            "amount": "20.00", "category": "Food", "currency": "GBP",
            "date": "2026-01-01", "description": "Sushi",
        }
        auth_client.post(f"/expenses/{expense_id}/edit", data=payload)
        row = db.get_expense_by_id(expense_id)
        assert row["currency"] == "GBP"


class TestEditExpenseCurrencyValidation:
    """An invalid/tampered currency on edit re-renders the form with an
    error and does not update the row (spec Definition of Done)."""

    @pytest.mark.parametrize("bad_currency", ["", "XXX", "jpy", "NotACurrency"])
    def test_invalid_currency_rejected_and_row_unchanged(
        self, auth_client, registered_user, bad_currency
    ):
        expense_id = _insert_expense(
            registered_user["id"], 20.0, "Food", "2026-01-01", "Sushi", currency="INR"
        )
        payload = {
            "amount": "20.00", "category": "Food", "currency": bad_currency,
            "date": "2026-01-01", "description": "Sushi",
        }
        resp = auth_client.post(f"/expenses/{expense_id}/edit", data=payload)
        assert resp.status_code == 200, (
            "Expected the form to be re-rendered (200) on invalid currency, not a redirect"
        )
        body = resp.data.decode()
        assert "error" in body.lower(), "Expected an error message for an invalid currency"

        row = db.get_expense_by_id(expense_id)
        assert row["currency"] == "INR", (
            "Invalid currency submission must not change the stored currency"
        )


# ------------------------------------------------------------------ #
# POST /expenses/recurring/add — currency field                       #
# ------------------------------------------------------------------ #

class TestRecurringCurrencyForm:
    def test_list_page_shows_currency_field(self, auth_client):
        resp = auth_client.get("/expenses/recurring")
        body = resp.data.decode()
        assert 'name="currency"' in body, "Expected a currency select on the create-template form"

    def test_list_page_lists_all_currencies(self, auth_client):
        resp = auth_client.get("/expenses/recurring")
        body = resp.data.decode()
        for currency in db.CURRENCIES:
            assert currency in body, f"Expected currency '{currency}' to appear in the form"

    def test_created_templates_currency_shown_in_list_row(self, auth_client):
        payload = {**VALID_RECURRING_PAYLOAD, "currency": "GBP"}
        auth_client.post("/expenses/recurring/add", data=payload)
        resp = auth_client.get("/expenses/recurring")
        body = resp.data.decode()
        assert "GBP" in body, "Expected the created template's currency to appear in its list row"


class TestRecurringCurrencyHappyPath:
    """A valid POST persists the selected currency on the recurring
    template row (spec Definition of Done)."""

    @pytest.mark.parametrize("currency", db.CURRENCIES)
    def test_valid_currency_persists_on_template(self, auth_client, registered_user, currency):
        payload = {**VALID_RECURRING_PAYLOAD, "currency": currency}
        resp = auth_client.post("/expenses/recurring/add", data=payload)
        assert resp.status_code == 302

        rows = _all_recurring_for(registered_user["id"])
        assert len(rows) == 1
        assert rows[0]["currency"] == currency


class TestRecurringCurrencyValidation:
    @pytest.mark.parametrize("bad_currency", ["", "XXX", "gbp", "NotACurrency"])
    def test_invalid_currency_rejected(self, auth_client, registered_user, bad_currency):
        before = _count_all_recurring()
        payload = {**VALID_RECURRING_PAYLOAD, "currency": bad_currency}
        resp = auth_client.post("/expenses/recurring/add", data=payload)
        assert resp.status_code == 200, (
            "Expected the form to be re-rendered (200) on invalid currency, not a redirect"
        )
        body = resp.data.decode()
        assert "error" in body.lower(), "Expected an error message for an invalid currency"

        after = _count_all_recurring()
        assert after == before, "Invalid currency must not insert a recurring_expenses row"
        assert len(_all_recurring_for(registered_user["id"])) == 0


class TestRecurringGeneratedExpensesCarryCurrency:
    """Every expense a recurring template later generates via
    sync_due_recurring_expenses() carries the template's currency (spec
    Definition of Done)."""

    def test_generated_occurrence_carries_templates_currency(self, auth_client, registered_user):
        payload = {
            "amount": "500", "category": "Bills", "currency": "AUD",
            "interval": "monthly", "start_date": _today_str(),
            "description": "AUD subscription",
        }
        auth_client.post("/expenses/recurring/add", data=payload)

        auth_client.get("/profile")  # triggers sync_due_recurring_expenses

        rows = [
            r for r in _all_expenses_for(registered_user["id"])
            if r["description"] == "AUD subscription"
        ]
        assert len(rows) == 1, "Expected exactly one generated occurrence"
        assert rows[0]["currency"] == "AUD", (
            "Expected the generated expense to carry the recurring template's currency"
        )

    def test_multiple_backfilled_occurrences_all_carry_currency(self, auth_client, registered_user):
        start = date.today() - timedelta(weeks=3)
        payload = {
            "amount": "20", "category": "Food", "currency": "EUR",
            "interval": "weekly", "start_date": _date_str(start),
            "description": "EUR weekly coffee",
        }
        auth_client.post("/expenses/recurring/add", data=payload)
        auth_client.get("/profile")

        rows = [
            r for r in _all_expenses_for(registered_user["id"])
            if r["description"] == "EUR weekly coffee"
        ]
        assert len(rows) >= 2, "Setup sanity check: expected multiple backfilled occurrences"
        for row in rows:
            assert row["currency"] == "EUR", (
                "Expected every backfilled occurrence to carry the template's currency"
            )


# ------------------------------------------------------------------ #
# /profile/edit — preferred_currency                                  #
# ------------------------------------------------------------------ #

class TestProfileEditAuthGuard:
    def test_get_requires_login(self, client):
        resp = client.get("/profile/edit")
        assert resp.status_code == 302
        assert "/login" in resp.headers.get("Location", "")

    def test_post_requires_login(self, client, registered_user):
        resp = client.post(
            "/profile/edit", data=_profile_edit_payload(registered_user, "USD")
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers.get("Location", "")

        user = db.get_user_by_id(registered_user["id"])
        assert user["preferred_currency"] == "INR", (
            "Unauthenticated POST must not change preferred_currency"
        )


class TestProfileEditPreferredCurrencyForm:
    def test_get_shows_preferred_currency_field(self, auth_client):
        resp = auth_client.get("/profile/edit")
        body = resp.data.decode()
        assert 'name="preferred_currency"' in body, (
            "Expected a preferred_currency select on the profile-edit form"
        )

    def test_get_lists_all_currencies(self, auth_client):
        resp = auth_client.get("/profile/edit")
        body = resp.data.decode()
        for currency in db.CURRENCIES:
            assert currency in body, f"Expected currency '{currency}' to appear in the form"

    def test_get_preselects_current_preferred_currency(self, auth_client, registered_user):
        auth_client.post(
            "/profile/edit", data=_profile_edit_payload(registered_user, "GBP")
        )
        resp = auth_client.get("/profile/edit")
        body = resp.data.decode()
        assert _selected_option_value(body, "preferred_currency") == "GBP", (
            "Expected the preferred_currency select to be pre-filled with the "
            "user's current preference"
        )


class TestProfileEditPreferredCurrencyHappyPath:
    """Changing preferred_currency persists and is reflected immediately on
    /profile (spec Definition of Done)."""

    @pytest.mark.parametrize("currency", db.CURRENCIES)
    def test_valid_preferred_currency_persists(self, auth_client, registered_user, currency):
        resp = auth_client.post(
            "/profile/edit", data=_profile_edit_payload(registered_user, currency)
        )
        assert resp.status_code == 302, f"Expected redirect for preferred_currency={currency}"

        user = db.get_user_by_id(registered_user["id"])
        assert user["preferred_currency"] == currency

    def test_change_reflected_immediately_on_profile(self, auth_client, registered_user):
        _insert_expense(
            registered_user["id"], 100.0, "Food", _today_str(), "Groceries", currency="INR"
        )
        rates = _rates_map()

        auth_client.post(
            "/profile/edit", data=_profile_edit_payload(registered_user, "USD")
        )
        resp = auth_client.get("/profile")
        body = resp.data.decode()

        expected_symbol = db.CURRENCY_SYMBOLS["USD"]
        assert expected_symbol in body, (
            "Expected /profile to immediately reflect the new preferred_currency's symbol"
        )
        expected_total = _expected_conversion(100.0, "INR", "USD", rates)
        assert _fmt(expected_total) in body, (
            "Expected /profile's summary total to be converted into the newly "
            "chosen preferred_currency"
        )


class TestProfileEditPreferredCurrencyValidation:
    """An invalid/tampered preferred_currency re-renders the form with an
    error and does not persist (spec Definition of Done)."""

    @pytest.mark.parametrize(
        "bad_currency", ["", "XXX", "usd", "NotACurrency", "INR<script>"]
    )
    def test_invalid_preferred_currency_rejected(self, auth_client, registered_user, bad_currency):
        resp = auth_client.post(
            "/profile/edit", data=_profile_edit_payload(registered_user, bad_currency)
        )
        assert resp.status_code == 200, (
            "Expected the form to be re-rendered (200) on invalid preferred_currency, "
            "not a redirect"
        )
        body = resp.data.decode()
        assert "error" in body.lower(), (
            "Expected an error message for an invalid preferred_currency"
        )

        user = db.get_user_by_id(registered_user["id"])
        assert user["preferred_currency"] == "INR", (
            "Invalid preferred_currency submission must not change the stored value"
        )


# ------------------------------------------------------------------ #
# /profile — converted display                                        #
# ------------------------------------------------------------------ #

class TestProfileConvertedDisplay:
    """Summary total, category breakdown, and recent-expenses amounts are
    converted into preferred_currency, with the correct symbol (spec
    Definition of Done)."""

    def test_summary_total_is_converted(self, auth_client, registered_user):
        _insert_expense(
            registered_user["id"], 1000.0, "Food", _today_str(), "Groceries", currency="INR"
        )
        rates = _rates_map()
        auth_client.post("/profile/edit", data=_profile_edit_payload(registered_user, "USD"))

        resp = auth_client.get("/profile")
        body = resp.data.decode()

        expected_total = _expected_conversion(1000.0, "INR", "USD", rates)
        assert _fmt(expected_total) in body, (
            "Expected the summary total to show the amount converted into USD"
        )
        assert db.CURRENCY_SYMBOLS["USD"] in body

    def test_category_breakdown_is_converted(self, auth_client, registered_user):
        _insert_expense(
            registered_user["id"], 200.0, "Transport", _today_str(), "Taxi", currency="INR"
        )
        rates = _rates_map()
        auth_client.post("/profile/edit", data=_profile_edit_payload(registered_user, "EUR"))

        resp = auth_client.get("/profile")
        body = resp.data.decode()

        expected_total = _expected_conversion(200.0, "INR", "EUR", rates)
        assert _fmt(expected_total) in body, (
            "Expected the Transport category breakdown row to show the converted total"
        )

    def test_recent_expense_shows_converted_amount_and_original_when_currencies_differ(
        self, auth_client, registered_user
    ):
        _insert_expense(
            registered_user["id"], 6.0, "Food", _today_str(), "Imported snack", currency="USD"
        )
        rates = _rates_map()
        # preferred_currency stays the default 'INR' so USD != INR triggers show_original.

        resp = auth_client.get("/profile")
        body = resp.data.decode()

        expected_converted = _expected_conversion(6.0, "USD", "INR", rates)
        assert _fmt(expected_converted) in body, (
            "Expected the recent-expenses row to show the amount converted into INR"
        )
        assert "originally" in body.lower(), (
            "Expected a differing-currency expense row to show its original amount/currency"
        )
        assert db.CURRENCY_SYMBOLS["USD"] in body
        assert _fmt(6.0) in body, "Expected the original USD amount to also be shown"

    def test_recent_expense_does_not_show_original_when_currencies_match(
        self, auth_client, registered_user
    ):
        _insert_expense(
            registered_user["id"], 50.0, "Food", _today_str(), "Local lunch", currency="INR"
        )
        # preferred_currency stays default 'INR' — currency matches, no "originally" text.
        resp = auth_client.get("/profile")
        body = resp.data.decode()
        assert "originally" not in body.lower(), (
            "Expected no 'originally ...' annotation when the expense's currency "
            "already matches preferred_currency"
        )

    def test_no_hardcoded_rupee_symbol_when_preferred_currency_is_not_inr(
        self, auth_client, registered_user
    ):
        _insert_expense(
            registered_user["id"], 40.0, "Food", _today_str(), "Burger", currency="USD"
        )
        auth_client.post("/profile/edit", data=_profile_edit_payload(registered_user, "USD"))

        resp = auth_client.get("/profile")
        body = resp.data.decode()
        assert "₹" not in body, (
            "Expected no hardcoded ₹ symbol once preferred_currency is USD and every "
            "expense is already in USD (no 'originally' annotations to legitimately "
            "contain a different symbol)"
        )
        assert db.CURRENCY_SYMBOLS["USD"] in body


# ------------------------------------------------------------------ #
# /analytics — converted totals and per-category comparison           #
# ------------------------------------------------------------------ #

class TestAnalyticsConvertedDisplay:
    """Current/previous totals, percent-change, and per-category comparison
    are computed on amounts converted into preferred_currency (spec
    Definition of Done)."""

    def test_totals_are_converted(self, auth_client, registered_user):
        _insert_expense(
            registered_user["id"], 300.0, "Food", _today_str(), "This month", currency="INR"
        )
        rates = _rates_map()
        auth_client.post("/profile/edit", data=_profile_edit_payload(registered_user, "USD"))

        resp = auth_client.get("/analytics")
        body = resp.data.decode()
        expected_total = _expected_conversion(300.0, "INR", "USD", rates)
        assert _fmt(expected_total) in body, (
            "Expected /analytics' current-month total to be converted into preferred_currency"
        )

    def test_percent_change_computed_on_converted_amounts(self, auth_client, registered_user):
        rates = _rates_map()
        # preferred_currency stays default 'INR'; mix currencies across the
        # two months so a naive raw-amount comparison would compute a
        # different (wrong) percentage than one computed on converted totals.
        _insert_expense(
            registered_user["id"], 100.0, "Food", _today_str(), "USD this month", currency="USD"
        )
        _insert_expense(
            registered_user["id"], 50.0, "Food", _last_day_of_previous_month_str(),
            "INR last month", currency="INR",
        )

        current_converted = _expected_conversion(100.0, "USD", "INR", rates)
        previous_converted = 50.0
        expected_pct = (current_converted - previous_converted) / previous_converted * 100

        resp = auth_client.get("/analytics")
        assert resp.status_code == 200
        body = resp.data.decode()

        percents = [float(m) for m in re.findall(r"(-?\d+(?:\.\d+)?)\s*%", body)]
        assert any(abs(p - expected_pct) < 1.0 for p in percents), (
            f"Expected a percent-change of ~{expected_pct:.1f}% computed on converted "
            f"totals; found percentages: {percents}"
        )

    def test_per_category_comparison_is_converted(self, auth_client, registered_user):
        _insert_expense(
            registered_user["id"], 500.0, "Shopping", _today_str(), "Gadget", currency="INR"
        )
        rates = _rates_map()
        auth_client.post("/profile/edit", data=_profile_edit_payload(registered_user, "EUR"))

        resp = auth_client.get("/analytics")
        body = resp.data.decode()
        expected_total = _expected_conversion(500.0, "INR", "EUR", rates)
        assert "Shopping" in body
        assert _fmt(expected_total) in body, (
            "Expected the Shopping category row to show the converted amount"
        )


# ------------------------------------------------------------------ #
# /expenses/search — converted display, original-amount filtering     #
# ------------------------------------------------------------------ #

class TestSearchConvertedDisplay:
    """Result amounts are converted into preferred_currency for display
    (spec Definition of Done)."""

    def test_result_amount_is_converted(self, auth_client, registered_user):
        _insert_expense(
            registered_user["id"], 50.0, "Food", "2026-01-01", "Cafe", currency="USD"
        )
        rates = _rates_map()
        # preferred_currency stays default 'INR'.

        resp = auth_client.get("/expenses/search?q=Cafe")
        body = resp.data.decode()

        expected_converted = _expected_conversion(50.0, "USD", "INR", rates)
        assert _fmt(expected_converted) in body, (
            "Expected the search result row to show the amount converted into "
            "preferred_currency"
        )


class TestSearchFilterUsesOriginalCurrencyAmount:
    """min_amount/max_amount compare against each expense's own
    original-currency amount, not a converted amount (spec Rules for
    implementation + Definition of Done)."""

    def test_expense_included_by_original_amount_despite_tiny_converted_amount(
        self, auth_client, registered_user
    ):
        rates = _rates_map()
        auth_client.post("/profile/edit", data=_profile_edit_payload(registered_user, "USD"))
        _insert_expense(
            registered_user["id"], 1000.0, "Food", "2026-01-01", "Big INR purchase", currency="INR"
        )
        converted = _expected_conversion(1000.0, "INR", "USD", rates)

        # Bounds that fit the *original* 1000 INR amount. Only meaningful as a
        # trade-off demonstration if the converted display amount falls
        # *outside* these bounds (otherwise both interpretations would agree) —
        # skip rather than assert something the current seed can't demonstrate.
        if 500.0 <= converted <= 1500.0:
            pytest.skip(
                "Converted USD amount happens to also fall within [500, 1500] in "
                "this seed; trade-off not distinctly observable with these bounds"
            )

        resp = auth_client.get("/expenses/search?min_amount=500&max_amount=1500")
        body = resp.data.decode()
        assert "Big INR purchase" in body, (
            "Expected min_amount/max_amount to match against the expense's own "
            "original-currency amount (1000), not its converted display amount "
            f"(~{converted:.2f}, outside [500, 1500])"
        )

    def test_expense_excluded_by_original_amount_despite_matching_converted_amount(
        self, auth_client, registered_user
    ):
        rates = _rates_map()
        auth_client.post("/profile/edit", data=_profile_edit_payload(registered_user, "USD"))
        _insert_expense(
            registered_user["id"], 1000.0, "Food", "2026-01-01", "Big INR purchase", currency="INR"
        )
        converted = _expected_conversion(1000.0, "INR", "USD", rates)

        if not (0 < converted < 1000.0):
            pytest.skip(
                "Converted USD amount isn't strictly between 0 and the original "
                "1000 INR in this seed; can't construct a bound that the converted "
                "amount satisfies but the original amount doesn't"
            )

        # A max_amount strictly between the converted amount and the original
        # amount: satisfied by the *converted* display amount, but not by the
        # original 1000 INR amount the filter is actually supposed to use.
        narrow_max = (converted + 1000.0) / 2

        resp = auth_client.get(f"/expenses/search?max_amount={narrow_max:.2f}")
        body = resp.data.decode()
        assert "Big INR purchase" not in body, (
            "Expected max_amount filtering to reject this expense based on its "
            "original 1000 INR amount, even though its converted display amount "
            f"(~{converted:.2f}) would satisfy a max_amount of {narrow_max:.2f}"
        )


# ------------------------------------------------------------------ #
# Cross-user isolation                                                #
# ------------------------------------------------------------------ #

class TestCrossUserIsolation:
    """A user cannot view or edit another user's expenses regardless of
    currency; one user's preferred_currency never affects another user's
    display (spec Definition of Done)."""

    def test_cannot_edit_other_users_expense_currency(
        self, auth_client, second_auth_client, second_user
    ):
        expense_id = _insert_expense(
            second_user["id"], 30.0, "Food", "2026-01-01", "Not yours", currency="INR"
        )
        payload = {
            "amount": "30.00", "category": "Food", "currency": "USD",
            "date": "2026-01-01", "description": "Not yours",
        }
        resp = auth_client.post(f"/expenses/{expense_id}/edit", data=payload)
        assert resp.status_code == 404, (
            "Expected 404 when attempting to edit another user's expense, "
            "regardless of currency changes attempted"
        )

        row = db.get_expense_by_id(expense_id)
        assert row["currency"] == "INR", (
            "Another user's expense currency must remain untouched by a non-owner's edit attempt"
        )

    def test_second_users_preferred_currency_does_not_affect_first_user(
        self, auth_client, registered_user, second_auth_client, second_user
    ):
        _insert_expense(
            registered_user["id"], 100.0, "Food", _today_str(), "User1 expense", currency="INR"
        )
        second_auth_client.post(
            "/profile/edit", data=_profile_edit_payload(second_user, "JPY", name="Second User")
        )

        resp = auth_client.get("/profile")
        body = resp.data.decode()
        assert _fmt(100.0) in body, (
            "Expected user1's own preferred_currency (INR, unchanged) to still govern "
            "their own /profile display"
        )
        assert db.CURRENCY_SYMBOLS["JPY"] not in body, (
            "A second user's preferred_currency change must not affect the first "
            "user's displayed currency symbol"
        )

    def test_second_users_expenses_do_not_appear_in_first_users_search(
        self, auth_client, registered_user, second_auth_client, second_user
    ):
        _insert_expense(
            second_user["id"], 999.0, "Food", "2026-01-01", "Second users food", currency="EUR"
        )
        resp = auth_client.get("/expenses/search?category=Food")
        body = resp.data.decode()
        assert "Second users food" not in body, (
            "A second user's expense must never leak into the first user's search "
            "results regardless of currency"
        )
