# Spec: Delete Expense

## Overview
This feature replaces the `/expenses/<id>/delete` stub with a real
implementation that lets a logged-in user permanently remove an expense
they own. It follows the same ownership-check pattern already
established by `edit_expense` (Step 08), and the same "POST + JS confirm
dialog" pattern already used by `profile_delete` (account deletion) for
the destructive action. This closes out the core expense CRUD flow
(add → edit → delete) for the Spendly roadmap.

## Depends on
- Step 01 — Database setup (`users`, `expenses` tables, `get_db()`)
- Step 03 — Login/logout (session-based auth, `user_id` in session)
- Step 04/05 — Profile page (destination after a successful delete, and
  the "Recent Transactions" table this feature adds a Delete action to)
- Step 08 — Edit expense (`get_expense_by_id`, ownership-check pattern
  to reuse for delete)

## Routes
- `POST /expenses/<id>/delete` — delete the expense, then redirect to
  `/profile` — logged-in only, owner only

The existing stub is `GET /expenses/<id>/delete`; this step changes the
method to `POST` (matching `profile_delete`'s POST-only, no-GET-body
pattern for destructive actions) since a bare `GET` should never mutate
data.

## Database changes
No schema changes. This step adds one new helper to `database/db.py`:
- `delete_expense(expense_id)` — parameterized
  `DELETE FROM expenses WHERE id = ?`, following the same
  connect/try/finally/close pattern as `update_expense`.

## Templates
- **Create:** none.
- **Modify:** `templates/profile.html` — add a "Delete" button/form next
  to the existing "Edit" link in the `col-actions` cell of the Recent
  Transactions table (around line 83-85), posting to
  `url_for('delete_expense', id=expense['id'])`, with a unique form `id`
  per row (e.g. `delete-expense-form-{{ expense['id'] }}`) so
  `static/js/main.js` can attach a confirm dialog to each one, matching
  the `delete-account-form` pattern.

## Files to change
- `app.py` — replace the `delete_expense` stub with the real
  implementation; change the route method from `GET` to `POST`; import
  `delete_expense` from `database.db`.
- `database/db.py` — add the `delete_expense(expense_id)` helper.
- `templates/profile.html` — add the delete form/button to each
  transaction row.
- `static/js/main.js` — extend the existing confirm-dialog logic (or add
  a parallel block) to intercept submission of every
  `delete-expense-form-*` and show a `confirm()` prompt before allowing
  the POST through, same shape as the account-delete confirmation.

## Files to create
No new files.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (n/a for this feature, but no auth
  logic should be duplicated or weakened)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html` (n/a for new templates since none are
  created; `profile.html` already does)
- `delete_expense` (route) must redirect unauthenticated users to
  `/login`, matching `edit_expense` and `add_expense`
- `delete_expense` (route) must look up the expense via
  `get_expense_by_id`; if it does not exist, call `abort(404)`
- `delete_expense` (route) must verify the expense's `user_id` matches
  `session["user_id"]`; if it belongs to another user, call `abort(404)`
  (do not reveal existence of other users' expenses via a 403)
- The route only accepts `POST` — no `GET` handler, so the action cannot
  be triggered by a plain link or browser prefetch
- On success, redirect to `url_for("profile")`
- The delete action must be confirmed client-side via `confirm()` before
  the form submits, reusing the pattern in `static/js/main.js`
- Deleting an expense must not affect other expenses or other users' data

## Definition of done
- [ ] Visiting `/expenses/<id>/delete` with `GET` returns a 404/405 (no
      route handles `GET`)
- [ ] Submitting `POST /expenses/<id>/delete` while logged out redirects
      to `/login`
- [ ] Submitting `POST /expenses/<id>/delete` for a non-existent id
      returns a 404
- [ ] Submitting `POST /expenses/<id>/delete` for an expense owned by
      another user returns a 404
- [ ] Submitting `POST /expenses/<id>/delete` for an expense owned by the
      current user removes it from the database
- [ ] After a successful delete, the browser lands on `/profile` and the
      deleted expense no longer appears in "recent expenses", and
      summary totals and category breakdown reflect its removal
- [ ] Clicking "Delete" on a transaction row shows a confirm dialog
      before any request is sent; cancelling the dialog leaves the
      expense untouched
- [ ] A second user's expenses are unaffected by any delete
</content>
