# Spec: Add Expense

## Overview
This feature implements the "add expense" flow — the first write path for
expense data in Spendly. It replaces the `/expenses/add` stub with a real
form that lets a logged-in user record a new expense (amount, category,
date, optional description), persist it via `database/db.py`, and land back
on their profile page where the new entry appears in recent expenses and
totals. This is the step that makes the app's core loop (log an expense,
see it reflected in analytics/profile) functional for the first time.

## Depends on
- Step 01 — Database setup (`users`, `expenses` tables, `get_db()`)
- Step 03 — Login/logout (session-based auth, `user_id` in session)
- Step 04/05 — Profile page (destination after a successful add; consumes
  `get_user_expenses`, `get_user_expense_summary`, `get_category_breakdown`)

## Routes
- `GET /expenses/add` — render the add-expense form — logged-in only
- `POST /expenses/add` — validate and insert a new expense, then redirect
  to `/profile` — logged-in only

Both methods are handled by the same `add_expense` view, matching the
existing pattern used by `register`, `login`, and `profile_edit`.

## Database changes
No schema changes. The `expenses` table (`database/db.py` `init_db()`)
already has the columns needed: `user_id`, `amount`, `category`, `date`,
`description`, `created_at`. This step adds a new helper function,
`create_expense(user_id, amount, category, date, description)`, to
`database/db.py` that performs a parameterized `INSERT` and returns
`cursor.lastrowid`, following the same connect/try/finally/close pattern as
`create_user`.

## Templates
- **Create:** `templates/expenses_add.html` — the add-expense form, extends
  `base.html`, styled after `templates/profile_edit.html` /
  `templates/register.html` (form-input, label, error banner patterns).
- **Modify:** none required. (No nav link needed — expenses are added via
  a link/button from the profile page in a later step, or already exists;
  do not add new nav entries unless a link is needed to reach the form.)

## Files to change
- `app.py` — replace the `add_expense` stub with the real `GET`/`POST`
  implementation; import `create_expense` and `CATEGORIES` from
  `database.db`.
- `database/db.py` — add `create_expense(...)` helper.

## Files to create
- `templates/expenses_add.html`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (n/a for this feature, but no auth logic
  should be duplicated or weakened)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- `add_expense` must redirect unauthenticated users to `/login`, matching
  `profile` and `profile_edit`
- Category must be validated against `CATEGORIES` from `database/db.py`
  (reject anything not in that list)
- Amount must be validated as a positive number (reject zero, negative,
  non-numeric)
- Date must be validated as a real date in `YYYY-MM-DD` format (reuse the
  parsing approach already used in `_parse_date_range` in `app.py`)
- Description is optional; store `None`/empty consistently with how
  existing seeded expenses are read (`e["description"] or ""` in
  `profile()`)
- On validation failure, re-render `expenses_add.html` with an `error`
  message and the submitted values, matching the `register`/`login`/
  `profile_edit` pattern — never a bare string return
- On success, redirect to `url_for("profile")`

## Definition of done
- [ ] Visiting `/expenses/add` while logged out redirects to `/login`
- [ ] Visiting `/expenses/add` while logged in renders the add-expense form
- [ ] Submitting the form with valid amount, category, date, and
      description creates a new row in `expenses` for the current user
- [ ] After a successful submit, the browser lands on `/profile` and the
      new expense appears in "recent expenses" and is reflected in the
      summary totals and category breakdown
- [ ] Submitting with a missing amount, invalid amount (e.g. `-5`, `abc`),
      missing/invalid category, or missing/invalid date re-renders the form
      with a clear error message and no row is inserted
- [ ] Submitting with an empty description succeeds and stores it without
      error
- [ ] A second user's expenses are unaffected — the new expense is only
      ever inserted with `user_id = session["user_id"]`
