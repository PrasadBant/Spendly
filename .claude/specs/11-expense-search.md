# Spec: Expense Search

## Overview
Right now the only way to narrow down expenses is the date-range filter on
`/profile`, and even then only the 6 most recent matching rows are shown.
As a user's expense history grows, they need a dedicated way to find a
specific transaction — e.g. "that ₹450 Food expense from last month" — by
searching its description and/or filtering by category, amount range, and
date range, with the *full* matching result set (not capped at 6). This
feature adds a standalone search page for that purpose, following the same
pattern established by `/expenses/recurring` (Step 10): its own route, its
own template, reusing existing DB/table/CSS conventions rather than
inventing new ones.

## Depends on
- Step 4 (Profile page) and Step 5 (Backend routes for profile page) — reuses
  `get_user_by_id`, session-based auth guard, and the `CATEGORIES` constant.
- Step 7 (Add expense) — reuses the `expenses` table and its columns
  unchanged; no schema migration needed.
- Step 6 (Date filter on profile) — reuses the existing `_parse_date_range`
  validation pattern in `app.py`.

## Routes
- `GET /expenses/search` — logged-in — renders the search form and, if any
  filter query params are present, the matching expenses (full result set,
  not limited to 6). With no filters applied, shows an empty/prompt state
  (does not dump the user's entire history unfiltered).

No POST route is needed — filters are submitted as a `GET` query string so
results are shareable/bookmarkable/back-button-friendly, matching the
existing `/profile` date-filter form's approach.

## Database changes
No new tables or columns — verified against `database/db.py`: the
`expenses` table already has every column this feature filters on
(`amount`, `category`, `date`, `description`).

One new query function in `database/db.py`:
- `search_user_expenses(user_id, q=None, category=None, min_amount=None, max_amount=None, start_date=None, end_date=None)`
  — returns matching rows ordered `date DESC, id DESC`. Builds its WHERE
  clause the same way `_date_filter_clause` does today (static SQL
  fragments + a `params` list of `?` placeholders, never an f-string of a
  value into SQL). Generalize the existing `_date_filter_clause` helper
  into a `_search_filter_clause` that layers on top of it:
  - `q` → `AND description LIKE ?` with the value wrapped as `f"%{q}%"` in
    Python (the `%` wildcards are data inside the placeholder, not part of
    the SQL string) — still fully parameterized.
  - `category` → `AND category = ?` (validated against `CATEGORIES` in the
    route before it ever reaches this function, same as every other route).
  - `min_amount` / `max_amount` → `AND amount >= ?` / `AND amount <= ?`.
  - `start_date` / `end_date` → reuse the existing date clause logic.

## Templates
- **Create:** `templates/expenses_search.html` — a filter form (text input
  for description `q`, category `<select>`, min/max amount number inputs,
  start/end date inputs, Search button, Clear-filters link) above a results
  table. Reuses:
  - `.date-filter-form` / `.form-group` / `.form-input` styling from
    `profile.html`'s existing date filter for the filter bar.
  - `.panel > .panel-title` + `.transactions-table` (`.col-amount`,
    `.cat-badge cat-{{ category|lower }}`) from `profile.html`'s "Recent
    Transactions" table for the results, including Edit/Delete actions per
    row (links to the existing `edit_expense` / `delete_expense` routes —
    no new edit/delete logic needed, this page just surfaces existing
    rows).
  - `.panel-empty` for both the "no filters applied yet" prompt state and
    the "no expenses matched" empty state (distinct messages, same class).
  Include `<link rel="stylesheet" href="{{ url_for('static', filename='css/profile.css') }}">` in `{% block head %}` — no new CSS file needed.

- **Modify:** `templates/base.html` — add a "Search" nav link next to the
  existing "Recurring" link, following the exact same `nav-link` /
  `active`-class pattern.

## Files to change
- `app.py` — add `search_user_expenses` to the `database.db` import block
  (alphabetical); add the `expenses_search` route.
- `database/db.py` — add `_search_filter_clause` and `search_user_expenses`.
- `templates/base.html` — add the Search nav link.
- `CLAUDE.md` — add `GET /expenses/search` to the routes table.

## Files to create
- `templates/expenses_search.html`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterized queries only — including the `LIKE` search, where the `%`
  wildcards are built into the Python value passed as a `?` parameter, never
  concatenated into the SQL string itself
- Passwords hashed with werkzeug (n/a to this feature, no password handling)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Reuse `CATEGORIES` for category validation — never trust the raw query
  param
- `min_amount`/`max_amount` must be validated as optional finite numbers
  (reuse the parsing style of `_validate_amount`, but empty is valid here —
  unlike add/edit expense, an empty amount field means "no bound", not an
  error)
- Ownership is implicit and total: `search_user_expenses` always scopes by
  `session["user_id"]` — there is no way to pass another user's `user_id`
  from the route, so no separate IDOR check is needed here (unlike the
  edit/delete-by-id routes)

## Definition of done
- [ ] Logged-out visit to `/expenses/search` redirects to `/login`
- [ ] Logged-in visit with no query params shows the filter form and a
      "enter a filter to search" prompt state, not the full expense list
- [ ] Searching by a description substring (e.g. "coffee") returns only
      expenses whose description contains it, case-insensitively
- [ ] Filtering by category alone returns only that category's expenses
- [ ] Filtering by min/max amount returns only expenses in that range
      (inclusive)
- [ ] Combining multiple filters (e.g. category + date range + min amount)
      ANDs them together correctly
- [ ] A search that matches nothing shows a distinct "no expenses matched"
      empty state, not an error
- [ ] Results are not capped at 6 — a filter matching 20 expenses shows all 20
- [ ] Each result row's Edit/Delete links work exactly as they do on
      `/profile`
- [ ] A second logged-in user's search never returns the first user's
      expenses, even with an identical query
- [ ] `pytest` — full suite passes with no regressions
