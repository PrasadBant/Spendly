# Spec: Edit Expense

## Overview
This feature implements the "edit expense" flow, replacing the
`/expenses/<id>/edit` stub with a real form that lets a logged-in user
update an existing expense they own (amount, category, date, description).
It follows the same add/validate/persist/redirect shape as the add-expense
flow (Step 07), but pre-fills the form with the existing row and updates
in place instead of inserting. This is the step that makes expense data
correctable rather than write-once.

## Depends on
- Step 01 — Database setup (`users`, `expenses` tables, `get_db()`)
- Step 03 — Login/logout (session-based auth, `user_id` in session)
- Step 04/05 — Profile page (destination after a successful edit)
- Step 07 — Add expense (`CATEGORIES` validation pattern, `expenses_add.html`
  form conventions, amount/date validation approach)

## Routes
- `GET /expenses/<id>/edit` — render the edit-expense form pre-filled with
  the existing expense's values — logged-in only, owner only
- `POST /expenses/<id>/edit` — validate and update the expense, then
  redirect to `/profile` — logged-in only, owner only

Both methods are handled by the same `edit_expense` view, matching the
existing pattern used by `add_expense` and `profile_edit`.

## Database changes
No schema changes. This step adds two new helpers to `database/db.py`:
- `get_expense_by_id(expense_id)` — parameterized `SELECT * FROM expenses
  WHERE id = ?`, returns the row or `None`, following the same
  connect/try/finally/close pattern as `get_user_by_id`.
- `update_expense(expense_id, amount, category, date, description)` —
  parameterized `UPDATE expenses SET amount = ?, category = ?, date = ?,
  description = ? WHERE id = ?`, following the same pattern as
  `update_user`.

## Templates
- **Create:** `templates/expenses_edit.html` — the edit-expense form,
  extends `base.html`, styled after `templates/expenses_add.html` (same
  form-input, label, error banner, category `<select>` markup), with
  fields pre-filled from the existing expense on `GET` and re-populated
  with submitted values on a validation error.
- **Modify:** none required.

## Files to change
- `app.py` — replace the `edit_expense` stub with the real `GET`/`POST`
  implementation; import `get_expense_by_id` and `update_expense` from
  `database.db`.
- `database/db.py` — add `get_expense_by_id(...)` and `update_expense(...)`
  helpers.

## Files to create
- `templates/expenses_edit.html`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (n/a for this feature, but no auth logic
  should be duplicated or weakened)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- `edit_expense` must redirect unauthenticated users to `/login`, matching
  `add_expense` and `profile`
- `edit_expense` must look up the expense via `get_expense_by_id`; if it
  does not exist, call `abort(404)`
- `edit_expense` must verify the expense's `user_id` matches
  `session["user_id"]`; if it belongs to another user, call `abort(404)`
  (do not reveal existence of other users' expenses via a 403)
- Category must be validated against `CATEGORIES` from `database/db.py`
  (reject anything not in that list)
- Amount must be validated as a positive number (reject zero, negative,
  non-numeric)
- Date must be validated as a real date in `YYYY-MM-DD` format (reuse the
  parsing approach already used in `add_expense`)
- Description is optional; store consistently with `add_expense`
- On validation failure, re-render `expenses_edit.html` with an `error`
  message and the submitted values, matching the `add_expense` pattern —
  never a bare string return
- On success, redirect to `url_for("profile")`

## Definition of done
- [ ] Visiting `/expenses/<id>/edit` while logged out redirects to `/login`
- [ ] Visiting `/expenses/<id>/edit` for a non-existent id returns a 404
- [ ] Visiting `/expenses/<id>/edit` for an expense owned by another user
      returns a 404
- [ ] Visiting `/expenses/<id>/edit` for an expense owned by the current
      user renders the edit form pre-filled with its amount, category,
      date, and description
- [ ] Submitting the form with valid amount, category, date, and
      description updates the existing row (no new row is created) for
      the current user
- [ ] After a successful submit, the browser lands on `/profile` and the
      updated values are reflected in "recent expenses", summary totals,
      and category breakdown
- [ ] Submitting with a missing amount, invalid amount (e.g. `-5`, `abc`),
      missing/invalid category, or missing/invalid date re-renders the
      form with a clear error message and the row is left unchanged
- [ ] Submitting with an empty description succeeds and stores it without
      error
- [ ] A second user's expenses are unaffected by any edit
</content>
