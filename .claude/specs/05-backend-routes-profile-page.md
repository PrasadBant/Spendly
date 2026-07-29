# Spec: Backend Routes For Profile Page

## Overview
Step 4 (`04-profile-page.md`) delivered a read-only `/profile` page: it shows the logged-in user's name, email, join date, and expense summary, backed by `get_user_by_id` and `get_user_expense_summary`. This step extends that account area with the backend routes needed to actually manage the account from the profile page: editing name/email, changing password, and deleting the account. It builds directly on Step 4's page and Step 3's session-based auth, turning `/profile` from a display-only page into a functional account-management hub.

## Depends on
- Step 1 — Database Setup (`users`, `expenses` tables, `get_db()`)
- Step 2 — Registration (`create_user`, email validation pattern, password length rule)
- Step 3 — Login and Logout (session `user_id`, `get_user_by_id`, `logout` route)
- Step 4 — Profile Page (`GET /profile`, `profile.html`, `get_user_expense_summary`, `profile.css`)

## Routes
- `GET /profile` — unchanged from Step 4; renders `profile.html` with user + summary — logged-in only
- `GET/POST /profile/edit` — form to update name and email; on POST, validates and updates the user record, then redirects to `/profile` — logged-in only
- `GET/POST /profile/change-password` — form requiring current password + new password (with confirmation); verifies current hash before updating — logged-in only
- `POST /profile/delete` — deletes the logged-in user's account (and their expenses via FK cascade or explicit delete), clears the session, redirects to landing — logged-in only

## Database changes
No schema changes. Reuses existing `users` and `expenses` tables and the existing `FOREIGN KEY (user_id) REFERENCES users (id)` on `expenses`. New read/write helpers are needed in `database/db.py`:
- `update_user(user_id, name, email)` — parameterized `UPDATE users SET name = ?, email = ? WHERE id = ?`
- `update_user_password(user_id, password_hash)` — parameterized `UPDATE users SET password_hash = ? WHERE id = ?`
- `delete_user(user_id)` — deletes the user's `expenses` rows, then the `users` row, in one connection/transaction (SQLite does not enforce `ON DELETE CASCADE` by default even with `PRAGMA foreign_keys = ON`, unless the FK is declared with `ON DELETE CASCADE` — since it isn't, expenses must be deleted explicitly before the user row)

## Templates
- **Create:**
  - `templates/profile_edit.html` — extends `base.html`; form for name/email, preserves submitted values on error, links back to `/profile`
  - `templates/profile_change_password.html` — extends `base.html`; form for current password, new password, confirm new password
- **Modify:**
  - `templates/profile.html` — add links/buttons to `/profile/edit`, `/profile/change-password`, and a delete-account action (with a confirmation step) using `url_for()`

## Files to change
- `app.py` — add `profile_edit`, `profile_change_password`, `profile_delete` view functions; all check `session["user_id"]` and redirect to `/login` if absent
- `database/db.py` — add `update_user`, `update_user_password`, `delete_user`
- `templates/profile.html` — add navigation to the new routes

## Files to create
- `templates/profile_edit.html`
- `templates/profile_change_password.html`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (`generate_password_hash` for new password, `check_password_hash` to verify current password before allowing a change)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Every new route must redirect unauthenticated users to `/login`, not raise an error
- No DB logic inline in `app.py` — all queries live in `database/db.py`
- Use `url_for()` for all internal links
- Reuse the existing email-format and password-length validation rules from `register()` in `app.py` for `/profile/edit` and `/profile/change-password`
- `/profile/edit` must catch `sqlite3.IntegrityError` for duplicate email, same pattern as `register()`
- `/profile/delete` must require `POST` (not a bare `GET` link) to avoid accidental deletion via crawlers/prefetch, and should ask for confirmation in the UI before submitting

## Definition of done
- [ ] Visiting `/profile/edit`, `/profile/change-password` while logged out redirects to `/login`
- [ ] `GET /profile/edit` pre-fills the form with the current user's name and email
- [ ] `POST /profile/edit` with a valid new name/email updates the `users` row and redirects to `/profile` showing the new values
- [ ] `POST /profile/edit` with an email already used by another account shows an error and does not update the row
- [ ] `POST /profile/change-password` with the wrong current password shows an error and does not change the hash
- [ ] `POST /profile/change-password` with a correct current password and matching new password (min 8 chars) updates the hash, and the user can log in with the new password afterward
- [ ] `POST /profile/delete` removes the user's row and all their `expenses` rows, clears the session, and redirects to the landing page
- [ ] After deletion, the deleted user's old credentials no longer work on `/login`
- [ ] Page styling uses `static/css/profile.css` with CSS variables, no inline `<style>` tags or hardcoded hex colors
- [ ] All links/forms use `url_for()`, no hardcoded URLs
- [ ] `pytest` still passes with no regressions to existing routes
