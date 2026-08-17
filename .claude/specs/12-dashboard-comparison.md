# Spec: Dashboard Comparison

## Overview
`/analytics` currently renders a static "Coming Soon" placeholder — it's the
last stub route left on the roadmap. This step replaces it with a real
month-over-month view: total spend this month vs. last month (with a
percentage change), plus a per-category breakdown comparing the same two
periods. It gives users a quick answer to "am I spending more or less than
last month, and in what categories?" without needing to manually filter
`/profile` twice and do the math themselves.

## Depends on
- Step 1 (Database Setup) — `expenses` table.
- Step 4 (Profile Page) — establishes the summary/category-breakdown display
  conventions this feature mirrors.
- Step 6 (Date Filter For Profile Page) — `_date_filter_clause`,
  `get_user_expense_summary`, `get_category_breakdown` all already accept
  `start_date`/`end_date` and are reused as-is here, called twice (once per
  month) rather than duplicated.
- Step 10 (Recurring Expenses) — `sync_due_recurring_expenses` must run
  before computing "this month" totals, same as `/profile` does, so
  due recurring expenses are materialized first.

## Routes
- `GET /analytics` — replaces the existing stub — renders the month
  comparison dashboard (current-month vs. previous-month total, % change,
  and per-category breakdown for both months) — logged-in only. No new
  route path; this is Step 12's implementation of the route already
  reserved in `app.py`.

No other new routes.

## Database changes
No new tables or columns.

No new `db.py` functions either — `get_user_expense_summary(user_id,
start_date, end_date)` and `get_category_breakdown(user_id, start_date,
end_date)` (both already in `database/db.py`) are called twice each, once
per month's date range, entirely from the route. This mirrors how
`_search_filter_clause` in Step 11 built on `_date_filter_clause` instead
of duplicating it — here the reuse is even more direct, since no new
filtering logic is needed at all, just two different `(start_date,
end_date)` pairs.

Month boundaries are computed in `app.py` (not `db.py`), using the same
`calendar.monthrange`-based approach `_add_one_month` already uses in
`db.py`, since `date` is stored as `'YYYY-MM-DD'` TEXT and sorts correctly
as a plain string range:

```python
def _current_and_previous_month_ranges(today=None):
    """Returns ((cur_start, cur_end), (prev_start, prev_end)) as
    'YYYY-MM-DD' strings, for the calendar month containing `today`
    and the one immediately before it."""
    today = today or date.today()
    cur_start = date(today.year, today.month, 1)
    cur_last_day = calendar.monthrange(today.year, today.month)[1]
    cur_end = date(today.year, today.month, cur_last_day)

    if today.month == 1:
        prev_year, prev_month = today.year - 1, 12
    else:
        prev_year, prev_month = today.year, today.month - 1
    prev_start = date(prev_year, prev_month, 1)
    prev_last_day = calendar.monthrange(prev_year, prev_month)[1]
    prev_end = date(prev_year, prev_month, prev_last_day)

    fmt = "%Y-%m-%d"
    return (
        (cur_start.strftime(fmt), cur_end.strftime(fmt)),
        (prev_start.strftime(fmt), prev_end.strftime(fmt)),
    )
```

`calendar` must be imported in `app.py` if not already (it already is in
`database/db.py`; check before adding a duplicate import).

## Templates
- **Modify `templates/analytics.html`** — replace the entire "Coming Soon"
  body with the real dashboard: a stat row (this month total, last month
  total, % change), then a per-category comparison panel.
- **Modify `static/css/analytics.css`** — remove the now-unused
  `.coming-soon-*` rules, add only what's not already covered by
  `profile.css` (e.g. a `.stat-change` positive/negative color modifier for
  the % change figure). The template's `{% block head %}` should link
  **both** `profile.css` (for `.stat-card`, `.panel`, `.category-list`,
  `.category-bar-track`/`.category-bar`, `.cat-badge`) and `analytics.css`
  (for the small amount of page-specific styling) — same
  reuse-before-reinvent approach Step 11 used with `profile.css`.

No new templates.

## Files to change
- `app.py` — implement the `/analytics` route body (currently a stub);
  add `_current_and_previous_month_ranges` helper; add `calendar` import
  if missing.
- `templates/analytics.html` — replace placeholder content with the
  comparison dashboard.
- `static/css/analytics.css` — drop `.coming-soon-*`, add only
  page-specific deltas not already in `profile.css`.
- `CLAUDE.md` — add `GET /analytics` row to the routes table (it's
  currently missing from that table entirely, even as a stub) marked
  "Implemented — Step 12".

## Files to create
None.

## New dependencies
No new dependencies. `calendar` and `datetime.date` are both stdlib and
already used in `database/db.py`.

## Rules for implementation
- No SQLAlchemy or ORMs.
- Parameterised queries only — inherited for free here since no new SQL is
  written; `get_user_expense_summary`/`get_category_breakdown` already use
  `?` placeholders.
- Passwords hashed with werkzeug (n/a to this feature, no auth changes).
- Use CSS variables — never hardcode hex values.
- All templates extend `base.html`.
- `sync_due_recurring_expenses(session["user_id"])` must be called at the
  top of the route, before either summary query, exactly as `/profile`
  already does — otherwise a recurring expense due this month could be
  missing from the "this month" total depending on whether the user has
  visited `/profile` yet.
- Guard against division by zero: if last month's total is `0`, percentage
  change must not be computed as a division — render an explicit "N/A" (or
  "New spending" if this month > 0) state instead of `inf`/`NaN`/a crash.
- Per-category comparison must include a category if it has spend in
  *either* month (not just categories present in both) — a category with
  spend last month but zero this month is a meaningful signal ("you spent
  ₹0 on Entertainment this month, down from ₹1,200") and must not be
  silently dropped just because it's missing from the current month's
  `get_category_breakdown` result.
- All amounts formatted `₹{{ "{:,.2f}".format(amount) }}`, matching every
  other template's currency formatting (`profile.html`,
  `expenses_search.html`).
- Reuse `.stat-card`, `.panel`, `.panel-title`, `.category-list`,
  `.category-bar-track`/`.category-bar`, `.cat-badge` classes from
  `profile.css` rather than inventing parallel CSS.
- No IDOR risk to check — both summary calls are always scoped by
  `session["user_id"]`, no id-based lookups are introduced.

## Definition of done
1. Logged out → `GET /analytics` redirects to `/login`.
2. Logged in with no expenses at all → dashboard renders without error,
   both months show ₹0.00, % change shows "N/A" (not a crash or `inf`).
3. Logged in with expenses only in the current month → this month's total
   is correct, last month shows ₹0.00, % change shows "New spending" (or
   equivalent), not a divide-by-zero error.
4. Logged in with expenses in both this month and last month → both totals
   are correct and % change is calculated correctly (positive when this
   month is higher, negative when lower).
5. A recurring expense due today that hasn't been materialized yet still
   shows up in "this month" total (i.e. `sync_due_recurring_expenses` ran
   before the summary query).
6. Per-category panel shows every category with spend in either month —
   including a category with spend last month but none this month (shown
   as ₹0.00 this month, not omitted).
7. Per-category panel does **not** show categories with ₹0.00 in both
   months.
8. All currency values formatted consistently with the rest of the app
   (`₹` prefix, thousands separator, 2 decimals).
9. Second logged-in user sees only their own totals — never another user's
   data.
10. Nav "Analytics" link still points to `/analytics` and gets the
    `active` class on this page (no nav changes needed, but must not
    regress).
11. `CLAUDE.md` routes table has a `GET /analytics` row marked
    "Implemented — Step 12".
12. Full `pytest` suite still passes — no regressions in tests touching
    `get_user_expense_summary`, `get_category_breakdown`, or
    `sync_due_recurring_expenses`.
