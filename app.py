# ============================================================
# MKOLANI POS - COMPLETE STABLE VERSION
# Flask + SQLite
# Render / Gunicorn Ready
# ============================================================

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify
)

import sqlite3
import os
import requests
import threading
import random
import secrets
from datetime import datetime, timedelta
from functools import wraps

from werkzeug.security import generate_password_hash, check_password_hash


# ============================================================
# APP CONFIGURATION
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "mkolani-pos-change-this-secret-key"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(BASE_DIR, "pos.db")

UPLOAD_FOLDER = os.path.join(
    BASE_DIR,
    "static",
    "uploads"
)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")

    return conn


def column_exists(conn, table_name, column_name):
    try:
        columns = conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()

        return any(
            row["name"] == column_name
            for row in columns
        )

    except Exception:
        return False


def add_column_if_missing(
    conn,
    table_name,
    column_name,
    column_definition
):
    if not column_exists(
        conn,
        table_name,
        column_name
    ):
        try:
            conn.execute(
                f"""
                ALTER TABLE {table_name}
                ADD COLUMN {column_name}
                {column_definition}
                """
            )
        except Exception:
            pass


def init_db():

    conn = get_db()

    # ========================================================
    # USERS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'Staff',
            is_admin INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            business_name TEXT DEFAULT 'Mkolani Stationery',
            phone TEXT,
            master_pin TEXT,
            reset_token TEXT,
            reset_expires TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ========================================================
    # SYSTEM SETTINGS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_key TEXT UNIQUE,
            setting_value TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ========================================================
    # RECEIPTS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            receipt_no TEXT UNIQUE,
            customer_name TEXT,
            customer_phone TEXT,
            items TEXT,
            amount REAL DEFAULT 0,
            discount REAL DEFAULT 0,
            paid REAL DEFAULT 0,
            debt REAL DEFAULT 0,
            cash_received REAL DEFAULT 0,
            change_amount REAL DEFAULT 0,
            cost REAL DEFAULT 0,
            profit REAL DEFAULT 0,
            payment_method TEXT DEFAULT 'Cash',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id)
                REFERENCES users(id)
                ON DELETE SET NULL
        )
    """)

    # ========================================================
    # PRODUCTS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            sku TEXT,
            category TEXT,
            unit TEXT DEFAULT 'pcs',
            buying_price REAL DEFAULT 0,
            selling_price REAL DEFAULT 0,
            quantity REAL DEFAULT 0,
            min_stock REAL DEFAULT 5,
            supplier TEXT,
            description TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id)
                REFERENCES users(id)
                ON DELETE SET NULL
        )
    """)

    # ========================================================
    # CUSTOMERS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            address TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id)
                REFERENCES users(id)
                ON DELETE SET NULL
        )
    """)

    # ========================================================
    # DEBTS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            customer_id INTEGER,
            customer_name TEXT,
            customer_phone TEXT,
            receipt_id INTEGER,
            amount REAL DEFAULT 0,
            paid REAL DEFAULT 0,
            balance REAL DEFAULT 0,
            status TEXT DEFAULT 'Pending',
            due_date TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id)
                REFERENCES users(id)
                ON DELETE SET NULL,
            FOREIGN KEY(customer_id)
                REFERENCES customers(id)
                ON DELETE SET NULL
        )
    """)

    # ========================================================
    # DEBT PAYMENTS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS debt_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            debt_id INTEGER,
            user_id INTEGER,
            amount REAL DEFAULT 0,
            payment_method TEXT DEFAULT 'Cash',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(debt_id)
                REFERENCES debts(id)
                ON DELETE CASCADE,
            FOREIGN KEY(user_id)
                REFERENCES users(id)
                ON DELETE SET NULL
        )
    """)

    # ========================================================
    # EXPENSES
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT NOT NULL,
            category TEXT,
            amount REAL DEFAULT 0,
            description TEXT,
            expense_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id)
                REFERENCES users(id)
                ON DELETE SET NULL
        )
    """)

    # ========================================================
    # SMS LOGS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sms_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            phone TEXT,
            message TEXT,
            status TEXT,
            response TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id)
                REFERENCES users(id)
                ON DELETE SET NULL
        )
    """)

    # ========================================================
    # AUDIT LOGS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            ip_address TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id)
                REFERENCES users(id)
                ON DELETE SET NULL
        )
    """)

    # ========================================================
    # NOTIFICATIONS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            message TEXT,
            notification_type TEXT DEFAULT 'info',
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
    """)

    # ========================================================
    # BACKWARD COMPATIBILITY / MIGRATIONS
    # ========================================================

    user_columns = {
        "name": "TEXT",
        "role": "TEXT DEFAULT 'Staff'",
        "is_admin": "INTEGER DEFAULT 0",
        "is_active": "INTEGER DEFAULT 1",
        "business_name": "TEXT DEFAULT 'Mkolani Stationery'",
        "phone": "TEXT",
        "master_pin": "TEXT",
        "reset_token": "TEXT",
        "reset_expires": "TEXT",
        "created_at": "TEXT"
    }

    for col, definition in user_columns.items():
        add_column_if_missing(
            conn,
            "users",
            col,
            definition
        )

    product_columns = {
        "user_id": "INTEGER",
        "sku": "TEXT",
        "category": "TEXT",
        "unit": "TEXT DEFAULT 'pcs'",
        "buying_price": "REAL DEFAULT 0",
        "selling_price": "REAL DEFAULT 0",
        "quantity": "REAL DEFAULT 0",
        "min_stock": "REAL DEFAULT 5",
        "supplier": "TEXT",
        "description": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT"
    }

    for col, definition in product_columns.items():
        add_column_if_missing(
            conn,
            "products",
            col,
            definition
        )

    receipt_columns = {
        "user_id": "INTEGER",
        "receipt_no": "TEXT",
        "customer_name": "TEXT",
        "customer_phone": "TEXT",
        "items": "TEXT",
        "amount": "REAL DEFAULT 0",
        "discount": "REAL DEFAULT 0",
        "paid": "REAL DEFAULT 0",
        "debt": "REAL DEFAULT 0",
        "cash_received": "REAL DEFAULT 0",
        "change_amount": "REAL DEFAULT 0",
        "cost": "REAL DEFAULT 0",
        "profit": "REAL DEFAULT 0",
        "payment_method": "TEXT DEFAULT 'Cash'",
        "notes": "TEXT",
        "created_at": "TEXT"
    }

    for col, definition in receipt_columns.items():
        add_column_if_missing(
            conn,
            "receipts",
            col,
            definition
        )

    conn.commit()

    # ========================================================
    # DEFAULT SETTINGS
    # ========================================================

    default_settings = {
        "app_name": "Mkolani POS",
        "business_name": "Mkolani Stationery",
        "currency": "TZS",
        "low_stock_limit": "5",
        "sms_enabled": "0",
        "beem_api_key": "",
        "beem_secret": "",
        "beem_sender": "Mkolani"
    }

    for key, value in default_settings.items():

        existing = conn.execute(
            """
            SELECT id
            FROM system_settings
            WHERE setting_key = ?
            """,
            (key,)
        ).fetchone()

        if not existing:
            conn.execute(
                """
                INSERT INTO system_settings
                (setting_key, setting_value)
                VALUES (?, ?)
                """,
                (key, value)
            )

    # ========================================================
    # MAKE FIRST USER MASTER
    # ========================================================

    first_user = conn.execute(
        """
        SELECT id
        FROM users
        ORDER BY id ASC
        LIMIT 1
        """
    ).fetchone()

    if first_user:

        conn.execute(
            """
            UPDATE users
            SET role = 'Master',
                is_admin = 1
            WHERE id = ?
            """,
            (first_user["id"],)
        )

    conn.commit()
    conn.close()


# Initialize DB immediately
init_db()


# ============================================================
# HELPERS
# ============================================================

def get_current_user():

    user_id = session.get("user_id")

    if not user_id:
        return None

    conn = get_db()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    conn.close()

    if not user:
        session.clear()
        return None

    return user


def money(value):

    try:
        value = float(value or 0)
    except Exception:
        value = 0

    return f"{value:,.0f}"


def get_setting(key, default=""):

    conn = get_db()

    row = conn.execute(
        """
        SELECT setting_value
        FROM system_settings
        WHERE setting_key = ?
        """,
        (key,)
    ).fetchone()

    conn.close()

    if row and row["setting_value"] is not None:
        return row["setting_value"]

    return default


def set_setting(key, value):

    conn = get_db()

    conn.execute(
        """
        INSERT INTO system_settings
        (setting_key, setting_value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(setting_key)
        DO UPDATE SET
            setting_value = excluded.setting_value,
            updated_at = CURRENT_TIMESTAMP
        """,
        (key, str(value))
    )

    conn.commit()
    conn.close()


def normalize_phone(phone):

    if not phone:
        return ""

    phone = str(phone).strip()

    phone = phone.replace(
        " ",
        ""
    )

    phone = phone.replace(
        "-",
        ""
    )

    if phone.startswith("+255"):
        return phone

    if phone.startswith("255"):
        return "+" + phone

    if phone.startswith("0"):
        return "+255" + phone[1:]

    return phone


def make_receipt_number():

    prefix = "MK"

    date_part = datetime.now().strftime(
        "%Y%m%d"
    )

    random_part = str(
        random.randint(
            1000,
            9999
        )
    )

    return f"{prefix}-{date_part}-{random_part}"


def log_action(
    user_id,
    action,
    details=""
):

    try:

        conn = get_db()

        ip = request.remote_addr

        conn.execute(
            """
            INSERT INTO audit_logs
            (
                user_id,
                action,
                details,
                ip_address
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                action,
                details,
                ip
            )
        )

        conn.commit()
        conn.close()

    except Exception:
        pass


def add_notification(
    user_id,
    title,
    message,
    notification_type="info"
):

    try:

        conn = get_db()

        conn.execute(
            """
            INSERT INTO notifications
            (
                user_id,
                title,
                message,
                notification_type
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                title,
                message,
                notification_type
            )
        )

        conn.commit()
        conn.close()

    except Exception:
        pass


# ============================================================
# DASHBOARD DATA
# ============================================================

def get_dashboard_data(user_id):

    conn = get_db()

    today = datetime.now().strftime(
        "%Y-%m-%d"
    )

    month = datetime.now().strftime(
        "%Y-%m"
    )

    # --------------------------------------------------------
    # TODAY SALES
    # --------------------------------------------------------

    today_sales_row = conn.execute(
        """
        SELECT
            COALESCE(SUM(amount - discount), 0) AS total,
            COUNT(*) AS count
        FROM receipts
        WHERE user_id = ?
        AND substr(created_at, 1, 10) = ?
        """,
        (
            user_id,
            today
        )
    ).fetchone()

    today_sales = float(
        today_sales_row["total"] or 0
    )

    today_transactions = int(
        today_sales_row["count"] or 0
    )

    # --------------------------------------------------------
    # MONTH SALES
    # --------------------------------------------------------

    month_sales_row = conn.execute(
        """
        SELECT
            COALESCE(SUM(amount - discount), 0) AS total
        FROM receipts
        WHERE user_id = ?
        AND substr(created_at, 1, 7) = ?
        """,
        (
            user_id,
            month
        )
    ).fetchone()

    month_sales = float(
        month_sales_row["total"] or 0
    )

    # --------------------------------------------------------
    # PROFIT
    # --------------------------------------------------------

    profit_row = conn.execute(
        """
        SELECT
            COALESCE(SUM(profit), 0) AS profit
        FROM receipts
        WHERE user_id = ?
        AND substr(created_at, 1, 10) = ?
        """,
        (
            user_id,
            today
        )
    ).fetchone()

    today_profit = float(
        profit_row["profit"] or 0
    )

    # --------------------------------------------------------
    # EXPENSES
    # --------------------------------------------------------

    expense_row = conn.execute(
        """
        SELECT
            COALESCE(SUM(amount), 0) AS total
        FROM expenses
        WHERE user_id = ?
        AND substr(
            COALESCE(expense_date, created_at),
            1,
            10
        ) = ?
        """,
        (
            user_id,
            today
        )
    ).fetchone()

    today_expenses = float(
        expense_row["total"] or 0
    )

    # --------------------------------------------------------
    # PRODUCTS
    # --------------------------------------------------------

    product_count_row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM products
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    product_count = int(
        product_count_row["count"] or 0
    )

    # --------------------------------------------------------
    # CUSTOMERS
    # --------------------------------------------------------

    customer_count_row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM customers
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    customer_count = int(
        customer_count_row["count"] or 0
    )

    # --------------------------------------------------------
    # DEBT
    # --------------------------------------------------------

    debt_row = conn.execute(
        """
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN balance > 0
                        THEN balance
                        ELSE 0
                    END
                ),
                0
            ) AS total
        FROM debts
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    total_debt = float(
        debt_row["total"] or 0
    )

    # --------------------------------------------------------
    # LOW STOCK
    # --------------------------------------------------------

    low_stock = conn.execute(
        """
        SELECT *
        FROM products
        WHERE user_id = ?
        AND quantity <= min_stock
        ORDER BY quantity ASC
        LIMIT 20
        """,
        (user_id,)
    ).fetchall()

    # --------------------------------------------------------
    # RECENT SALES
    # --------------------------------------------------------

    recent_sales = conn.execute(
        """
        SELECT *
        FROM receipts
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 10
        """,
        (user_id,)
    ).fetchall()

    # --------------------------------------------------------
    # NOTIFICATIONS
    # --------------------------------------------------------

    notifications = conn.execute(
        """
        SELECT *
        FROM notifications
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 10
        """,
        (user_id,)
    ).fetchall()

    unread_notifications = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM notifications
        WHERE user_id = ?
        AND is_read = 0
        """,
        (user_id,)
    ).fetchone()["count"]

    conn.close()

    stats = {
        "today_sales": today_sales,
        "today_transactions": today_transactions,
        "month_sales": month_sales,
        "today_profit": today_profit,
        "today_expenses": today_expenses,
        "products": product_count,
        "customers": customer_count,
        "total_debt": total_debt,
        "unread_notifications": unread_notifications
    }

    return {
        "stats": stats,
        "sales_stats": stats,
        "recent_sales": recent_sales,
        "receipts": recent_sales,
        "low_stock": low_stock,
        "notifications": notifications
    }


# ============================================================
# TEMPLATE GLOBALS
# ============================================================

@app.context_processor
def inject_globals():

    user = get_current_user()

    return {
        "app_name": get_setting(
            "app_name",
            "Mkolani POS"
        ),

        "business_name": get_setting(
            "business_name",
            "Mkolani Stationery"
        ),

        "system_currency": get_setting(
            "currency",
            "TZS"
        ),

        # IMPORTANT FIX:
        # Templates such as user.html use current_user
        "current_user": user,

        # Compatibility with old templates
        "current_user_obj": user,

        "money": money,

        "now": datetime.now
    }


# ============================================================
# AUTH DECORATORS
# ============================================================

def login_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        user = get_current_user()

        if not user:
            flash(
                "Tafadhali ingia kwanza.",
                "warning"
            )

            return redirect(
                url_for("login")
            )

        if not user["is_active"]:
            session.clear()

            flash(
                "Akaunti yako imezuiwa.",
                "danger"
            )

            return redirect(
                url_for("login")
            )

        return func(*args, **kwargs)

    return wrapper


def roles_required(*roles):

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):

            user = get_current_user()

            if not user:
                return redirect(
                    url_for("login")
                )

            if user["role"] not in roles:

                flash(
                    "Huna ruhusa ya kufanya kitendo hiki.",
                    "danger"
                )

                return redirect(
                    url_for("dashboard")
                )

            return func(
                *args,
                **kwargs
            )

        return wrapper

    return decorator


def master_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        user = get_current_user()

        if not user:
            return redirect(
                url_for("login")
            )

        if (
            user["role"] != "Master"
            and not user["is_admin"]
        ):

            flash(
                "Master/Admin pekee ndiye anaweza kufungua ukurasa huu.",
                "danger"
            )

            return redirect(
                url_for("dashboard")
            )

        return func(
            *args,
            **kwargs
        )

    return wrapper


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/",
    methods=["GET", "POST"]
)
@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = (
            request.form.get(
                "email",
                ""
            )
            .strip()
            .lower()
        )

        password = request.form.get(
            "password",
            ""
        )

        if not email or not password:

            flash(
                "Weka email na password.",
                "warning"
            )

            return render_template(
                "login.html"
            )

        conn = get_db()

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE lower(email) = ?
            LIMIT 1
            """,
            (email,)
        ).fetchone()

        conn.close()

        if not user:

            flash(
                "Email au password si sahihi.",
                "danger"
            )

            return render_template(
                "login.html"
            )

        if not user["is_active"]:

            flash(
                "Akaunti yako imezuiwa.",
                "danger"
            )

            return render_template(
                "login.html"
            )

        valid_password = False

        stored_password = user["password"] or ""

        try:

            valid_password = check_password_hash(
                stored_password,
                password
            )

        except Exception:

            valid_password = (
                stored_password == password
            )

        # ----------------------------------------------------
        # Legacy plain password migration
        # ----------------------------------------------------

        if valid_password:

            pass

        elif stored_password == password:

            valid_password = True

            conn = get_db()

            conn.execute(
                """
                UPDATE users
                SET password = ?
                WHERE id = ?
                """,
                (
                    generate_password_hash(
                        password
                    ),
                    user["id"]
                )
            )

            conn.commit()
            conn.close()

        if not valid_password:

            flash(
                "Email au password si sahihi.",
                "danger"
            )

            return render_template(
                "login.html"
            )

        session.clear()

        session["user_id"] = user["id"]

        session["role"] = user["role"]

        session.permanent = True

        log_action(
            user["id"],
            "LOGIN",
            "User logged in"
        )

        return redirect(
            url_for("dashboard")
        )

    user = get_current_user()

    if user:

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "login.html"
    )


# ============================================================
# REGISTER
# ============================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = (
            request.form.get(
                "email",
                ""
            )
            .strip()
            .lower()
        )

        password = request.form.get(
            "password",
            ""
        )

        business_name = request.form.get(
            "business_name",
            "Mkolani Stationery"
        ).strip()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        if not name:
            flash(
                "Jina linahitajika.",
                "warning"
            )

            return render_template(
                "register.html"
            )

        if not email:
            flash(
                "Email inahitajika.",
                "warning"
            )

            return render_template(
                "register.html"
            )

        if len(password) < 4:

            flash(
                "Password iwe na angalau characters 4.",
                "warning"
            )

            return render_template(
                "register.html"
            )

        conn = get_db()

        existing = conn.execute(
            """
            SELECT id
            FROM users
            WHERE lower(email) = ?
            """,
            (email,)
        ).fetchone()

        if existing:

            conn.close()

            flash(
                "Email hiyo tayari imesajiliwa.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM users
            """
        ).fetchone()["count"]

        if count == 0:
            role = "Master"
            is_admin = 1
        else:
            role = "Staff"
            is_admin = 0

        conn.execute(
            """
            INSERT INTO users
            (
                name,
                email,
                password,
                role,
                is_admin,
                is_active,
                business_name,
                phone
            )
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                name,
                email,
                generate_password_hash(password),
                role,
                is_admin,
                business_name or "Mkolani Stationery",
                phone
            )
        )

        conn.commit()

        conn.close()

        flash(
            "Usajili umefanikiwa. Sasa ingia.",
            "success"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "register.html"
    )


# ============================================================
# FORGOT PASSWORD
# ============================================================

@app.route(
    "/forgot-password",
    methods=["GET", "POST"]
)
def forgot_password():

    if request.method == "POST":

        email = (
            request.form.get(
                "email",
                ""
            )
            .strip()
            .lower()
        )

        conn = get_db()

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE lower(email) = ?
            """,
            (email,)
        ).fetchone()

        if user:

            token = secrets.token_urlsafe(
                32
            )

            expires = (
                datetime.now()
                + timedelta(minutes=30)
            ).isoformat()

            conn.execute(
                """
                UPDATE users
                SET reset_token = ?,
                    reset_expires = ?
                WHERE id = ?
                """,
                (
                    token,
                    expires,
                    user["id"]
                )
            )

            conn.commit()

            conn.close()

            reset_link = url_for(
                "reset_password",
                token=token,
                _external=True
            )

            flash(
                f"Link ya kubadilisha password: {reset_link}",
                "info"
            )

        else:

            conn.close()

            flash(
                "Kama email ipo kwenye mfumo, utaratibu wa reset umeanzishwa.",
                "info"
            )

        return redirect(
            url_for("forgot_password")
        )

    return render_template(
        "forgot_password.html"
    )


# ============================================================
# RESET PASSWORD
# ============================================================

@app.route(
    "/reset-password/<token>",
    methods=["GET", "POST"]
)
def reset_password(token):

    conn = get_db()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE reset_token = ?
        """,
        (token,)
    ).fetchone()

    if not user:

        conn.close()

        flash(
            "Reset link si sahihi au imekwisha.",
            "danger"
        )

        return redirect(
            url_for("login")
        )

    try:

        expires = datetime.fromisoformat(
            user["reset_expires"]
        )

    except Exception:

        expires = datetime.min

    if datetime.now() > expires:

        conn.close()

        flash(
            "Reset link imekwisha muda.",
            "danger"
        )

        return redirect(
            url_for("forgot_password")
        )

    if request.method == "POST":

        password = request.form.get(
            "password",
            ""
        )

        confirm = request.form.get(
            "confirm_password",
            password
        )

        if len(password) < 4:

            conn.close()

            flash(
                "Password iwe na angalau characters 4.",
                "warning"
            )

            return render_template(
                "reset_password.html",
                token=token
            )

        if password != confirm:

            conn.close()

            flash(
                "Passwords hazifanani.",
                "warning"
            )

            return render_template(
                "reset_password.html",
                token=token
            )

        conn.execute(
            """
            UPDATE users
            SET password = ?,
                reset_token = NULL,
                reset_expires = NULL
            WHERE id = ?
            """,
            (
                generate_password_hash(password),
                user["id"]
            )
        )

        conn.commit()

        conn.close()

        flash(
            "Password imebadilishwa. Sasa unaweza kuingia.",
            "success"
        )

        return redirect(
            url_for("login")
        )

    conn.close()

    return render_template(
        "reset_password.html",
        token=token
    )


# ============================================================
# CHANGE PASSWORD
# ============================================================

@app.route(
    "/change-password",
    methods=["GET", "POST"]
)
@login_required
def change_password():

    user = get_current_user()

    if request.method == "POST":

        old_password = request.form.get(
            "old_password",
            ""
        )

        new_password = request.form.get(
            "new_password",
            ""
        )

        confirm = request.form.get(
            "confirm_password",
            ""
        )

        valid = False

        try:

            valid = check_password_hash(
                user["password"],
                old_password
            )

        except Exception:

            valid = (
                user["password"] == old_password
            )

        if not valid:

            flash(
                "Password ya zamani si sahihi.",
                "danger"
            )

            return render_template(
                "change_password.html"
            )

        if len(new_password) < 4:

            flash(
                "Password mpya iwe na angalau characters 4.",
                "warning"
            )

            return render_template(
                "change_password.html"
            )

        if new_password != confirm:

            flash(
                "Password mpya hazifanani.",
                "warning"
            )

            return render_template(
                "change_password.html"
            )

        conn = get_db()

        conn.execute(
            """
            UPDATE users
            SET password = ?
            WHERE id = ?
            """,
            (
                generate_password_hash(
                    new_password
                ),
                user["id"]
            )
        )

        conn.commit()
        conn.close()

        log_action(
            user["id"],
            "CHANGE_PASSWORD",
            "Password changed"
        )

        flash(
            "Password imebadilishwa.",
            "success"
        )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "change_password.html"
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
@app.route("/home")
@login_required
def dashboard():

    user = get_current_user()

    data = get_dashboard_data(
        user["id"]
    )

    # IMPORTANT:
    # current_user is explicitly passed too.
    # This protects against templates expecting it.

    return render_template(
        "user.html",
        user=user,
        current_user=user,
        **data
    )


# ============================================================
# SALES / POS
# ============================================================

@app.route(
    "/sales",
    methods=["GET", "POST"]
)
@login_required
def sales():

    user = get_current_user()

    if request.method == "POST":

        try:

            customer_name = request.form.get(
                "customer_name",
                ""
            ).strip()

            customer_phone = request.form.get(
                "customer_phone",
                ""
            ).strip()

            payment_method = request.form.get(
                "payment_method",
                "Cash"
            )

            notes = request.form.get(
                "notes",
                ""
            ).strip()

            discount = float(
                request.form.get(
                    "discount",
                    0
                ) or 0
            )

            paid = float(
                request.form.get(
                    "paid",
                    0
                ) or 0
            )

            cash_received = float(
                request.form.get(
                    "cash_received",
                    paid
                ) or paid
            )

            # ------------------------------------------------
            # Accept JSON items OR form items
            # ------------------------------------------------

            items = []

            if request.is_json:

                data = request.get_json(
                    silent=True
                ) or {}

                items = data.get(
                    "items",
                    []
                )

                customer_name = data.get(
                    "customer_name",
                    customer_name
                )

                customer_phone = data.get(
                    "customer_phone",
                    customer_phone
                )

                payment_method = data.get(
                    "payment_method",
                    payment_method
                )

                discount = float(
                    data.get(
                        "discount",
                        discount
                    ) or 0
                )

                paid = float(
                    data.get(
                        "paid",
                        paid
                    ) or 0
                )

                cash_received = float(
                    data.get(
                        "cash_received",
                        paid
                    ) or paid
                )

            else:

                raw_items = request.form.get(
                    "items",
                    ""
                )

                if raw_items:

                    import json

                    try:
                        items = json.loads(
                            raw_items
                        )
                    except Exception:
                        items = []

                # ------------------------------------------------
                # Alternative simple product form
                # ------------------------------------------------

                product_id = request.form.get(
                    "product_id"
                )

                quantity = request.form.get(
                    "quantity"
                )

                if product_id and quantity:

                    items = [{
                        "product_id": int(
                            product_id
                        ),
                        "quantity": float(
                            quantity
                        )
                    }]

            if not items:

                flash(
                    "Hakuna bidhaa iliyochaguliwa.",
                    "warning"
                )

                return redirect(
                    url_for("sales")
                )

            conn = get_db()

            processed_items = []

            gross_total = 0

            total_cost = 0

            # ------------------------------------------------
            # Process products
            # ------------------------------------------------

            for item in items:

                product_id = int(
                    item.get(
                        "product_id",
                        item.get(
                            "id",
                            0
                        )
                    )
                )

                quantity = float(
                    item.get(
                        "quantity",
                        item.get(
                            "qty",
                            1
                        )
                    )
                    or 0
                )

                if quantity <= 0:
                    continue

                product = conn.execute(
                    """
                    SELECT *
                    FROM products
                    WHERE id = ?
                    """,
                    (product_id,)
                ).fetchone()

                if not product:

                    conn.close()

                    flash(
                        "Bidhaa haikupatikana.",
                        "danger"
                    )

                    return redirect(
                        url_for("sales")
                    )

                stock = float(
                    product["quantity"] or 0
                )

                if stock < quantity:

                    conn.close()

                    flash(
                        f"Stock ya {product['name']} haitoshi.",
                        "danger"
                    )

                    return redirect(
                        url_for("sales")
                    )

                selling_price = float(
                    item.get(
                        "price",
                        product["selling_price"]
                    )
                    or product["selling_price"]
                    or 0
                )

                buying_price = float(
                    product["buying_price"]
                    or 0
                )

                line_total = (
                    selling_price
                    * quantity
                )

                line_cost = (
                    buying_price
                    * quantity
                )

                gross_total += line_total

                total_cost += line_cost

                processed_items.append({
                    "product_id": product["id"],
                    "name": product["name"],
                    "quantity": quantity,
                    "price": selling_price,
                    "cost": buying_price,
                    "total": line_total
                })

            if not processed_items:

                conn.close()

                flash(
                    "Bidhaa halali hazikupatikana.",
                    "warning"
                )

                return redirect(
                    url_for("sales")
                )

            # ------------------------------------------------
            # Totals
            # ------------------------------------------------

            if discount < 0:
                discount = 0

            if discount > gross_total:
                discount = gross_total

            net_total = (
                gross_total
                - discount
            )

            if paid < 0:
                paid = 0

            if paid > net_total:
                paid = net_total

            debt = (
                net_total
                - paid
            )

            if cash_received < 0:
                cash_received = 0

            change_amount = max(
                0,
                cash_received - paid
            )

            profit = (
                net_total
                - total_cost
            )

            receipt_no = make_receipt_number()

            # ------------------------------------------------
            # Insert receipt
            # ------------------------------------------------

            import json

            items_json = json.dumps(
                processed_items,
                ensure_ascii=False
            )

            conn.execute(
                """
                INSERT INTO receipts
                (
                    user_id,
                    receipt_no,
                    customer_name,
                    customer_phone,
                    items,
                    amount,
                    discount,
                    paid,
                    debt,
                    cash_received,
                    change_amount,
                    cost,
                    profit,
                    payment_method,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    receipt_no,
                    customer_name,
                    customer_phone,
                    items_json,
                    gross_total,
                    discount,
                    paid,
                    debt,
                    cash_received,
                    change_amount,
                    total_cost,
                    profit,
                    payment_method,
                    notes
                )
            )

            receipt_id = conn.execute(
                """
                SELECT last_insert_rowid()
                """
            ).fetchone()[0]

            # ------------------------------------------------
            # Reduce stock
            # ------------------------------------------------

            for item in processed_items:

                conn.execute(
                    """
                    UPDATE products
                    SET quantity = quantity - ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        item["quantity"],
                        item["product_id"]
                    )
                )

            # ------------------------------------------------
            # Customer
            # ------------------------------------------------

            customer_id = None

            if customer_name:

                existing_customer = None

                if customer_phone:

                    existing_customer = conn.execute(
                        """
                        SELECT *
                        FROM customers
                        WHERE user_id = ?
                        AND phone = ?
                        LIMIT 1
                        """,
                        (
                            user["id"],
                            customer_phone
                        )
                    ).fetchone()

                if existing_customer:

                    customer_id = existing_customer["id"]

                else:

                    conn.execute(
                        """
                        INSERT INTO customers
                        (
                            user_id,
                            name,
                            phone
                        )
                        VALUES (?, ?, ?)
                        """,
                        (
                            user["id"],
                            customer_name,
                            customer_phone
                        )
                    )

                    customer_id = conn.execute(
                        """
                        SELECT last_insert_rowid()
                        """
                    ).fetchone()[0]

            # ------------------------------------------------
            # Debt
            # ------------------------------------------------

            if debt > 0:

                conn.execute(
                    """
                    INSERT INTO debts
                    (
                        user_id,
                        customer_id,
                        customer_name,
                        customer_phone,
                        receipt_id,
                        amount,
                        paid,
                        balance,
                        status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user["id"],
                        customer_id,
                        customer_name or "Customer",
                        customer_phone,
                        receipt_id,
                        net_total,
                        paid,
                        debt,
                        "Pending"
                    )
                )

                add_notification(
                    user["id"],
                    "Deni jipya",
                    f"{customer_name or 'Customer'} ana deni la {money(debt)} TZS.",
                    "warning"
                )

            # ------------------------------------------------
            # Low stock notifications
            # ------------------------------------------------

            for item in processed_items:

                p = conn.execute(
                    """
                    SELECT *
                    FROM products
                    WHERE id = ?
                    """,
                    (item["product_id"],)
                ).fetchone()

                if p:

                    if float(
                        p["quantity"] or 0
                    ) <= float(
                        p["min_stock"] or 5
                    ):

                        add_notification(
                            user["id"],
                            "Stock iko chini",
                            f"{p['name']} imebaki {p['quantity']}.",
                            "warning"
                        )

            conn.commit()

            conn.close()

            log_action(
                user["id"],
                "SALE",
                f"Receipt {receipt_no}"
            )

            if request.is_json:

                return jsonify({
                    "success": True,
                    "message": "Mauzo yamehifadhiwa.",
                    "receipt_id": receipt_id,
                    "receipt_no": receipt_no,
                    "total": net_total,
                    "paid": paid,
                    "debt": debt,
                    "change": change_amount,
                    "profit": profit
                })

            flash(
                f"Mauzo yamehifadhiwa. Receipt: {receipt_no}",
                "success"
            )

            return redirect(
                url_for(
                    "receipt",
                    receipt_id=receipt_id
                )
            )

        except Exception as e:

            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass

            if request.is_json:

                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500

            flash(
                f"Hitilafu kwenye mauzo: {str(e)}",
                "danger"
            )

            return redirect(
                url_for("sales")
            )

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    conn = get_db()

    products = conn.execute(
        """
        SELECT *
        FROM products
        WHERE user_id = ?
        ORDER BY name ASC
        """,
        (user["id"],)
    ).fetchall()

    customers = conn.execute(
        """
        SELECT *
        FROM customers
        WHERE user_id = ?
        ORDER BY name ASC
        """,
        (user["id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "sales.html",
        products=products,
        customers=customers
    )


# ============================================================
# SALES API
# ============================================================

@app.route(
    "/api/sales",
    methods=["GET", "POST"]
)
@login_required
def api_sales():

    if request.method == "POST":

        return sales()

    user = get_current_user()

    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM receipts
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 100
        """,
        (user["id"],)
    ).fetchall()

    conn.close()

    return jsonify([
        dict(row)
        for row in rows
    ])


# ============================================================
# PRODUCTS
# ============================================================

@app.route(
    "/products",
    methods=["GET", "POST"]
)
@login_required
def products():

    user = get_current_user()

    conn = get_db()

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        sku = request.form.get(
            "sku",
            ""
        ).strip()

        category = request.form.get(
            "category",
            ""
        ).strip()

        unit = request.form.get(
            "unit",
            "pcs"
        ).strip()

        supplier = request.form.get(
            "supplier",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        try:

            buying_price = float(
                request.form.get(
                    "buying_price",
                    0
                ) or 0
            )

            selling_price = float(
                request.form.get(
                    "selling_price",
                    0
                ) or 0
            )

            quantity = float(
                request.form.get(
                    "quantity",
                    0
                ) or 0
            )

            min_stock = float(
                request.form.get(
                    "min_stock",
                    5
                ) or 5
            )

        except Exception:

            flash(
                "Bei za bidhaa si sahihi.",
                "danger"
            )

            conn.close()

            return redirect(
                url_for("products")
            )

        if not name:

            conn.close()

            flash(
                "Jina la bidhaa linahitajika.",
                "warning"
            )

            return redirect(
                url_for("products")
            )

        conn.execute(
            """
            INSERT INTO products
            (
                user_id,
                name,
                sku,
                category,
                unit,
                buying_price,
                selling_price,
                quantity,
                min_stock,
                supplier,
                description
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                name,
                sku,
                category,
                unit,
                buying_price,
                selling_price,
                quantity,
                min_stock,
                supplier,
                description
            )
        )

        conn.commit()

        conn.close()

        log_action(
            user["id"],
            "ADD_PRODUCT",
            name
        )

        flash(
            "Bidhaa imeongezwa.",
            "success"
        )

        return redirect(
            url_for("products")
        )

    rows = conn.execute(
        """
        SELECT *
        FROM products
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user["id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "products.html",
        products=rows
    )


# ============================================================
# DELETE PRODUCT
# ============================================================

@app.route(
    "/products/delete/<int:product_id>",
    methods=["POST", "GET"]
)
@login_required
def delete_product(product_id):

    user = get_current_user()

    conn = get_db()

    conn.execute(
        """
        DELETE FROM products
        WHERE id = ?
        AND user_id = ?
        """,
        (
            product_id,
            user["id"]
        )
    )

    conn.commit()
    conn.close()

    log_action(
        user["id"],
        "DELETE_PRODUCT",
        str(product_id)
    )

    flash(
        "Bidhaa imefutwa.",
        "success"
    )

    return redirect(
        url_for("products")
    )


# ============================================================
# PRODUCT API
# ============================================================

@app.route(
    "/api/products",
    methods=["GET"]
)
@login_required
def api_products():

    user = get_current_user()

    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM products
        WHERE user_id = ?
        ORDER BY name
        """,
        (user["id"],)
    ).fetchall()

    conn.close()

    return jsonify([
        dict(row)
        for row in rows
    ])


# ============================================================
# CUSTOMERS
# ============================================================

@app.route(
    "/customers",
    methods=["GET", "POST"]
)
@login_required
def customers():

    user = get_current_user()

    conn = get_db()

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip()

        address = request.form.get(
            "address",
            ""
        ).strip()

        notes = request.form.get(
            "notes",
            ""
        ).strip()

        if not name:

            conn.close()

            flash(
                "Jina la customer linahitajika.",
                "warning"
            )

            return redirect(
                url_for("customers")
            )

        conn.execute(
            """
            INSERT INTO customers
            (
                user_id,
                name,
                phone,
                email,
                address,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                name,
                phone,
                email,
                address,
                notes
            )
        )

        conn.commit()

        conn.close()

        flash(
            "Customer ameongezwa.",
            "success"
        )

        return redirect(
            url_for("customers")
        )

    rows = conn.execute(
        """
        SELECT *
        FROM customers
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user["id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "customers.html",
        customers=rows
    )


# ============================================================
# DEBTS
# ============================================================

@app.route(
    "/debts",
    methods=["GET", "POST"]
)
@login_required
def debts():

    user = get_current_user()

    conn = get_db()

    if request.method == "POST":

        customer_name = request.form.get(
            "customer_name",
            ""
        ).strip()

        customer_phone = request.form.get(
            "customer_phone",
            ""
        ).strip()

        try:

            amount = float(
                request.form.get(
                    "amount",
                    0
                ) or 0
            )

            paid = float(
                request.form.get(
                    "paid",
                    0
                ) or 0
            )

        except Exception:

            conn.close()

            flash(
                "Amount si sahihi.",
                "danger"
            )

            return redirect(
                url_for("debts")
            )

        if amount <= 0:

            conn.close()

            flash(
                "Amount lazima iwe zaidi ya sifuri.",
                "warning"
            )

            return redirect(
                url_for("debts")
            )

        balance = max(
            0,
            amount - paid
        )

        status = (
            "Paid"
            if balance <= 0
            else "Pending"
        )

        conn.execute(
            """
            INSERT INTO debts
            (
                user_id,
                customer_name,
                customer_phone,
                amount,
                paid,
                balance,
                status,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                customer_name,
                customer_phone,
                amount,
                paid,
                balance,
                status,
                request.form.get(
                    "notes",
                    ""
                )
            )
        )

        conn.commit()

        conn.close()

        flash(
            "Deni limeongezwa.",
            "success"
        )

        return redirect(
            url_for("debts")
        )

    rows = conn.execute(
        """
        SELECT *
        FROM debts
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user["id"],)
    ).fetchall()

    total_debt = conn.execute(
        """
        SELECT COALESCE(
            SUM(balance),
            0
        )
        FROM debts
        WHERE user_id = ?
        """,
        (user["id"],)
    ).fetchone()[0]

    conn.close()

    return render_template(
        "debts.html",
        debts=rows,
        total_debt=total_debt
    )


# ============================================================
# PAY DEBT
# ============================================================

@app.route(
    "/debts/pay/<int:debt_id>",
    methods=["POST"]
)
@login_required
def pay_debt(debt_id):

    user = get_current_user()

    try:

        amount = float(
            request.form.get(
                "amount",
                0
            ) or 0
        )

    except Exception:

        flash(
            "Amount si sahihi.",
            "danger"
        )

        return redirect(
            url_for("debts")
        )

    if amount <= 0:

        flash(
            "Weka amount zaidi ya 0.",
            "warning"
        )

        return redirect(
            url_for("debts")
        )

    conn = get_db()

    debt = conn.execute(
        """
        SELECT *
        FROM debts
        WHERE id = ?
        AND user_id = ?
        """,
        (
            debt_id,
            user["id"]
        )
    ).fetchone()

    if not debt:

        conn.close()

        flash(
            "Deni halijapatikana.",
            "danger"
        )

        return redirect(
            url_for("debts")
        )

    balance = float(
        debt["balance"] or 0
    )

    amount = min(
        amount,
        balance
    )

    new_paid = (
        float(debt["paid"] or 0)
        + amount
    )

    new_balance = max(
        0,
        balance - amount
    )

    status = (
        "Paid"
        if new_balance <= 0
        else "Pending"
    )

    conn.execute(
        """
        UPDATE debts
        SET paid = ?,
            balance = ?,
            status = ?
        WHERE id = ?
        """,
        (
            new_paid,
            new_balance,
            status,
            debt_id
        )
    )

    conn.execute(
        """
        INSERT INTO debt_payments
        (
            debt_id,
            user_id,
            amount,
            payment_method,
            notes
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            debt_id,
            user["id"],
            amount,
            request.form.get(
                "payment_method",
                "Cash"
            ),
            request.form.get(
                "notes",
                ""
            )
        )
    )

    conn.commit()
    conn.close()

    log_action(
        user["id"],
        "DEBT_PAYMENT",
        f"Debt {debt_id}: {amount}"
    )

    flash(
        "Malipo ya deni yamehifadhiwa.",
        "success"
    )

    return redirect(
        url_for("debts")
    )


# ============================================================
# EXPENSES
# ============================================================

@app.route(
    "/expenses",
    methods=["GET", "POST"]
)
@login_required
def expenses():

    user = get_current_user()

    conn = get_db()

    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        category = request.form.get(
            "category",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        expense_date = request.form.get(
            "expense_date",
            datetime.now().strftime(
                "%Y-%m-%d"
            )
        )

        try:

            amount = float(
                request.form.get(
                    "amount",
                    0
                ) or 0
            )

        except Exception:

            amount = 0

        if not title or amount <= 0:

            conn.close()

            flash(
                "Jaza title na amount sahihi.",
                "warning"
            )

            return redirect(
                url_for("expenses")
            )

        conn.execute(
            """
            INSERT INTO expenses
            (
                user_id,
                title,
                category,
                amount,
                description,
                expense_date
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                title,
                category,
                amount,
                description,
                expense_date
            )
        )

        conn.commit()

        conn.close()

        flash(
            "Expense imehifadhiwa.",
            "success"
        )

        return redirect(
            url_for("expenses")
        )

    rows = conn.execute(
        """
        SELECT *
        FROM expenses
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user["id"],)
    ).fetchall()

    total = conn.execute(
        """
        SELECT COALESCE(
            SUM(amount),
            0
        )
        FROM expenses
        WHERE user_id = ?
        """,
        (user["id"],)
    ).fetchone()[0]

    conn.close()

    return render_template(
        "expenses.html",
        expenses=rows,
        total_expenses=total
    )


# ============================================================
# REPORTS
# ============================================================

@app.route("/reports")
@login_required
def reports():

    user = get_current_user()

    conn = get_db()

    today = datetime.now().strftime(
        "%Y-%m-%d"
    )

    month = datetime.now().strftime(
        "%Y-%m"
    )

    sales_today = conn.execute(
        """
        SELECT
            COALESCE(
                SUM(amount - discount),
                0
            ) AS total,
            COUNT(*) AS count,
            COALESCE(
                SUM(profit),
                0
            ) AS profit
        FROM receipts
        WHERE user_id = ?
        AND substr(created_at, 1, 10) = ?
        """,
        (
            user["id"],
            today
        )
    ).fetchone()

    sales_month = conn.execute(
        """
        SELECT
            COALESCE(
                SUM(amount - discount),
                0
            ) AS total,
            COUNT(*) AS count,
            COALESCE(
                SUM(profit),
                0
            ) AS profit
        FROM receipts
        WHERE user_id = ?
        AND substr(created_at, 1, 7) = ?
        """,
        (
            user["id"],
            month
        )
    ).fetchone()

    expenses_month = conn.execute(
        """
        SELECT
            COALESCE(
                SUM(amount),
                0
            )
        FROM expenses
        WHERE user_id = ?
        AND substr(
            COALESCE(
                expense_date,
                created_at
            ),
            1,
            7
        ) = ?
        """,
        (
            user["id"],
            month
        )
    ).fetchone()[0]

    monthly_sales = conn.execute(
        """
        SELECT
            substr(created_at, 1, 10) AS day,
            COALESCE(
                SUM(amount - discount),
                0
            ) AS total,
            COALESCE(
                SUM(profit),
                0
            ) AS profit
        FROM receipts
        WHERE user_id = ?
        GROUP BY substr(
            created_at,
            1,
            10
        )
        ORDER BY day DESC
        LIMIT 31
        """,
        (user["id"],)
    ).fetchall()

    top_products = conn.execute(
        """
        SELECT
            json_extract(value, '$.name') AS name,
            SUM(
                json_extract(value, '$.quantity')
            ) AS quantity
        FROM receipts,
        json_each(receipts.items)
        WHERE receipts.user_id = ?
        GROUP BY name
        ORDER BY quantity DESC
        LIMIT 10
        """,
        (user["id"],)
    ).fetchall()

    conn.close()

    report_data = {
        "today_sales": sales_today["total"] or 0,
        "today_transactions": sales_today["count"] or 0,
        "today_profit": sales_today["profit"] or 0,

        "month_sales": sales_month["total"] or 0,
        "month_transactions": sales_month["count"] or 0,
        "month_profit": sales_month["profit"] or 0,

        "month_expenses": expenses_month or 0,

        "net_month": (
            float(sales_month["profit"] or 0)
            - float(expenses_month or 0)
        )
    }

    return render_template(
        "reports.html",
        stats=report_data,
        monthly_sales=monthly_sales,
        top_products=top_products
    )


# ============================================================
# RECEIPT
# ============================================================

@app.route(
    "/receipt/<int:receipt_id>"
)
@login_required
def receipt(receipt_id):

    user = get_current_user()

    conn = get_db()

    row = conn.execute(
        """
        SELECT *
        FROM receipts
        WHERE id = ?
        AND user_id = ?
        """,
        (
            receipt_id,
            user["id"]
        )
    ).fetchone()

    conn.close()

    if not row:

        flash(
            "Receipt haijapatikana.",
            "danger"
        )

        return redirect(
            url_for("sales")
        )

    import json

    try:

        items = json.loads(
            row["items"] or "[]"
        )

    except Exception:

        items = []

    return render_template(
        "receipt.html",
        receipt=row,
        items=items
    )


# ============================================================
# SMS
# ============================================================

def send_beem_sms(
    phone,
    message
):

    api_key = get_setting(
        "beem_api_key",
        ""
    )

    secret = get_setting(
        "beem_secret",
        ""
    )

    sender = get_setting(
        "beem_sender",
        "Mkolani"
    )

    phone = normalize_phone(
        phone
    )

    if not api_key or not secret:

        return {
            "success": False,
            "message": "Beem API credentials hazijawekwa."
        }

    if not phone:

        return {
            "success": False,
            "message": "Namba ya simu si sahihi."
        }

    try:

        response = requests.post(
            "https://api.beem.africa/v1/send",
            auth=(
                api_key,
                secret
            ),
            json={
                "source_addr": sender,
                "encoding": 0,
                "message": message,
                "recipients": [
                    {
                        "recipient_id": 1,
                        "dest_addr": phone
                    }
                ]
            },
            timeout=20
        )

        return {
            "success": response.ok,
            "status_code": response.status_code,
            "response": response.text
        }

    except Exception as e:

        return {
            "success": False,
            "message": str(e)
        }


@app.route(
    "/sms",
    methods=["GET", "POST"]
)
@login_required
def sms():

    user = get_current_user()

    if request.method == "POST":

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        message = request.form.get(
            "message",
            ""
        ).strip()

        result = send_beem_sms(
            phone,
            message
        )

        conn = get_db()

        conn.execute(
            """
            INSERT INTO sms_logs
            (
                user_id,
                phone,
                message,
                status,
                response
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                phone,
                message,
                "SUCCESS"
                if result.get("success")
                else "FAILED",
                str(result)
            )
        )

        conn.commit()
        conn.close()

        if result.get("success"):

            flash(
                "SMS imetumwa.",
                "success"
            )

        else:

            flash(
                result.get(
                    "message",
                    "SMS imeshindikana."
                ),
                "danger"
            )

        return redirect(
            url_for("sms")
        )

    conn = get_db()

    logs = conn.execute(
        """
        SELECT *
        FROM sms_logs
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 100
        """,
        (user["id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "sms.html",
        sms_logs=logs
    )


# ============================================================
# PROFILE / SETTINGS
# ============================================================

@app.route(
    "/profile",
    methods=["GET", "POST"]
)
@app.route(
    "/settings",
    methods=["GET", "POST"]
)
@login_required
def profile():

    user = get_current_user()

    if request.method == "POST":

        name = request.form.get(
            "name",
            user["name"] or ""
        ).strip()

        phone = request.form.get(
            "phone",
            user["phone"] or ""
        ).strip()

        business_name = request.form.get(
            "business_name",
            user["business_name"]
            or "Mkolani Stationery"
        ).strip()

        currency = request.form.get(
            "currency",
            get_setting(
                "currency",
                "TZS"
            )
        ).strip()

        conn = get_db()

        conn.execute(
            """
            UPDATE users
            SET name = ?,
                phone = ?,
                business_name = ?
            WHERE id = ?
            """,
            (
                name,
                phone,
                business_name,
                user["id"]
            )
        )

        conn.commit()
        conn.close()

        set_setting(
            "business_name",
            business_name
        )

        set_setting(
            "currency",
            currency or "TZS"
        )

        log_action(
            user["id"],
            "UPDATE_PROFILE",
            "Profile updated"
        )

        flash(
            "Profile imeboreshwa.",
            "success"
        )

        return redirect(
            url_for("profile")
        )

    # --------------------------------------------------------
    # IMPORTANT:
    # Old system sometimes rendered user.html here.
    # We preserve its expected variables so it cannot crash.
    # --------------------------------------------------------

    data = get_dashboard_data(
        user["id"]
    )

    return render_template(
        "user.html",
        user=user,
        current_user=user,
        profile_mode=True,
        **data
    )


# ============================================================
# MASTER / ADMIN
# ============================================================

@app.route(
    "/master",
    methods=["GET", "POST"]
)
@master_required
def master():

    user = get_current_user()

    conn = get_db()

    if request.method == "POST":

        action = request.form.get(
            "action",
            ""
        )

        # ----------------------------------------------------
        # ADD USER
        # ----------------------------------------------------

        if action == "add_user":

            name = request.form.get(
                "name",
                ""
            ).strip()

            email = (
                request.form.get(
                    "email",
                    ""
                )
                .strip()
                .lower()
            )

            password = request.form.get(
                "password",
                ""
            )

            role = request.form.get(
                "role",
                "Staff"
            )

            phone = request.form.get(
                "phone",
                ""
            ).strip()

            if not name or not email or not password:

                flash(
                    "Jaza taarifa zote muhimu.",
                    "warning"
                )

            else:

                existing = conn.execute(
                    """
                    SELECT id
                    FROM users
                    WHERE lower(email) = ?
                    """,
                    (email,)
                ).fetchone()

                if existing:

                    flash(
                        "Email tayari ipo.",
                        "danger"
                    )

                else:

                    conn.execute(
                        """
                        INSERT INTO users
                        (
                            name,
                            email,
                            password,
                            role,
                            is_admin,
                            is_active,
                            business_name,
                            phone
                        )
                        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                        """,
                        (
                            name,
                            email,
                            generate_password_hash(
                                password
                            ),
                            role,
                            1 if role == "Master"
                            else 0,
                            user["business_name"],
                            phone
                        )
                    )

                    conn.commit()

                    flash(
                        "User ameongezwa.",
                        "success"
                    )

        # ----------------------------------------------------
        # CHANGE ROLE
        # ----------------------------------------------------

        elif action == "change_role":

            target_id = request.form.get(
                "user_id"
            )

            role = request.form.get(
                "role",
                "Staff"
            )

            try:

                target_id = int(
                    target_id
                )

                if target_id == user["id"]:

                    flash(
                        "Huwezi kubadilisha role yako mwenyewe hapa.",
                        "warning"
                    )

                else:

                    conn.execute(
                        """
                        UPDATE users
                        SET role = ?,
                            is_admin = ?
                        WHERE id = ?
                        """,
                        (
                            role,
                            1 if role == "Master"
                            else 0,
                            target_id
                        )
                    )

                    conn.commit()

                    flash(
                        "Role imebadilishwa.",
                        "success"
                    )

            except Exception:

                flash(
                    "User ID si sahihi.",
                    "danger"
                )

        # ----------------------------------------------------
        # TOGGLE USER
        # ----------------------------------------------------

        elif action == "toggle_user":

            target_id = request.form.get(
                "user_id"
            )

            try:

                target_id = int(
                    target_id
                )

                if target_id == user["id"]:

                    flash(
                        "Huwezi kujizima mwenyewe.",
                        "warning"
                    )

                else:

                    conn.execute(
                        """
                        UPDATE users
                        SET is_active =
                            CASE
                                WHEN is_active = 1
                                THEN 0
                                ELSE 1
                            END
                        WHERE id = ?
                        """,
                        (target_id,)
                    )

                    conn.commit()

                    flash(
                        "Status ya user imebadilishwa.",
                        "success"
                    )

            except Exception:

                flash(
                    "Hitilafu.",
                    "danger"
                )

        # ----------------------------------------------------
        # DELETE USER
        # ----------------------------------------------------

        elif action == "delete_user":

            target_id = request.form.get(
                "user_id"
            )

            try:

                target_id = int(
                    target_id
                )

                if target_id == user["id"]:

                    flash(
                        "Huwezi kujifuta mwenyewe.",
                        "warning"
                    )

                else:

                    conn.execute(
                        """
                        DELETE FROM users
                        WHERE id = ?
                        """,
                        (target_id,)
                    )

                    conn.commit()

                    flash(
                        "User amefutwa.",
                        "success"
                    )

            except Exception:

                flash(
                    "Hitilafu wakati wa kufuta user.",
                    "danger"
                )

        # ----------------------------------------------------
        # SYSTEM SETTINGS
        # ----------------------------------------------------

        elif action == "settings":

            app_name = request.form.get(
                "app_name",
                "Mkolani POS"
            ).strip()

            business_name = request.form.get(
                "business_name",
                "Mkolani Stationery"
            ).strip()

            currency = request.form.get(
                "currency",
                "TZS"
            ).strip()

            low_stock_limit = request.form.get(
                "low_stock_limit",
                "5"
            ).strip()

            beem_api_key = request.form.get(
                "beem_api_key",
                ""
            ).strip()

            beem_secret = request.form.get(
                "beem_secret",
                ""
            ).strip()

            beem_sender = request.form.get(
                "beem_sender",
                "Mkolani"
            ).strip()

            set_setting(
                "app_name",
                app_name
            )

            set_setting(
                "business_name",
                business_name
            )

            set_setting(
                "currency",
                currency
            )

            set_setting(
                "low_stock_limit",
                low_stock_limit
            )

            set_setting(
                "beem_api_key",
                beem_api_key
            )

            set_setting(
                "beem_secret",
                beem_secret
            )

            set_setting(
                "beem_sender",
                beem_sender
            )

            flash(
                "System settings zimehifadhiwa.",
                "success"
            )

        # ----------------------------------------------------
        # MASTER PIN
        # ----------------------------------------------------

        elif action == "master_pin":

            pin = request.form.get(
                "master_pin",
                ""
            ).strip()

            if len(pin) < 4:

                flash(
                    "Master PIN iwe angalau digits 4.",
                    "warning"
                )

            else:

                conn.execute(
                    """
                    UPDATE users
                    SET master_pin = ?
                    WHERE id = ?
                    """,
                    (
                        pin,
                        user["id"]
                    )
                )

                conn.commit()

                flash(
                    "Master PIN imebadilishwa.",
                    "success"
                )

    users = conn.execute(
        """
        SELECT
            id,
            name,
            email,
            role,
            is_admin,
            is_active,
            business_name,
            phone,
            created_at
        FROM users
        ORDER BY id ASC
        """
    ).fetchall()

    settings = {
        "app_name": get_setting(
            "app_name",
            "Mkolani POS"
        ),
        "business_name": get_setting(
            "business_name",
            "Mkolani Stationery"
        ),
        "currency": get_setting(
            "currency",
            "TZS"
        ),
        "low_stock_limit": get_setting(
            "low_stock_limit",
            "5"
        ),
        "beem_api_key": get_setting(
            "beem_api_key",
            ""
        ),
        "beem_secret": get_setting(
            "beem_secret",
            ""
        ),
        "beem_sender": get_setting(
            "beem_sender",
            "Mkolani"
        )
    }

    conn.close()

    return render_template(
        "master.html",
        users=users,
        settings=settings
    )


# ============================================================
# ADMIN COMPATIBILITY
# ============================================================

@app.route("/admin")
@login_required
def admin():

    user = get_current_user()

    if (
        user["role"] != "Master"
        and not user["is_admin"]
    ):

        flash(
            "Huna ruhusa.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    return master()


# ============================================================
# NOTIFICATIONS
# ============================================================

@app.route(
    "/notifications/read",
    methods=["POST", "GET"]
)
@login_required
def mark_notifications_read():

    user = get_current_user()

    conn = get_db()

    conn.execute(
        """
        UPDATE notifications
        SET is_read = 1
        WHERE user_id = ?
        """,
        (user["id"],)
    )

    conn.commit()
    conn.close()

    if request.is_json:

        return jsonify({
            "success": True
        })

    return redirect(
        url_for("dashboard")
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    user = get_current_user()

    if user:

        log_action(
            user["id"],
            "LOGOUT",
            "User logged out"
        )

    session.clear()

    flash(
        "Umetoka kwenye mfumo.",
        "info"
    )

    return redirect(
        url_for("login")
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    try:

        conn = get_db()

        conn.execute(
            "SELECT 1"
        ).fetchone()

        conn.close()

        return jsonify({
            "status": "ok",
            "app": "Mkolani POS",
            "database": "connected",
            "time": datetime.now().isoformat()
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "database": "failed",
            "error": str(e)
        }), 500


@app.route("/api/health")
def api_health():

    return health()


# ============================================================
# STATIC FILE SAFETY
# ============================================================

@app.after_request
def add_security_headers(response):

    response.headers[
        "X-Content-Type-Options"
    ] = "nosniff"

    response.headers[
        "X-Frame-Options"
    ] = "SAMEORIGIN"

    response.headers[
        "X-XSS-Protection"
    ] = "1; mode=block"

    return response


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def page_not_found(error):

    # IMPORTANT:
    # Never redirect missing static assets to login.
    # This prevents CSS/JS from receiving HTTP 302.

    if request.path.startswith(
        "/static/"
    ):

        return jsonify({
            "error": "Static file not found",
            "path": request.path
        }), 404

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "error": "Endpoint not found",
            "path": request.path
        }), 404

    user = get_current_user()

    if user:

        try:

            return render_template(
                "404.html"
            ), 404

        except Exception:

            return (
                "404 - Page Not Found",
                404
            )

    return redirect(
        url_for("login")
    )


@app.errorhandler(405)
def method_not_allowed(error):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "error": "Method Not Allowed",
            "path": request.path
        }), 405

    return (
        "Method Not Allowed",
        405
    )


@app.errorhandler(500)
def internal_server_error(error):

    try:

        app.logger.exception(
            "Internal server error"
        )

    except Exception:
        pass

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "error": "Internal server error"
        }), 500

    user = get_current_user()

    if user:

        try:

            return render_template(
                "500.html"
            ), 500

        except Exception:

            return (
                "500 - Internal Server Error",
                500
            )

    return redirect(
        url_for("login")
    )


# ============================================================
# CLI / DATABASE INITIALIZATION
# ============================================================

@app.cli.command("init-db")
def init_db_command():

    init_db()

    print(
        "Mkolani POS database initialized."
    )


# ============================================================
# APPLICATION START
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
