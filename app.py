import math
import os
import re
import sqlite3
from datetime import datetime

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import (
    CATEGORIES,
    create_expense,
    create_user,
    delete_user,
    get_category_breakdown,
    get_db,
    get_user_by_email,
    get_user_by_id,
    get_user_expense_summary,
    get_user_expenses,
    init_db,
    seed_db,
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
    recent_expenses = [
        {
            "date": datetime.strptime(e["date"], "%Y-%m-%d").strftime("%d %b %Y"),
            "description": e["description"] or "",
            "category": e["category"],
            "amount": e["amount"],
        }
        for e in recent_expenses
    ]
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


def _parse_date_range(start_date, end_date):
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
        end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
    except ValueError:
        return None, None

    if start and end and start > end:
        return None, None

    return start_date or None, end_date or None


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

    if not amount:
        return render_error("Amount is required.")

    try:
        amount_value = float(amount)
    except ValueError:
        return render_error("Amount must be a valid number.")

    if not math.isfinite(amount_value) or amount_value <= 0:
        return render_error("Amount must be a positive number.")

    if category not in CATEGORIES:
        return render_error("Please select a valid category.")

    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return render_error("Please enter a valid date.")

    try:
        # expenses.user_id has a FOREIGN KEY constraint; defensive guard in
        # case the session's user was deleted in another tab mid-request.
        create_expense(session["user_id"], amount_value, category, date, description)
    except sqlite3.IntegrityError:
        return render_error("Could not save expense. Please try again.")

    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


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
