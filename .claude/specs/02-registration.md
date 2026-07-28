# Spec: Registration

## Overview
This feature implements user account creation for Spendly. The `register.html` template and `GET /register` route already exist, but form submission does nothing — there is no `POST /register` handler. This step wires the existing form to `database/db.py`, validating input, hashing passwords, and inserting new users so that people can actually sign up before login (Step 3) and the rest of the app can be used.

## Depends on
- Step 01 — Database setup (`users` table, `get_db()`, `init_db()`)

## Routes
- `GET /register` — already implemented, no change
- `POST /register` — create a new user from form data — public

## Database changes
No database changes. `users` table (id, name, email, password_hash, created_at) already supports this feature as defined in `database/db.py`.

## Templates
- **Create:** none
- **Modify:** `templates/register.html` — render `{{ error }}` messages for validation failures (missing fields, invalid email, password too short, duplicate email) and repopulate `name`/`email` values on failed submission so the user doesn't retype them

## Files to change
- `app.py` — change `register()` to accept `GET` and `POST`, handle form validation, call a DB helper to insert the user, redirect to `login` on success
- `database/db.py` — add a `create_user(name, email, password)` helper that hashes the password and inserts the row, raising/handling `sqlite3.IntegrityError` for duplicate emails

## Files to create
None

## New dependencies
No new dependencies

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (`generate_password_hash`)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- DB logic lives in `database/db.py` only, never inline in `app.py`
- Use `abort()` for HTTP errors, not bare string returns
- Password minimum length: 8 characters (matches the placeholder text already in `register.html`)

## Definition of done
- [ ] Submitting the register form with valid, unique name/email/password creates a user in the `users` table with a hashed password
- [ ] Submitting with an email that already exists shows an error on the page and does not create a duplicate row
- [ ] Submitting with a missing field shows an error and does not hit the database
- [ ] Submitting with a password under 8 characters shows an error
- [ ] On success, the user is redirected to `/login`
- [ ] `GET /register` still renders the form normally with no errors
- [ ] No plaintext passwords appear anywhere in the database
