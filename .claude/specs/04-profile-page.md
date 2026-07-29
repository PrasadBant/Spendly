# Spec: Profile Page

## Overview
This step implements the `/profile` route, replacing its current stub with a real page that shows the logged-in user's account details (name, email, member-since date) and a summary of their expense activity. It is the first authenticated "account" page in Spendly and depends on the user and expenses tables already created in Step 1, and the session-based login/logout flow from Steps 2 and 3.

## Depends on
- Step 1 — Database Setup (`users`, `expenses` tables, `get_db()`)
- Step 2 — Registration (`create_user`, `get_user_by_email`)
- Step 3 — Login and Logout (session `user_id`, `get_user_by_id`, `logout` route)

## Routes
- `GET /profile` — renders the profile page for the logged-in user; redirects to `/login` if no `user_id` in session — logged-in only

## Database changes
No database changes. Reuses existing `users` and `expenses` tables. A new read-only helper is needed in `database/db.py` to aggregate expense totals per user (e.g. total spent, expense count) — this is a query addition, not a schema change.

## Templates
- **Create:** `templates/profile.html` — extends `base.html`; displays user name, email, join date, total expenses count, and total amount spent
- **Modify:** None

## Files to change
- `app.py` — replace the `/profile` stub with a real implementation that checks session, fetches user + summary data, and renders `profile.html`
- `database/db.py` — add a helper function (e.g. `get_user_expense_summary(user_id)`) using parameterized queries to compute expense count and total amount for a user

## Files to create
- `templates/profile.html`
- `static/css/profile.css` — page-specific styles for the profile layout

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (no password changes in this step; not touched)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- `/profile` must redirect unauthenticated users to `/login`, not raise an error
- No DB logic inline in `app.py` — all queries live in `database/db.py`
- Use `url_for()` for all internal links in `profile.html`

## Definition of done
- [ ] Visiting `/profile` while logged out redirects to `/login`
- [ ] Visiting `/profile` while logged in renders `templates/profile.html` (no more raw string response)
- [ ] Profile page displays the current user's name and email correctly
- [ ] Profile page displays a correct count of the user's expenses and total amount spent, matching the `expenses` table for that `user_id`
- [ ] Page styling uses `static/css/profile.css` with CSS variables, no inline `<style>` tags or hardcoded hex colors
- [ ] All links on the page use `url_for()`, no hardcoded URLs
- [ ] `pytest` still passes with no regressions to existing routes
