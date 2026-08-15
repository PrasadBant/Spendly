# Spec: Recurring Expenses

## Overview
Spendly currently requires every expense — including fixed monthly costs like
rent or subscriptions — to be entered by hand each time. This feature lets a
user mark an expense as recurring (weekly or monthly) so future occurrences
are generated automatically instead of retyped. Because Spendly is a single
Flask process with no background job runner (no Celery, no OS cron), recurrence
is implemented as **lazy generation**: due occurrences are created the next
time the user's data is loaded (on `/profile`), not on a wall-clock schedule.

## Depends on
- Step 07 (add-expense) — reuses `CATEGORIES`, the add-expense form, and
  `create_expense`.
- Step 09 (delete-expense) — the "cancel recurring" flow mirrors the existing
  delete-expense ownership-check pattern.

## Routes
- `GET /expenses/recurring` — list the current user's recurring expense
  templates — logged-in
- `POST /expenses/recurring/add` — create a new recurring template (fields:
  amount, category, description, interval, start date) — logged-in
- `POST /expenses/recurring/<int:id>/delete` — cancel (delete) a recurring
  template — logged-in, owner-only (404 if the template belongs to another
  user, matching `edit_expense`/`delete_expense`)

`GET /profile` is modified (not a new route) to call the sync helper before
reading expense data, so due occurrences appear immediately.

## Database changes
New table, added to `init_db()` in `database/db.py`:

```sql
CREATE TABLE IF NOT EXISTS recurring_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    interval TEXT NOT NULL,          -- 'weekly' or 'monthly'
    next_run_date TEXT NOT NULL,     -- 'YYYY-MM-DD', next date to generate
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users (id)
)
```

`interval` is validated against `("weekly", "monthly")` in the route handler,
the same way `category` is validated against `CATEGORIES` — no DB `CHECK`
constraint, consistent with existing style.

Generated occurrences are inserted into the existing `expenses` table via the
existing `create_expense()` — no changes to the `expenses` schema.

## Templates
- **Create:** `templates/expenses_recurring.html` — list of active recurring
  templates (amount, category, interval, next run date) with a "New
  recurring expense" form and a cancel button per row, following the same
  layout conventions as `expenses_add.html` / `expenses_edit.html`.
- **Modify:** `templates/profile.html` — add a small nav link to
  `/expenses/recurring` near the existing "Add expense" link.
- **Modify:** `templates/base.html` — only if the nav link belongs in the
  shared header rather than the profile page (decide during implementation
  based on where "Add expense" currently lives).

## Files to change
- `database/db.py` — add `recurring_expenses` table to `init_db()`; add
  `create_recurring_expense()`, `get_recurring_expenses(user_id)`,
  `get_recurring_expense_by_id(id)`, `delete_recurring_expense_by_id(id)`,
  `sync_due_recurring_expenses(user_id)` (generates due `expenses` rows and
  advances `next_run_date`).
- `app.py` — import new `db.py` helpers; add the three new routes; call
  `sync_due_recurring_expenses(session["user_id"])` at the top of the
  `profile()` route, before the existing summary/breakdown/recent-expenses
  queries.
- `templates/profile.html` — add link to the new recurring-expenses page.
- `CLAUDE.md` — add `GET /expenses/recurring` to the routes table once
  implemented (and note that the existing stub table for steps 3/4/7/8/9 is
  already stale — those are implemented, not stubs).

## Files to create
- `templates/expenses_recurring.html`
- `.claude/specs/10-recurring-expenses.md` (this file)

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only, matching `database/db.py`.
- Parameterised queries only (`?` placeholders) — never f-string values into
  SQL. `_date_filter_clause`-style dynamic-but-safe query assembly is fine
  (static fragments only), same as existing code.
- All DB logic lives in `database/db.py` — never inline SQL in `app.py`.
- `interval` validated against an explicit allow-list (`weekly`, `monthly`)
  in the route, same pattern as `category` vs `CATEGORIES`.
- Amount/date validation on the recurring-add form must reuse the same
  checks as `add_expense` (positive finite float, valid `YYYY-MM-DD` date).
- Ownership check (`template["user_id"] != session["user_id"] → abort(404)`)
  required on the delete route — same pattern as `edit_expense`/
  `delete_expense`.
- `sync_due_recurring_expenses` must be idempotent and safe to call on every
  `/profile` load — advancing `next_run_date` past `today` in a loop so a
  user who hasn't logged in for months gets all missed occurrences
  backfilled, not just one.
- Use CSS variables — never hardcode hex values — matching `static/css/style.css`.
- All new templates extend `base.html`.
- Every internal link uses `url_for()` — never a hardcoded path.

## Definition of done
- [ ] Creating a recurring expense (e.g. $1200/monthly "Rent" starting today)
      via `/expenses/recurring` saves a row in `recurring_expenses` with
      `next_run_date` set correctly.
- [ ] Visiting `/profile` immediately after creating a due recurring
      template generates a matching row in `expenses` and advances
      `next_run_date` to the next period.
- [ ] Visiting `/profile` again without any due templates does **not**
      create duplicate expense rows.
- [ ] A recurring template whose `next_run_date` is in the future does not
      generate an expense on `/profile` load.
- [ ] `/expenses/recurring` lists only the logged-in user's own templates.
- [ ] `POST /expenses/recurring/<id>/delete` for another user's template
      returns 404, not a redirect.
- [ ] Cancelling a recurring template stops future generation but does not
      delete already-generated `expenses` rows.
- [ ] All new routes redirect anonymous users to `/login`.
- [ ] `pytest` passes with no regressions in existing test files.
