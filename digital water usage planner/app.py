from flask import Flask, render_template, request, redirect, url_for, session , flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta

app = Flask(__name__)

app.secret_key = "digital-water-planner-secret-key"

def get_db():
    connection = sqlite3.connect("database.db")
    connection.row_factory = sqlite3.Row
    return connection

def create_database():
    connection = get_db()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS water_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            usage_liters REAL NOT NULL,
            usage_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS water_limits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            daily_limit REAL NOT NULL DEFAULT 150,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    connection.commit()
    connection.close()


create_database()

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        connection = get_db()

        user = connection.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        connection.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]

            return redirect(url_for("dashboard"))

        flash("Invalid email or password")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            flash("Passwords do not match")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("Password must be at least 6 characters")
            return redirect(url_for("register"))

        connection = get_db()

        try:
            connection.execute(
                "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password))
            )

            connection.commit()

        except sqlite3.IntegrityError:
            connection.close()
            flash("Email already registered")
            return redirect(url_for("register"))

        connection.close()

        flash("Account created! Please login.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out")
    return redirect(url_for("home"))

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db()

    # Today's water usage
    today_usage = connection.execute(
        """
        SELECT COALESCE(SUM(usage_liters), 0)
        FROM water_usage
        WHERE user_id = ?
        AND usage_date = DATE('now')
        """,
        (session["user_id"],)
    ).fetchone()[0]

    # Last 7 days water usage
    weekly_usage = connection.execute(
        """
        SELECT COALESCE(SUM(usage_liters), 0)
        FROM water_usage
        WHERE user_id = ?
        AND usage_date >= DATE('now', '-6 days')
        """,
        (session["user_id"],)
    ).fetchone()[0]

    # Get user's daily water limit
    limit = connection.execute(
        """
        SELECT daily_limit
        FROM water_limits
        WHERE user_id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    daily_limit = limit["daily_limit"] if limit else 150

    # Last 7 days breakdown for the chart
    daily_rows = connection.execute(
        """
        SELECT usage_date, SUM(usage_liters) AS total
        FROM water_usage
        WHERE user_id = ?
        AND usage_date >= DATE('now', '-6 days')
        GROUP BY usage_date
        ORDER BY usage_date
        """,
        (session["user_id"],)
    ).fetchall()

    connection.close()

    # Build a full 7-day series (fill missing days with 0)
    usage_by_date = {row["usage_date"]: row["total"] for row in daily_rows}
    chart_labels = []
    chart_data = []
    for offset in range(-6, 1):
        d = date.today() + timedelta(days=offset)
        d_str = d.isoformat()
        chart_labels.append(d.strftime("%a"))
        chart_data.append(usage_by_date.get(d_str, 0))

    # Monthly total
    monthly_usage = sum(chart_data)

    goal_percent = round((today_usage / daily_limit) * 100) if daily_limit else 0
    goal_percent = min(goal_percent, 100)

    water_score = max(0, min(100, 100 - round((today_usage / daily_limit) * 100))) if daily_limit else 100

    return render_template(
        "dashboard.html",
        today_usage=today_usage,
        weekly_usage=weekly_usage,
        monthly_usage=monthly_usage,
        daily_limit=daily_limit,
        goal_percent=goal_percent,
        water_score=water_score,
        chart_labels=chart_labels,
        chart_data=chart_data
    )
@app.route("/add-usage", methods=["GET", "POST"])
def add_usage():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":

        usage_liters = request.form["usage_liters"]

        connection = get_db()

        connection.execute(
            """
            INSERT INTO water_usage
            (user_id, usage_liters, usage_date)
            VALUES (?, ?, DATE('now'))
            """,
            (session["user_id"], usage_liters)
        )

        connection.commit()
        connection.close()

        return redirect(url_for("dashboard"))

    return render_template("add_usage.html")

@app.route("/set-limit", methods=["GET", "POST"])
def set_limit():

    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db()

    if request.method == "POST":

        daily_limit = request.form["daily_limit"]

        existing = connection.execute(
            "SELECT id FROM water_limits WHERE user_id = ?",
            (session["user_id"],)
        ).fetchone()

        if existing:
            connection.execute(
                """
                UPDATE water_limits
                SET daily_limit = ?
                WHERE user_id = ?
                """,
                (daily_limit, session["user_id"])
            )
        else:
            connection.execute(
                """
                INSERT INTO water_limits
                (user_id, daily_limit)
                VALUES (?, ?)
                """,
                (session["user_id"], daily_limit)
            )

        connection.commit()
        connection.close()

        return redirect(url_for("dashboard"))

    limit = connection.execute(
        "SELECT daily_limit FROM water_limits WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()

    connection.close()

    daily_limit = limit["daily_limit"] if limit else 150

    return render_template(
        "set_limit.html",
        daily_limit=daily_limit
    )


@app.route("/reports")
def reports():

    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db()

    # Last 30 days, day by day
    daily = connection.execute(
        """
        SELECT usage_date, SUM(usage_liters) AS total, COUNT(*) AS entries
        FROM water_usage
        WHERE user_id = ?
        AND usage_date >= DATE('now', '-29 days')
        GROUP BY usage_date
        ORDER BY usage_date DESC
        """,
        (session["user_id"],)
    ).fetchall()

    # Weekly totals (last 8 weeks)
    weekly = connection.execute(
        """
        SELECT strftime('%Y-W%W', usage_date) AS week,
               SUM(usage_liters) AS total
        FROM water_usage
        WHERE user_id = ?
        AND usage_date >= DATE('now', '-55 days')
        GROUP BY week
        ORDER BY week DESC
        """,
        (session["user_id"],)
    ).fetchall()

    stats = connection.execute(
        """
        SELECT COUNT(*) AS entries,
               COALESCE(SUM(usage_liters), 0) AS total,
               COALESCE(AVG(usage_liters), 0) AS average,
               COALESCE(MAX(usage_liters), 0) AS highest
        FROM water_usage
        WHERE user_id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    limit = connection.execute(
        "SELECT daily_limit FROM water_limits WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()

    connection.close()

    daily_limit = limit["daily_limit"] if limit else 150

    days_over_limit = sum(1 for row in daily if row["total"] > daily_limit)

    return render_template(
        "reports.html",
        daily=daily,
        weekly=weekly,
        stats=stats,
        daily_limit=daily_limit,
        days_over_limit=days_over_limit
    )


WATER_TIPS = [
    {"icon": "🚿", "title": "Shorter Showers", "text": "Cutting your shower by just 2 minutes can save up to 40 liters of water each time."},
    {"icon": "🚰", "title": "Fix Leaks Fast", "text": "A dripping tap can waste over 20 liters per day. Fix leaks as soon as you notice them."},
    {"icon": "🪥", "title": "Turn Off the Tap", "text": "Turn off the tap while brushing your teeth — this alone saves around 6 liters per minute."},
    {"icon": "🌀", "title": "Full Loads Only", "text": "Run dishwashers and washing machines only with full loads to maximize every liter used."},
    {"icon": "🌱", "title": "Water Plants Early", "text": "Water your plants in the early morning to reduce evaporation and use up to 30% less water."},
    {"icon": "🚽", "title": "Dual Flush", "text": "A dual-flush toilet can save up to 40,000 liters per year for a family of four."},
    {"icon": "🥛", "title": "Reuse Where Possible", "text": "Use leftover drinking water for houseplants instead of pouring it down the drain."},
    {"icon": "🛁", "title": "Prefer Showers", "text": "A 5-minute shower uses about half the water of a full bathtub. Choose showers more often."},
    {"icon": "🧺", "title": "Cold Wash Cycles", "text": "Washing clothes in cold water not only saves energy — efficient loads also save water."},
]


@app.route("/tips")
def tips():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("tips.html", tips=WATER_TIPS)
 
 
if __name__ == "__main__": 
    app.run(debug=True)    