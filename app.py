import math
import os
import re
import sqlite3
from datetime import datetime, timedelta

from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import (
    CATEGORIES,
    create_expense,
    create_recurring_expense,
    create_user,
    delete_expense_by_id,
    delete_recurring_expense_by_id,
    delete_user,
    get_category_breakdown,
    get_db,
    get_expense_by_id,
    get_recurring_expense_by_id,
    get_recurring_expenses,
    get_user_by_email,
    get_user_by_id,
    get_user_expense_summary,
    get_user_expenses,
    init_db,
    search_user_expenses,
    seed_db,
    sync_due_recurring_expenses,
    update_expense,
    update_user,
    update_user_password,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-secret-key")


@app.context_processor
def inject_current_user():
    if "user_id" in session:
        return {"current_user": get_user_by_id(session["user_id"])}
    return {"current_user": None}

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("profile"))

    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not name or not email or not password:
        return render_template(
            "register.html", error="All fields are required.",
            name=name, email=email,
        )

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return render_template(
            "register.html", error="Please enter a valid email address.",
            name=name, email=email,
        )

    if len(password) < 8:
        return render_template(
            "register.html", error="Password must be at least 8 characters.",
            name=name, email=email,
        )

    try:
        create_user(name, email, password)
    except sqlite3.IntegrityError:
        return render_template(
            "register.html", error="An account with that email already exists.",
            name=name, email=email,
        )

    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("profile"))

    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not email or not password:
        return render_template(
            "login.html", error="All fields are required.", email=email,
        )

    user = get_user_by_email(email)
    if user is None or not check_password_hash(user["password_hash"], password):
        return render_template(
            "login.html", error="Invalid email or password.", email=email,
        )

    session["user_id"] = user["id"]
    return redirect(url_for("profile"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    if "user_id" not in session:
        return redirect(url_for("login"))
    session.pop("user_id", None)
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    sync_due_recurring_expenses(session["user_id"])

    start_date, end_date = _parse_date_range(
        request.args.get("start_date"), request.args.get("end_date")
    )

    user = get_user_by_id(session["user_id"])
    summary = get_user_expense_summary(session["user_id"], start_date, end_date)
    category_breakdown = get_category_breakdown(session["user_id"], start_date, end_date)
    recent_expenses = get_user_expenses(
        session["user_id"], limit=6, start_date=start_date, end_date=end_date
    )

    name_parts = user["name"].split()
    initials = "".join(part[0] for part in name_parts[:2]).upper()
    member_since = datetime.strptime(
        user["created_at"], "%Y-%m-%d %H:%M:%S"
    ).strftime("%d %b %Y")
    recent_expenses = _format_expenses_for_display(recent_expenses)
    top_category = category_breakdown[0]["category"] if category_breakdown else "—"
    max_category_total = category_breakdown[0]["total"] if category_breakdown else 0

    return render_template(
        "profile.html",
        user=user,
        summary=summary,
        initials=initials,
        member_since=member_since,
        recent_expenses=recent_expenses,
        category_breakdown=category_breakdown,
        top_category=top_category,
        max_category_total=max_category_total,
        start_date=start_date,
        end_date=end_date,
    )


def _format_expenses_for_display(expenses):
    """Shared by profile()/expenses_search() — turns raw expense rows into
    display-ready dicts (formatted date, description defaulted to "")."""
    return [
        {
            "id": e["id"],
            "date": datetime.strptime(e["date"], "%Y-%m-%d").strftime("%d %b %Y"),
            "description": e["description"] or "",
            "category": e["category"],
            "amount": e["amount"],
        }
        for e in expenses
    ]


def _validate_amount(raw_amount):
    """Shared by add_expense/edit_expense/add_recurring_expense.
    Returns (amount_value, error) — error is None on success."""
    if not raw_amount:
        return None, "Amount is required."

    try:
        amount_value = float(raw_amount)
    except ValueError:
        return None, "Amount must be a valid number."

    if not math.isfinite(amount_value) or amount_value <= 0:
        return None, "Amount must be a positive number."

    return amount_value, None


def _validate_date_string(raw_date, error="Please enter a valid date."):
    """Shared by add_expense/edit_expense/add_recurring_expense.
    Returns an error string, or None if raw_date is a valid 'YYYY-MM-DD'."""
    try:
        datetime.strptime(raw_date, "%Y-%m-%d")
    except ValueError:
        return error
    return None


def _parse_date_range(start_date, end_date):
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
        end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
    except ValueError:
        return None, None

    if start and end and start > end:
        return None, None

    return start_date or None, end_date or None


def _validate_amount_bound(raw_value, error):
    """Parses an optional min/max amount search bound (expenses_search).
    Unlike _validate_amount, an empty raw_value means "no bound" and is
    valid, not an error. Returns (value_or_None, error) — error is None
    on success."""
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return None, None

    try:
        value = float(raw_value)
    except ValueError:
        return None, error

    if not math.isfinite(value) or value < 0:
        return None, error

    return value, None


@app.route("/analytics")
def analytics():
    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template("expenses_add.html", categories=CATEGORIES)

    amount = request.form.get("amount", "").strip()
    category = request.form.get("category", "").strip()
    date = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip()

    def render_error(error):
        return render_template(
            "expenses_add.html", categories=CATEGORIES,
            error=error,
            amount=amount, category=category, date=date, description=description,
        )

    amount_value, amount_error = _validate_amount(amount)
    if amount_error:
        return render_error(amount_error)

    if category not in CATEGORIES:
        return render_error("Please select a valid category.")

    date_error = _validate_date_string(date, "Please enter a valid date.")
    if date_error:
        return render_error(date_error)

    try:
        # expenses.user_id has a FOREIGN KEY constraint; defensive guard in
        # case the session's user was deleted in another tab mid-request.
        create_expense(session["user_id"], amount_value, category, date, description)
    except sqlite3.IntegrityError:
        return render_error("Could not save expense. Please try again.")

    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    expense = get_expense_by_id(id)
    if expense is None or expense["user_id"] != session["user_id"]:
        abort(404)

    if request.method == "GET":
        return render_template(
            "expenses_edit.html", categories=CATEGORIES, expense=expense,
            amount=expense["amount"], category=expense["category"],
            date=expense["date"], description=expense["description"] or "",
        )

    amount = request.form.get("amount", "").strip()
    category = request.form.get("category", "").strip()
    date = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip()

    def render_error(error):
        return render_template(
            "expenses_edit.html", categories=CATEGORIES, expense=expense,
            error=error,
            amount=amount, category=category, date=date, description=description,
        )

    amount_value, amount_error = _validate_amount(amount)
    if amount_error:
        return render_error(amount_error)

    if category not in CATEGORIES:
        return render_error("Please select a valid category.")

    date_error = _validate_date_string(date, "Please enter a valid date.")
    if date_error:
        return render_error(date_error)

    try:
        update_expense(id, amount_value, category, date, description)
    except sqlite3.IntegrityError:
        return render_error("Could not save expense. Please try again.")

    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/delete", methods=["POST"])
def delete_expense(id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    expense = get_expense_by_id(id)
    if expense is None or expense["user_id"] != session["user_id"]:
        abort(404)

    delete_expense_by_id(id)
    return redirect(url_for("profile"))


@app.route("/expenses/recurring")
def expenses_recurring():
    if "user_id" not in session:
        return redirect(url_for("login"))

    recurring_expenses = get_recurring_expenses(session["user_id"])
    return render_template(
        "expenses_recurring.html",
        categories=CATEGORIES,
        recurring_expenses=recurring_expenses,
    )


@app.route("/expenses/recurring/add", methods=["POST"])
def add_recurring_expense():
    if "user_id" not in session:
        return redirect(url_for("login"))

    amount = request.form.get("amount", "").strip()
    category = request.form.get("category", "").strip()
    interval = request.form.get("interval", "").strip()
    start_date = request.form.get("start_date", "").strip()
    description = request.form.get("description", "").strip()

    def render_error(error):
        return render_template(
            "expenses_recurring.html", categories=CATEGORIES,
            recurring_expenses=get_recurring_expenses(session["user_id"]),
            error=error,
            amount=amount, category=category, interval=interval,
            start_date=start_date, description=description,
        )

    amount_value, amount_error = _validate_amount(amount)
    if amount_error:
        return render_error(amount_error)

    if category not in CATEGORIES:
        return render_error("Please select a valid category.")

    if interval not in ("weekly", "monthly"):
        return render_error("Please select a valid interval.")

    date_error = _validate_date_string(start_date, "Please enter a valid start date.")
    if date_error:
        return render_error(date_error)

    # Bounds the sync_due_recurring_expenses() backfill loop — without this,
    # a far-past start_date + a short interval could generate an unbounded
    # number of expense rows on the next /profile load.
    one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    if start_date < one_year_ago:
        return render_error("Start date can't be more than a year in the past.")

    try:
        create_recurring_expense(
            session["user_id"], amount_value, category, description,
            interval, start_date,
        )
    except sqlite3.IntegrityError:
        return render_error("Could not save recurring expense. Please try again.")

    return redirect(url_for("expenses_recurring"))


@app.route("/expenses/recurring/<int:id>/delete", methods=["POST"])
def delete_recurring_expense(id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    template = get_recurring_expense_by_id(id)
    if template is None or template["user_id"] != session["user_id"]:
        abort(404)

    delete_recurring_expense_by_id(id)
    return redirect(url_for("expenses_recurring"))


@app.route("/expenses/search")
def expenses_search():
    if "user_id" not in session:
        return redirect(url_for("login"))

    raw_q = request.args.get("q", "").strip()
    raw_category = request.args.get("category", "").strip()
    raw_min_amount = request.args.get("min_amount", "").strip()
    raw_max_amount = request.args.get("max_amount", "").strip()
    raw_start_date = request.args.get("start_date", "").strip()
    raw_end_date = request.args.get("end_date", "").strip()

    filters_applied = any([
        raw_q, raw_category, raw_min_amount, raw_max_amount,
        raw_start_date, raw_end_date,
    ])

    def render(error=None, results=None):
        return render_template(
            "expenses_search.html",
            categories=CATEGORIES,
            error=error,
            filters_applied=filters_applied,
            results=results,
            q=raw_q, category=raw_category,
            min_amount=raw_min_amount, max_amount=raw_max_amount,
            start_date=raw_start_date, end_date=raw_end_date,
        )

    if not filters_applied:
        return render()

    min_amount_value, min_amount_error = _validate_amount_bound(
        raw_min_amount, "Minimum amount must be a non-negative number."
    )
    if min_amount_error:
        return render(error=min_amount_error)

    max_amount_value, max_amount_error = _validate_amount_bound(
        raw_max_amount, "Maximum amount must be a non-negative number."
    )
    if max_amount_error:
        return render(error=max_amount_error)

    if (
        min_amount_value is not None
        and max_amount_value is not None
        and min_amount_value > max_amount_value
    ):
        return render(error="Minimum amount can't be greater than maximum amount.")

    # Invalid category values (only reachable via URL tampering, since the
    # form field is a <select>) are silently dropped rather than errored —
    # same convention _parse_date_range already uses for a bad date range
    # on this same style of GET-querystring filter.
    category = raw_category if raw_category in CATEGORIES else None
    start_date, end_date = _parse_date_range(raw_start_date, raw_end_date)

    matches = search_user_expenses(
        session["user_id"],
        q=raw_q or None,
        category=category,
        min_amount=min_amount_value,
        max_amount=max_amount_value,
        start_date=start_date,
        end_date=end_date,
    )
    return render(results=_format_expenses_for_display(matches))


# ------------------------------------------------------------------ #
# Profile management routes                                          #
# ------------------------------------------------------------------ #

# --- /profile/edit (Subagent 1) ---
@app.route("/profile/edit", methods=["GET", "POST"])
def profile_edit():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = get_user_by_id(session["user_id"])

    if request.method == "GET":
        return render_template("profile_edit.html", name=user["name"], email=user["email"])

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()

    if not name or not email:
        return render_template(
            "profile_edit.html", error="All fields are required.",
            name=name, email=email,
        )

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return render_template(
            "profile_edit.html", error="Please enter a valid email address.",
            name=name, email=email,
        )

    try:
        update_user(session["user_id"], name, email)
    except sqlite3.IntegrityError:
        return render_template(
            "profile_edit.html", error="That email is already in use by another account.",
            name=name, email=email,
        )

    return redirect(url_for("profile"))

# --- /profile/change-password (Subagent 2) ---
@app.route("/profile/change-password", methods=["GET", "POST"])
def profile_change_password():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template("profile_change_password.html")

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not current_password or not new_password or not confirm_password:
        return render_template(
            "profile_change_password.html", error="All fields are required.",
        )

    user = get_user_by_id(session["user_id"])
    if not check_password_hash(user["password_hash"], current_password):
        return render_template(
            "profile_change_password.html", error="Current password is incorrect.",
        )

    if len(new_password) < 8:
        return render_template(
            "profile_change_password.html", error="New password must be at least 8 characters.",
        )

    if new_password != confirm_password:
        return render_template(
            "profile_change_password.html", error="New password and confirmation do not match.",
        )

    update_user_password(session["user_id"], generate_password_hash(new_password))
    return redirect(url_for("profile"))

# --- /profile/delete (Subagent 3) ---
@app.route("/profile/delete", methods=["POST"])
def profile_delete():
    if "user_id" not in session:
        return redirect(url_for("login"))

    delete_user(session["user_id"])
    session.pop("user_id", None)
    return redirect(url_for("landing"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
