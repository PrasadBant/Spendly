# Spec: Login and Logout

## Overview
This feature lets a registered user (Step 2) actually authenticate: submit their email/password on the existing `login.html` form, get verified against the `users` table, and have their identity persisted across requests via a Flask session. It also implements the `/logout` stub so a signed-in user can end their session. This is the first step to introduce sessions, so it also establishes the pattern (`session['user_id']`) that Step 4 (profile) and later expense routes will rely on to know who's signed in.

## Depends on
- Step 01 — Database setup (`users` table, `get_db()`)
- Step 02 — Registration (`create_user()`, so there are real hashed-password users to log in as)

## Routes
- `GET /login` — already implemented, no change
- `POST /login` — verify email/password, start a session — public
- `GET /logout` — clear the session, redirect to landing — logged-in (redirect to `/login` if not signed in)

## Database changes
No database changes. `users` table (id, name, email, password_hash, created_at) already supports this — login only needs to `SELECT` by email and verify the hash.

## Templates
- **Create:** none
- **Modify:**
  - `templates/login.html` — repopulate the `email` field on failed submits (mirrors `register.html`'s pattern), fix hardcoded `action="/login"` to `{{ url_for('login') }}`
  - `templates/base.html` — nav becomes session-aware: show "Sign in" / "Get started" when logged out (unchanged), show the user's name and a "Logout" link (`url_for('logout')`) when `session.user_id` is set

## Files to change
- `app.py` — set `app.secret_key` (required for sessions), change `login()` to accept `GET`/`POST` with validation, implement `logout()` to clear the session and redirect
- `database/db.py` — add a `get_user_by_email(email)` helper returning the row (or `None`) so the route can verify the password hash
- `templates/login.html` — error/repopulation + `url_for` fix
- `templates/base.html` — session-aware nav

## Files to create
None

## New dependencies
No new dependencies — `werkzeug.security.check_password_hash` is part of the already-installed werkzeug package

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug — verify with `check_password_hash`, never compare plaintext
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- DB logic lives in `database/db.py` only, never inline in `app.py`
- Use `abort()` for HTTP errors, not bare string returns
- `app.secret_key` must be set for `session` to work — read from an environment variable if present, falling back to a fixed dev-only value (do not hardcode a "production-grade" secret)
- Do not store the password hash or any sensitive data in the session — only `user_id`

## Definition of done
- [ ] Submitting `/login` with a correct email/password redirects to a logged-in view (e.g. `/`) and `session['user_id']` is set to that user's id
- [ ] Submitting `/login` with a wrong password shows an error and does not set a session
- [ ] Submitting `/login` with an email that doesn't exist shows the same generic error (no "user not found" vs "wrong password" distinction, to avoid leaking which emails are registered)
- [ ] Submitting `/login` with a missing field shows an error and does not hit the database
- [ ] After logging in, the nav bar shows the user's name and a Logout link instead of "Sign in"/"Get started"
- [ ] Visiting `/logout` while logged in clears the session and redirects to `/`; nav reverts to the logged-out state
- [ ] Visiting `/logout` while not logged in redirects to `/login` without error
- [ ] `GET /login` still renders the form normally with no errors
