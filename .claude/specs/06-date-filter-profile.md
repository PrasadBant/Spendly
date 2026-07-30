# Spec: Date Filter For Profile Page

## Overview
Steps 4 and 5 turned `/profile` into a functional account hub showing the user's summary, category breakdown, and 6 most recent expenses — but always over the user's *entire* expense history. This step adds a date-range filter to `/profile` so the user can narrow the summary, category breakdown, and recent-expenses list to a specific window (e.g. this month, last 30 days, or a custom range), without leaving the page.

## Depends on
- Step 1 — Database Setup (`expenses` table, `get_db()`)
- Step 4 — Profile Page (`GET /profile`, `profile.html`, `get_user_expense_summary`, `get_category_breakdown`, `get_user_expenses`)
- Step 5 — Backend Routes For Profile Page (existing profile route structure and helper patterns)

## Routes
- `GET /profile` — extended to accept optional `start_date` and `end_date` query parameters (`YYYY-MM-DD`); when present, filters summary, category breakdown, and recent expenses to that range; when absent, behaves exactly as before (all-time) — logged-in only

No new routes are added; the existing route gains optional query-string handling.

## Database changes
No schema changes. New/modified read helpers are needed in `database/db.py`, each accepting optional `start_date`/`end_date` and appending `AND date >= ?` / `AND date <= ?` conditions with parameterized values when provided:
- `get_user_expense_summary(user_id, start_date=None, end_date=None)`
- `get_category_breakdown(user_id, start_date=None, end_date=None)`
- `get_user_expenses(user_id, limit=None, start_date=None, end_date=None)`

## Templates
- **Create:** None
- **Modify:**
  - `templates/profile.html` — add a small date-range filter form (`start_date`, `end_date` inputs, type `date`, submitted via `GET`) above the summary section; show a "Clear filter" link (plain `/profile`) when a filter is active; preserve submitted `start_date`/`end_date` values in the form inputs

## Files to change
- `app.py` — `profile()` view reads `request.args.get("start_date")` / `request.args.get("end_date")`, validates format, and passes them through to the three helper calls and to the template for re-display
- `database/db.py` — extend `get_user_expense_summary`, `get_category_breakdown`, `get_user_expenses` with optional date-range filtering
- `templates/profile.html` — add filter form and "Clear filter" link

## Files to create
No new files.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Filter form must submit via `GET` so the range is shareable/bookmarkable as a URL
- Invalid or malformed dates in `start_date`/`end_date` must be ignored (fall back to unfiltered), not raise a 500
- If `start_date` is after `end_date`, treat the filter as invalid and fall back to unfiltered rather than erroring
- No DB logic inline in `app.py` — all date-filtering logic lives in `database/db.py`
- Use `url_for()` for all internal links, including the "Clear filter" link

## Definition of done
- [ ] Visiting `/profile` with no query parameters shows all-time data, unchanged from Step 5 behavior
- [ ] Visiting `/profile?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` shows summary totals, category breakdown, and recent expenses limited to that range
- [ ] The filter form inputs retain the submitted `start_date`/`end_date` values after filtering
- [ ] A "Clear filter" link appears only when a filter is active and returns to unfiltered `/profile`
- [ ] Submitting an invalid date format or `start_date` after `end_date` does not crash the app and falls back to unfiltered results
- [ ] Category breakdown percentages/bar widths (`max_category_total`) recalculate correctly for the filtered range
- [ ] `pytest` still passes with no regressions to existing routes
