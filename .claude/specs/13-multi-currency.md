# Spec: Multi Currency

## Overview
Today every expense is implicitly recorded and displayed in a single hardcoded currency (₹, INR — hardcoded directly into templates). This feature lets each user record expenses in whatever currency they were actually spent in, set a preferred display currency on their profile, and see every aggregate view (profile summary, category breakdown, analytics comparison, search results) converted into that preferred currency using a fixed, admin-seeded exchange-rate table stored in SQLite. There is no live FX API call and no new pip package — rates are static values seeded at `init_db()` time, viewable on a new read-only page so users understand how conversions were computed.

## Depends on
- Step 01 (database setup) — `get_db()`, `init_db()` conventions.
- Step 04/05 (profile page + backend routes) — `/profile`, `profile_edit`.
- Step 07 (add expense) — `/expenses/add`.
- Step 08 (edit expense) — `/expenses/<id>/edit`.
- Step 10 (recurring expenses) — `/expenses/recurring`, `sync_due_recurring_expenses`.
- Step 11 (expense search) — `/expenses/search`.
- Step 12 (dashboard comparison) — `/analytics`.

## Routes
- `GET /expenses/add` — modified — add a `currency` select, defaulting to the logged-in user's `preferred_currency` — logged-in.
- `POST /expenses/add` — modified — validate and persist `currency` on the new expense — logged-in.
- `GET /expenses/<id>/edit` — modified — pre-fill the `currency` select from the existing expense — logged-in.
- `POST /expenses/<id>/edit` — modified — validate and persist an updated `currency` — logged-in.
- `POST /expenses/recurring/add` — modified — add a `currency` field, carried onto every expense the template later generates — logged-in.
- `GET /profile/edit` — modified — add a `preferred_currency` select so a user can change their display currency — logged-in.
- `POST /profile/edit` — modified — validate and persist `preferred_currency` — logged-in.
- `GET /profile` — modified — convert summary total, category breakdown, and recent-expenses amounts into `preferred_currency`; each expense row also shows its original currency/amount — logged-in.
- `GET /analytics` — modified — convert both months' totals and per-category comparison into `preferred_currency` before computing percent-change — logged-in.
- `GET /expenses/search` — modified — convert result amounts into `preferred_currency` for display; filtering by `min_amount`/`max_amount` still compares against each expense's own original-currency amount (documented trade-off, see Rules) — logged-in.
- `GET /exchange-rates` — new — read-only page listing every supported currency and its static rate to the base currency (INR) — logged-in.

## Database changes
- `users`: add column `preferred_currency TEXT NOT NULL DEFAULT 'INR'`.
- `expenses`: add column `currency TEXT NOT NULL DEFAULT 'INR'`.
- `recurring_expenses`: add column `currency TEXT NOT NULL DEFAULT 'INR'` — copied onto every `expenses` row `sync_due_recurring_expenses()` generates from that template.
- New table `exchange_rates`:
  ```sql
  CREATE TABLE IF NOT EXISTS exchange_rates (
      currency TEXT PRIMARY KEY,
      rate_to_inr REAL NOT NULL
  )
  ```
  Seeded once (only if empty, same guard style as `seed_db()`) with a fixed, illustrative rate-to-INR for each supported currency: `INR=1.0, USD, EUR, GBP, JPY, AUD`. These are static/manually-maintained values, not live market rates — call this out in the `/exchange-rates` page copy so it isn't mistaken for real-time data.
- `CURRENCIES` constant (list of currency codes, same pattern as the existing `CATEGORIES` list) added to `database/db.py` for validating the `currency`/`preferred_currency` form fields against an allow-list.
- **Migration note:** `expense_tracker.db` already exists on disk from prior steps with the old `users`/`expenses`/`recurring_expenses` schemas (no currency columns). `init_db()`'s existing `CREATE TABLE IF NOT EXISTS` statements are no-ops against that file, so the three `ALTER TABLE ... ADD COLUMN ...` statements above must run unconditionally inside `init_db()`, each guarded with `try/except sqlite3.OperationalError: pass` (SQLite has no `ADD COLUMN IF NOT EXISTS`) so re-running `init_db()` on an already-migrated DB, or a fresh DB where the column already exists in `CREATE TABLE`, doesn't crash.

## Templates
- **Create:** `templates/exchange_rates.html` — table of currency code, symbol, and rate-to-INR; extends `base.html`.
- **Modify:**
  - `templates/expenses_add.html` — add currency `<select>` next to the amount field.
  - `templates/expenses_edit.html` — same, pre-filled from the expense being edited.
  - `templates/expenses_recurring.html` — add currency `<select>` to the create-template form; show each template's currency in its list row.
  - `templates/profile_edit.html` — add `preferred_currency` `<select>`.
  - `templates/profile.html` — replace hardcoded `₹` with the user's `preferred_currency` symbol on summary/category-breakdown amounts; recent-expenses rows show converted amount plus original (e.g. `₹500.00 (originally $6.00)`) when the expense's currency differs from `preferred_currency`.
  - `templates/analytics.html` — replace hardcoded `₹` with `preferred_currency` symbol on all amounts.
  - `templates/expenses_search.html` — replace hardcoded `₹` with `preferred_currency` symbol; result rows show original currency the same way as `profile.html`.
  - `templates/base.html` — add nav link to `/exchange-rates` (same `nav-link`/`active` pattern as Recurring/Search/Analytics).

## Files to change
- `app.py` — `add_expense`, `edit_expense`, `add_recurring_expense`, `profile_edit`, `profile`, `analytics`, `expenses_search` route bodies; add `exchange_rates` route; add a shared `_convert_amount(amount, from_currency, to_currency)` / currency-symbol helper.
- `database/db.py` — `init_db()` migration ALTERs, `CURRENCIES` constant, `exchange_rates` seed logic, `create_expense`/`update_expense`/`create_recurring_expense`/`update_user` signatures extended with the new currency field(s), new `get_exchange_rates()` helper.
- `templates/base.html` — nav link.
- `CLAUDE.md` — mark `GET /exchange-rates` and this step as implemented once done.

## Files to create
- `templates/exchange_rates.html`
- `.claude/specs/13-multi-currency.md` (this file)

## New dependencies
No new dependencies. Exchange rates are static values seeded into SQLite — no live FX API, so no HTTP client package (e.g. `requests`) is added in this step.

## Rules for implementation
- No SQLAlchemy or ORMs.
- Parameterised queries only — never f-string a value into SQL (the existing `f"""...{where_clause}..."""` pattern is fine since `where_clause` is built only from static fragments; the same rule applies to any new query here).
- Passwords hashed with werkzeug (unaffected by this feature, called out per project convention).
- Use CSS variables — never hardcode hex values — for any new template styling.
- All templates extend `base.html`.
- `currency` and `preferred_currency` form values are validated against the `CURRENCIES` allow-list exactly like `category` is validated against `CATEGORIES` — invalid/tampered values re-render the form with an error, no DB write.
- Conversion is one-hop through the base currency: `amount_in_target = amount * rate(from→INR) / rate(target→INR)`. Do this conversion math in `app.py`/a shared helper, not by embedding arithmetic in Jinja templates.
- `/expenses/search`'s `min_amount`/`max_amount` bounds compare against each expense's own stored (original-currency) amount, not a converted amount — documented explicitly in the page copy so it isn't a silent surprise (a true cross-currency amount filter is out of scope for this step).
- Existing rows created before this migration default to `currency = 'INR'` via the `ADD COLUMN ... DEFAULT 'INR'` clause — no backfill script needed.

## Definition of done
- [ ] Adding an expense lets you pick a currency; the saved row's `currency` column matches the selection.
- [ ] Editing an expense lets you change its currency; the update persists.
- [ ] Creating a recurring template lets you pick a currency; every expense the template later generates via `sync_due_recurring_expenses()` carries that same currency.
- [ ] `/profile/edit` lets you change `preferred_currency`; the change persists and is reflected immediately on `/profile`.
- [ ] `/profile`'s summary total, category breakdown, and recent-expenses amounts are shown converted into `preferred_currency`, with the correct currency symbol (not a hardcoded ₹).
- [ ] A recent-expense row whose original currency differs from `preferred_currency` shows both the converted amount and the original amount/currency.
- [ ] `/analytics`'s current/previous totals, percent-change, and per-category comparison are computed on amounts converted into `preferred_currency`.
- [ ] `/expenses/search` results display converted amounts, and `min_amount`/`max_amount` filtering still works against original-currency amounts.
- [ ] `/exchange-rates` renders a table of every `CURRENCIES` entry with its rate to INR, reachable from the nav, and requires login.
- [ ] Submitting an invalid/tampered `currency` value on any form (add/edit expense, recurring, profile) re-renders the form with an error and does not write to the DB.
- [ ] Running `pytest` after this step passes with no regressions in existing test files.
- [ ] Cross-user isolation still holds: a user cannot view or edit another user's expenses regardless of currency.
