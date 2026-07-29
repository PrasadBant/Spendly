import os
import re
import sqlite3

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import (
    create_user,
    get_db,
    get_user_by_email,
    get_user_by_id,
    get_user_expense_summary,
    init_db,
    seed_db,
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

    user = get_user_by_id(session["user_id"])
    summary = get_user_expense_summary(session["user_id"])

    return render_template("profile.html", user=user, summary=summary)


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
