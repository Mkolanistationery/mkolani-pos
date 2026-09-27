from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify
)
import sqlite3
import os
import requests
import threading
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash


# ============================================================
# MKOLANI POS - ADVANCED CORE
# Phase 1: Core / Master / Users / POS / Reports / Security
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "CHANGE_THIS_SECRET_KEY_ON_RENDER"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "pos.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def add_column(conn, table, column, definition):
    if not column_exists(conn, table, column):
        try:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )
        except sqlite3.OperationalError:
            pass


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone_number TEXT,
            business_name TEXT DEFAULT 'Mkolani Enterprise',
            business_type TEXT DEFAULT 'RETAIL',
            currency TEXT DEFAULT 'TZS',
            is_admin INTEGER DEFAULT 0,
            role TEXT DEFAULT 'Staff',
            status TEXT DEFAULT 'active',
            logo_path TEXT,
            beem_api_key TEXT,
            beem_secret_key TEXT,
            beem_sender_id TEXT,
            reset_otp TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT
        )
    """)

    # Compatibility with older versions
    add_column(conn, "users", "phone_number", "TEXT")
    add_column(conn, "users", "business_name", "TEXT")
    add_column(conn, "users", "business_type", "TEXT")
    add_column(conn, "users", "currency", "TEXT")
    add_column(conn, "users", "is_admin", "INTEGER DEFAULT 0")
    add_column(conn, "users", "role", "TEXT DEFAULT 'Staff'")
    add_column(conn, "users", "status", "TEXT DEFAULT 'active'")
    add_column(conn, "users", "logo_path", "TEXT")
    add_column(conn, "users", "beem_api_key", "TEXT")
    add_column(conn, "users", "beem_secret_key", "TEXT")
    add_column(conn, "users", "beem_sender_id", "TEXT")
    add_column(conn, "users", "reset_otp", "TEXT")
    add_column(conn, "users", "created_at", "TEXT")
    add_column(conn, "users", "last_login", "TEXT")

    # Older column names
    add_column(conn, "users", "phone", "TEXT")
    add_column(conn, "users", "sector", "TEXT")
    add_column(conn, "users", "api_key", "TEXT")
    add_column(conn, "users", "secret_key", "TEXT")
    add_column(conn, "users", "sender_id", "TEXT")
    add_column(conn, "users", "logo_url", "TEXT")

    # --------------------------------------------------------
    # SYSTEM SETTINGS
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_key TEXT UNIQUE NOT NULL,
            setting_value TEXT
        )
    """)

    defaults = {
        "admin_pin": "1234",
        "app_name": "Mkolani POS",
        "app_logo": "",
        "company_name": "Mkolani Enterprise",
        "currency": "TZS",
        "sms_enabled": "1"
    }

    for key, value in defaults.items():
        cur.execute("""
            INSERT OR IGNORE INTO system_settings
            (setting_key, setting_value)
            VALUES (?, ?)
        """, (key, value))

    # --------------------------------------------------------
    # RECEIPTS
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            customer_name TEXT,
            service_item TEXT,
            quantity REAL DEFAULT 1,
            unit_price REAL DEFAULT 0,
            amount REAL DEFAULT 0,
            discount REAL DEFAULT 0,
            debt REAL DEFAULT 0,
            phone TEXT,
            payment_method TEXT DEFAULT 'Cash',
            cash_received REAL DEFAULT 0,
            change_given REAL DEFAULT 0,
            cost REAL DEFAULT 0,
            profit REAL DEFAULT 0,
            receipt_number TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    add_column(conn, "receipts", "quantity", "REAL DEFAULT 1")
    add_column(conn, "receipts", "unit_price", "REAL DEFAULT 0")
    add_column(conn, "receipts", "discount", "REAL DEFAULT 0")
    add_column(conn, "receipts", "payment_method", "TEXT DEFAULT 'Cash'")
    add_column(conn, "receipts", "cash_received", "REAL DEFAULT 0")
    add_column(conn, "receipts", "change_given", "REAL DEFAULT 0")
    add_column(conn, "receipts", "cost", "REAL DEFAULT 0")
    add_column(conn, "receipts", "profit", "REAL DEFAULT 0")
    add_column(conn, "receipts", "receipt_number", "TEXT")

    # --------------------------------------------------------
    # PRODUCTS / STOCK
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            sku TEXT,
            category TEXT,
            supplier TEXT,
            buying_price REAL DEFAULT 0,
            selling_price REAL DEFAULT 0,
            quantity REAL DEFAULT 0,
            minimum_stock REAL DEFAULT 0,
            unit TEXT DEFAULT 'pcs',
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------------------------------------------
    # CUSTOMERS
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            address TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------------------------------------------
    # DEBTS
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            customer_id INTEGER,
            customer_name TEXT,
            phone TEXT,
            reference TEXT,
            amount REAL DEFAULT 0,
            paid REAL DEFAULT 0,
            balance REAL DEFAULT 0,
            status TEXT DEFAULT 'unpaid',
            due_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------------------------------------------
    # DEBT PAYMENTS
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS debt_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            debt_id INTEGER,
            user_id INTEGER,
            amount REAL DEFAULT 0,
            payment_method TEXT DEFAULT 'Cash',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------------------------------------------
    # EXPENSES
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT NOT NULL,
            category TEXT,
            amount REAL DEFAULT 0,
            payment_method TEXT DEFAULT 'Cash',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------------------------------------------
    # SMS
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sms_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            recipient TEXT,
            message TEXT,
            sender_id TEXT,
            status TEXT DEFAULT 'pending',
            response TEXT,
            cost REAL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------------------------------------------
    # AUDIT LOG
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            description TEXT,
            ip_address TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------------------------------------------
    # NOTIFICATIONS
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            message TEXT,
            type TEXT DEFAULT 'info',
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------------------------------------------
    # FIRST ADMIN / MASTER
    # --------------------------------------------------------

    first_user = cur.execute(
        "SELECT id FROM users ORDER BY id ASC LIMIT 1"
    ).fetchone()

    if first_user:
        # Existing first admin becomes Master
        cur.execute("""
            UPDATE users
            SET role = 'Master',
                is_admin = 1
            WHERE id = ?
              AND (
                  role IS NULL
                  OR role = ''
                  OR role = 'Staff'
                  OR is_admin = 1
              )
        """, (first_user["id"],))

    conn.commit()
    conn.close()


init_db()


# ============================================================
# HELPERS
# ============================================================

def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    conn.close()

    return user


def get_setting(key, default=""):
    conn = get_db()

    row = conn.execute(
        "SELECT setting_value FROM system_settings WHERE setting_key = ?",
        (key,)
    ).fetchone()

    conn.close()

    return row["setting_value"] if row else default


def set_setting(key, value):
    conn = get_db()

    conn.execute("""
        INSERT INTO system_settings
        (setting_key, setting_value)
        VALUES (?, ?)
        ON CONFLICT(setting_key)
        DO UPDATE SET setting_value = excluded.setting_value
    """, (key, value))

    conn.commit()
    conn.close()


def log_action(action, description=""):
    try:
        user_id = session.get("user_id")
        ip = request.headers.get(
            "X-Forwarded-For",
            request.remote_addr
        )

        conn = get_db()

        conn.execute("""
            INSERT INTO audit_logs
            (user_id, action, description, ip_address)
            VALUES (?, ?, ?, ?)
        """, (
            user_id,
            action,
            description,
            ip
        ))

        conn.commit()
        conn.close()

    except Exception as e:
        print("AUDIT ERROR:", e)


def add_notification(user_id, title, message, notification_type="info"):
    try:
        conn = get_db()

        conn.execute("""
            INSERT INTO notifications
            (user_id, title, message, type)
            VALUES (?, ?, ?, ?)
        """, (
            user_id,
            title,
            message,
            notification_type
        ))

        conn.commit()
        conn.close()

    except Exception as e:
        print("NOTIFICATION ERROR:", e)


def money(value):
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def make_receipt_number():
    return "MKP-" + datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]


# ============================================================
# AUTH DECORATORS
# ============================================================

def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):

        if not session.get("user_id"):
            return redirect(url_for("index"))

        return func(*args, **kwargs)

    return wrapper


def roles_required(*roles):
    @wraps
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):

            if not session.get("user_id"):
                return redirect(url_for("index"))

            user = current_user()

            if not user:
                session.clear()
                return redirect(url_for("index"))

            user_role = user["role"] or "Staff"

            if user_role not in roles:
                flash(
                    "Huna ruhusa ya kutumia sehemu hii.",
                    "danger"
                )
                return redirect(url_for("dashboard"))

            return func(*args, **kwargs)

        return wrapper

    return decorator


def master_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):

        if not session.get("user_id"):
            return redirect(url_for("index"))

        user = current_user()

        if not user:
            session.clear()
            return redirect(url_for("index"))

        if user["role"] != "Master":
            flash(
                "Sehemu hii ni ya Master pekee.",
                "danger"
            )
            return redirect(url_for("dashboard"))

        return func(*args, **kwargs)

    return wrapper


# ============================================================
# LOGIN / REGISTER
# ============================================================

@app.route("/")
def index():

    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login():

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not email or not password:
        flash(
            "Weka email na password.",
            "danger"
        )
        return redirect(url_for("index"))

    conn = get_db()

    user = conn.execute("""
        SELECT *
        FROM users
        WHERE lower(email) = ?
    """, (email,)).fetchone()

    if not user:
        conn.close()

        flash(
            "Email au password si sahihi.",
            "danger"
        )

        return redirect(url_for("index"))

    if user["status"] == "disabled":
        conn.close()

        flash(
            "Akaunti hii imezimwa na administrator.",
            "danger"
        )

        return redirect(url_for("index"))

    stored_password = user["password"] or ""
    valid = False
    old_plain_password = False

    # New secure password
    try:
        valid = check_password_hash(
            stored_password,
            password
        )
    except Exception:
        valid = False

    # Compatibility with old plain-text passwords
    if not valid and stored_password == password:
        valid = True
        old_plain_password = True

    if not valid:
        conn.close()

        flash(
            "Email au password si sahihi.",
            "danger"
        )

        return redirect(url_for("index"))

    # Upgrade old password automatically
    if old_plain_password:
        conn.execute("""
            UPDATE users
            SET password = ?
            WHERE id = ?
        """, (
            generate_password_hash(password),
            user["id"]
        ))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        UPDATE users
        SET last_login = ?
        WHERE id = ?
    """, (now, user["id"]))

    conn.commit()
    conn.close()

    session.clear()

    session["user_id"] = user["id"]
    session["email"] = user["email"]
    session["business_name"] = (
        user["business_name"]
        or "Mkolani Enterprise"
    )
    session["role"] = user["role"] or "Staff"

    log_action(
        "LOGIN",
        f"User {email} ameingia kwenye mfumo."
    )

    return redirect(url_for("dashboard"))


@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "GET":
        return render_template("register.html")

    business_name = request.form.get(
        "business_name",
        "Mkolani Enterprise"
    ).strip()

    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    password = request.form.get(
        "password",
        ""
    )

    phone = request.form.get(
        "phone",
        ""
    ).strip()

    if not email or not password:
        flash(
            "Email na password vinahitajika.",
            "danger"
        )
        return redirect(url_for("register"))

    if len(password) < 6:
        flash(
            "Password iwe na angalau characters 6.",
            "danger"
        )
        return redirect(url_for("register"))

    conn = get_db()

    existing = conn.execute(
        "SELECT id FROM users WHERE lower(email) = ?",
        (email,)
    ).fetchone()

    if existing:
        conn.close()

        flash(
            "Email hii tayari ipo kwenye mfumo.",
            "danger"
        )

        return redirect(url_for("register"))

    total_users = conn.execute(
        "SELECT COUNT(*) AS total FROM users"
    ).fetchone()["total"]

    if total_users == 0:
        role = "Master"
        is_admin = 1
    else:
        role = "Staff"
        is_admin = 0

    hashed_password = generate_password_hash(password)

    cur = conn.execute("""
        INSERT INTO users
        (
            email,
            password,
            phone_number,
            business_name,
            business_type,
            currency,
            is_admin,
            role,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        email,
        hashed_password,
        phone,
        business_name,
        "RETAIL",
        "TZS",
        is_admin,
        role,
        "active",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    user_id = cur.lastrowid

    conn.commit()
    conn.close()

    flash(
        "Akaunti imetengenezwa. Sasa ingia.",
        "success"
    )

    return redirect(url_for("index"))


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
@app.route("/home")
@login_required
def dashboard():

    user = current_user()

    if not user:
        session.clear()
        return redirect(url_for("index"))

    uid = user["id"]

    conn = get_db()

    sales = conn.execute("""
        SELECT
            COALESCE(SUM(amount), 0) AS total,
            COALESCE(SUM(debt), 0) AS debt,
            COUNT(*) AS receipts
        FROM receipts
        WHERE user_id = ?
    """, (uid,)).fetchone()

    expenses = conn.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM expenses
        WHERE user_id = ?
    """, (uid,)).fetchone()

    products = conn.execute("""
        SELECT COUNT(*) AS total
        FROM products
        WHERE user_id = ?
    """, (uid,)).fetchone()

    customers = conn.execute("""
        SELECT COUNT(*) AS total
        FROM customers
        WHERE user_id = ?
    """, (uid,)).fetchone()

    stock_value = conn.execute("""
        SELECT COALESCE(
            SUM(quantity * buying_price),
            0
        ) AS total
        FROM products
        WHERE user_id = ?
    """, (uid,)).fetchone()

    profit = conn.execute("""
        SELECT COALESCE(SUM(profit), 0) AS total
        FROM receipts
        WHERE user_id = ?
    """, (uid,)).fetchone()

    recent_sales = conn.execute("""
        SELECT *
        FROM receipts
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 10
    """, (uid,)).fetchall()

    low_stock = conn.execute("""
        SELECT *
        FROM products
        WHERE user_id = ?
          AND quantity <= minimum_stock
        ORDER BY quantity ASC
        LIMIT 10
    """, (uid,)).fetchall()

    unread_notifications = conn.execute("""
        SELECT *
        FROM notifications
        WHERE user_id = ?
          AND is_read = 0
        ORDER BY id DESC
        LIMIT 10
    """, (uid,)).fetchall()

    conn.close()

    stats = {
        "sales": money(sales["total"]),
        "paid": money(sales["total"]) - money(sales["debt"]),
        "debt": money(sales["debt"]),
        "receipts": sales["receipts"] or 0,
        "expenses": money(expenses["total"]),
        "profit": money(profit["total"]) - money(expenses["total"]),
        "products": products["total"] or 0,
        "customers": customers["total"] or 0,
        "stock_value": money(stock_value["total"])
    }

    # Existing user.html is supported
    return render_template(
        "user.html",
        user=user,
        stats=stats,
        sales_stats=stats,
        recent_sales=recent_sales,
        receipts=recent_sales,
        low_stock=low_stock,
        notifications=unread_notifications
    )


@app.route("/api/dashboard")
@login_required
def api_dashboard():

    user = current_user()

    conn = get_db()

    sales = conn.execute("""
        SELECT
            COALESCE(SUM(amount),0) sales,
            COALESCE(SUM(debt),0) debt,
            COALESCE(SUM(profit),0) profit,
            COUNT(*) receipts
        FROM receipts
        WHERE user_id = ?
    """, (user["id"],)).fetchone()

    expenses = conn.execute("""
        SELECT COALESCE(SUM(amount),0) total
        FROM expenses
        WHERE user_id = ?
    """, (user["id"],)).fetchone()["total"]

    conn.close()

    return jsonify({
        "sales": money(sales["sales"]),
        "debt": money(sales["debt"]),
        "receipts": sales["receipts"],
        "profit": money(sales["profit"]) - money(expenses),
        "expenses": money(expenses)
    })


# ============================================================
# SALES / POS
# ============================================================

@app.route("/sales", methods=["GET", "POST"])
@login_required
def sales():

    user = current_user()
    uid = user["id"]

    if request.method == "POST":

        customer_name = request.form.get(
            "customer_name",
            "Walk-in Customer"
        ).strip()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        item = request.form.get(
            "service_item",
            request.form.get(
                "item",
                ""
            )
        ).strip()

        quantity = money(
            request.form.get("qty", 1)
        )

        total = money(
            request.form.get(
                "total",
                request.form.get(
                    "amount",
                    0
                )
            )
        )

        cost = money(
            request.form.get("cost", 0)
        )

        discount = money(
            request.form.get("discount", 0)
        )

        paid = money(
            request.form.get(
                "paid",
                request.form.get(
                    "amount_paid",
                    total
                )
            )
        )

        cash_received = money(
            request.form.get(
                "cash_received",
                paid
            )
        )

        payment_method = request.form.get(
            "payment_method",
            "Cash"
        )

        debt = max(
            total - paid,
            0
        )

        change = max(
            cash_received - paid,
            0
        )

        profit = (
            total
            - discount
            - cost
        )

        receipt_number = make_receipt_number()

        conn = get_db()

        conn.execute("""
            INSERT INTO receipts
            (
                user_id,
                customer_name,
                service_item,
                quantity,
                unit_price,
                amount,
                discount,
                debt,
                phone,
                payment_method,
                cash_received,
                change_given,
                cost,
                profit,
                receipt_number
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            uid,
            customer_name,
            item,
            quantity,
            (
                total / quantity
                if quantity > 0
                else total
            ),
            total,
            discount,
            debt,
            phone,
            payment_method,
            cash_received,
            change,
            cost,
            profit,
            receipt_number
        ))

        # Auto customer creation
        if customer_name and customer_name != "Walk-in Customer":

            existing_customer = conn.execute("""
                SELECT id
                FROM customers
                WHERE user_id = ?
                  AND (
                      name = ?
                      OR (
                          phone != ''
                          AND phone = ?
                      )
                  )
                LIMIT 1
            """, (
                uid,
                customer_name,
                phone
            )).fetchone()

            if not existing_customer:
                conn.execute("""
                    INSERT INTO customers
                    (user_id, name, phone)
                    VALUES (?, ?, ?)
                """, (
                    uid,
                    customer_name,
                    phone
                ))

        # Create debt automatically
        if debt > 0:

            conn.execute("""
                INSERT INTO debts
                (
                    user_id,
                    customer_name,
                    phone,
                    reference,
                    amount,
                    paid,
                    balance,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                uid,
                customer_name,
                phone,
                receipt_number,
                total,
                paid,
                debt,
                "unpaid"
            ))

        # Reduce stock if matching SKU/name exists
        product = conn.execute("""
            SELECT *
            FROM products
            WHERE user_id = ?
              AND (
                  name = ?
                  OR sku = ?
              )
            LIMIT 1
        """, (
            uid,
            item,
            item
        )).fetchone()

        if product:

            new_quantity = max(
                money(product["quantity"]) - quantity,
                0
            )

            conn.execute("""
                UPDATE products
                SET quantity = ?
                WHERE id = ?
            """, (
                new_quantity,
                product["id"]
            ))

            if new_quantity <= money(
                product["minimum_stock"]
            ):
                add_notification(
                    uid,
                    "Stock iko chini",
                    f"{product['name']} imefikia stock ya chini.",
                    "warning"
                )

        conn.commit()
        conn.close()

        log_action(
            "SALE",
            f"Sale {receipt_number} ya TZS {total:,.2f}"
        )

        flash(
            f"Mauzo yamehifadhiwa. Risiti: {receipt_number}",
            "success"
        )

        return redirect(url_for("sales"))

    conn = get_db()

    history = conn.execute("""
        SELECT *
        FROM receipts
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 100
    """, (uid,)).fetchall()

    products = conn.execute("""
        SELECT *
        FROM products
        WHERE user_id = ?
          AND status = 'active'
        ORDER BY name
    """, (uid,)).fetchall()

    conn.close()

    return render_template(
        "sales.html",
        user=user,
        sales=history,
        receipts=history,
        products=products
    )


@app.route("/api/sales")
@login_required
def api_sales():

    uid = session["user_id"]

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM receipts
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 100
    """, (uid,)).fetchall()

    conn.close()

    return jsonify([
        dict(row)
        for row in rows
    ])


# ============================================================
# PRODUCTS / STOCK
# ============================================================

@app.route("/products", methods=["GET", "POST"])
@login_required
def products():

    uid = session["user_id"]

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

        supplier = request.form.get(
            "supplier",
            ""
        ).strip()

        buying_price = money(
            request.form.get(
                "buying_price",
                request.form.get("cost", 0)
            )
        )

        selling_price = money(
            request.form.get(
                "selling_price",
                request.form.get("price", 0)
            )
        )

        quantity = money(
            request.form.get(
                "quantity",
                request.form.get("qty", 0)
            )
        )

        minimum_stock = money(
            request.form.get(
                "minimum_stock",
                request.form.get("min_stock", 0)
            )
        )

        unit = request.form.get(
            "unit",
            "pcs"
        )

        if not name:
            flash(
                "Jina la bidhaa linahitajika.",
                "danger"
            )
            return redirect(url_for("products"))

        conn = get_db()

        conn.execute("""
            INSERT INTO products
            (
                user_id,
                name,
                sku,
                category,
                supplier,
                buying_price,
                selling_price,
                quantity,
                minimum_stock,
                unit
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            uid,
            name,
            sku,
            category,
            supplier,
            buying_price,
            selling_price,
            quantity,
            minimum_stock,
            unit
        ))

        conn.commit()
        conn.close()

        log_action(
            "PRODUCT_CREATE",
            f"Bidhaa {name} imeongezwa."
        )

        flash(
            "Bidhaa imeongezwa kwenye stock.",
            "success"
        )

        return redirect(url_for("products"))

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM products
        WHERE user_id = ?
        ORDER BY id DESC
    """, (uid,)).fetchall()

    conn.close()

    return render_template(
        "products.html",
        products=rows
    )


@app.route("/products/delete/<int:product_id>", methods=["POST"])
@login_required
def delete_product(product_id):

    conn = get_db()

    conn.execute("""
        DELETE FROM products
        WHERE id = ?
          AND user_id = ?
    """, (
        product_id,
        session["user_id"]
    ))

    conn.commit()
    conn.close()

    log_action(
        "PRODUCT_DELETE",
        f"Product {product_id} imefutwa."
    )

    flash(
        "Bidhaa imefutwa.",
        "success"
    )

    return redirect(url_for("products"))


# ============================================================
# CUSTOMERS / CRM
# ============================================================

@app.route("/customers", methods=["GET", "POST"])
@login_required
def customers():

    uid = session["user_id"]

    if request.method == "POST":

        name = request.form.get(
            "name",
            request.form.get(
                "customer_name",
                ""
            )
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
            flash(
                "Jina la mteja linahitajika.",
                "danger"
            )
            return redirect(url_for("customers"))

        conn = get_db()

        conn.execute("""
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
        """, (
            uid,
            name,
            phone,
            email,
            address,
            notes
        ))

        conn.commit()
        conn.close()

        log_action(
            "CUSTOMER_CREATE",
            f"Mteja {name} ameongezwa."
        )

        flash(
            "Mteja ameongezwa.",
            "success"
        )

        return redirect(url_for("customers"))

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM customers
        WHERE user_id = ?
        ORDER BY id DESC
    """, (uid,)).fetchall()

    conn.close()

    return render_template(
        "customers.html",
        customers=rows
    )


# ============================================================
# DEBTS
# ============================================================

@app.route("/debts", methods=["GET", "POST"])
@login_required
def debts():

    uid = session["user_id"]

    if request.method == "POST":

        customer_name = request.form.get(
            "customer_name",
            ""
        ).strip()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        reference = request.form.get(
            "reference",
            ""
        ).strip()

        amount = money(
            request.form.get(
                "amount",
                0
            )
        )

        paid = money(
            request.form.get(
                "paid",
                0
            )
        )

        balance = max(
            amount - paid,
            0
        )

        status = (
            "paid"
            if balance <= 0
            else "partial"
            if paid > 0
            else "unpaid"
        )

        conn = get_db()

        conn.execute("""
            INSERT INTO debts
            (
                user_id,
                customer_name,
                phone,
                reference,
                amount,
                paid,
                balance,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            uid,
            customer_name,
            phone,
            reference,
            amount,
            paid,
            balance,
            status
        ))

        conn.commit()
        conn.close()

        log_action(
            "DEBT_CREATE",
            f"Deni la {customer_name}: TZS {balance:,.2f}"
        )

        flash(
            "Deni limehifadhiwa.",
            "success"
        )

        return redirect(url_for("debts"))

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM debts
        WHERE user_id = ?
        ORDER BY id DESC
    """, (uid,)).fetchall()

    total_debt = conn.execute("""
        SELECT COALESCE(SUM(balance), 0) AS total
        FROM debts
        WHERE user_id = ?
          AND balance > 0
    """, (uid,)).fetchone()["total"]

    conn.close()

    return render_template(
        "debts.html",
        debts=rows,
        total_debt=money(total_debt)
    )


@app.route("/debts/pay/<int:debt_id>", methods=["POST"])
@login_required
def pay_debt(debt_id):

    uid = session["user_id"]

    amount = money(
        request.form.get(
            "amount",
            0
        )
    )

    payment_method = request.form.get(
        "payment_method",
        "Cash"
    )

    if amount <= 0:
        flash(
            "Weka kiasi halali.",
            "danger"
        )
        return redirect(url_for("debts"))

    conn = get_db()

    debt = conn.execute("""
        SELECT *
        FROM debts
        WHERE id = ?
          AND user_id = ?
    """, (
        debt_id,
        uid
    )).fetchone()

    if not debt:
        conn.close()

        flash(
            "Deni halipatikani.",
            "danger"
        )

        return redirect(url_for("debts"))

    payment = min(
        amount,
        money(debt["balance"])
    )

    new_paid = money(debt["paid"]) + payment
    new_balance = max(
        money(debt["amount"]) - new_paid,
        0
    )

    status = (
        "paid"
        if new_balance <= 0
        else "partial"
    )

    conn.execute("""
        UPDATE debts
        SET paid = ?,
            balance = ?,
            status = ?
        WHERE id = ?
    """, (
        new_paid,
        new_balance,
        status,
        debt_id
    ))

    conn.execute("""
        INSERT INTO debt_payments
        (
            debt_id,
            user_id,
            amount,
            payment_method
        )
        VALUES (?, ?, ?, ?)
    """, (
        debt_id,
        uid,
        payment,
        payment_method
    ))

    conn.commit()
    conn.close()

    log_action(
        "DEBT_PAYMENT",
        f"Malipo ya deni TZS {payment:,.2f}"
    )

    flash(
        "Malipo ya deni yamehifadhiwa.",
        "success"
    )

    return redirect(url_for("debts"))


# ============================================================
# EXPENSES
# ============================================================

@app.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses():

    uid = session["user_id"]

    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        category = request.form.get(
            "category",
            ""
        ).strip()

        amount = money(
            request.form.get(
                "amount",
                0
            )
        )

        payment_method = request.form.get(
            "payment_method",
            "Cash"
        )

        notes = request.form.get(
            "notes",
            ""
        ).strip()

        if not title or amount <= 0:
            flash(
                "Jaza jina la expense na kiasi sahihi.",
                "danger"
            )
            return redirect(url_for("expenses"))

        conn = get_db()

        conn.execute("""
            INSERT INTO expenses
            (
                user_id,
                title,
                category,
                amount,
                payment_method,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            uid,
            title,
            category,
            amount,
            payment_method,
            notes
        ))

        conn.commit()
        conn.close()

        log_action(
            "EXPENSE_CREATE",
            f"Expense TZS {amount:,.2f}: {title}"
        )

        flash(
            "Expense imehifadhiwa.",
            "success"
        )

        return redirect(url_for("expenses"))

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM expenses
        WHERE user_id = ?
        ORDER BY id DESC
    """, (uid,)).fetchall()

    total = conn.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM expenses
        WHERE user_id = ?
    """, (uid,)).fetchone()["total"]

    conn.close()

    return render_template(
        "expenses.html",
        expenses=rows,
        total_expenses=money(total)
    )


# ============================================================
# REPORTS
# ============================================================

@app.route("/reports")
@login_required
def reports():

    uid = session["user_id"]

    conn = get_db()

    sales = conn.execute("""
        SELECT
            COALESCE(SUM(amount), 0) AS sales,
            COALESCE(SUM(debt), 0) AS debt,
            COALESCE(SUM(profit), 0) AS profit,
            COUNT(*) AS receipts
        FROM receipts
        WHERE user_id = ?
    """, (uid,)).fetchone()

    expenses_total = conn.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM expenses
        WHERE user_id = ?
    """, (uid,)).fetchone()["total"]

    payment_methods = conn.execute("""
        SELECT
            payment_method,
            COALESCE(SUM(amount - debt), 0) AS total
        FROM receipts
        WHERE user_id = ?
        GROUP BY payment_method
        ORDER BY total DESC
    """, (uid,)).fetchall()

    daily_sales = conn.execute("""
        SELECT
            date(created_at) AS day,
            COALESCE(SUM(amount), 0) AS total
        FROM receipts
        WHERE user_id = ?
        GROUP BY date(created_at)
        ORDER BY day DESC
        LIMIT 30
    """, (uid,)).fetchall()

    top_products = conn.execute("""
        SELECT
            service_item,
            SUM(quantity) AS quantity,
            SUM(amount) AS total
        FROM receipts
        WHERE user_id = ?
        GROUP BY service_item
        ORDER BY total DESC
        LIMIT 20
    """, (uid,)).fetchall()

    conn.close()

    stats = {
        "sales": money(sales["sales"]),
        "debt": money(sales["debt"]),
        "profit_before_expenses": money(sales["profit"]),
        "expenses": money(expenses_total),
        "net_profit": (
            money(sales["profit"])
            - money(expenses_total)
        ),
        "receipts": sales["receipts"] or 0
    }

    return render_template(
        "reports.html",
        stats=stats,
        payment_methods=payment_methods,
        daily_sales=daily_sales,
        top_products=top_products
    )


# ============================================================
# SMS
# ============================================================

def normalize_phone(phone):

    phone = (
        phone or ""
    ).strip().replace(
        " ",
        ""
    )

    if phone.startswith("0"):
        return "255" + phone[1:]

    if phone.startswith("+255"):
        return phone[1:]

    return phone


def send_beem_sms_async(user_id, recipient, message):

    thread = threading.Thread(
        target=send_beem_sms,
        args=(
            user_id,
            recipient,
            message
        ),
        daemon=True
    )

    thread.start()


def send_beem_sms(user_id, recipient, message):

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if not user:
        conn.close()
        return

    api_key = (
        user["beem_api_key"]
        or user["api_key"]
        or os.environ.get("BEEM_API_KEY")
    )

    secret_key = (
        user["beem_secret_key"]
        or user["secret_key"]
        or os.environ.get("BEEM_SECRET_KEY")
    )

    sender_id = (
        user["beem_sender_id"]
        or user["sender_id"]
        or os.environ.get(
            "BEEM_SENDER_ID",
            "INFO"
        )
    )

    recipient = normalize_phone(recipient)

    if not api_key or not secret_key or not recipient:
        conn.execute("""
            INSERT INTO sms_logs
            (
                user_id,
                recipient,
                message,
                sender_id,
                status
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            user_id,
            recipient,
            message,
            sender_id,
            "not_configured"
        ))

        conn.commit()
        conn.close()

        return

    try:

        response = requests.post(
            "https://api.beem.africa/v1/send",
            auth=(
                api_key,
                secret_key
            ),
            json={
                "source_addr": sender_id,
                "schedule_time": "",
                "encoding": "0",
                "message": message,
                "recipients": [
                    {
                        "recipient_id": 1,
                        "dest_addr": recipient
                    }
                ]
            },
            timeout=20
        )

        status = (
            "sent"
            if response.ok
            else "failed"
        )

        response_text = response.text[:1000]

    except Exception as e:

        status = "failed"
        response_text = str(e)

    conn.execute("""
        INSERT INTO sms_logs
        (
            user_id,
            recipient,
            message,
            sender_id,
            status,
            response
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        recipient,
        message,
        sender_id,
        status,
        response_text
    ))

    conn.commit()
    conn.close()


@app.route("/sms", methods=["GET", "POST"])
@login_required
def sms():

    uid = session["user_id"]

    if request.method == "POST":

        recipient = request.form.get(
            "recipient",
            ""
        ).strip()

        message = request.form.get(
            "message",
            ""
        ).strip()

        if not recipient or not message:
            flash(
                "Weka namba ya simu na ujumbe.",
                "danger"
            )
            return redirect(url_for("sms"))

        send_beem_sms_async(
            uid,
            recipient,
            message
        )

        log_action(
            "SMS_SEND",
            f"SMS kwa {recipient}"
        )

        flash(
            "SMS imepelekwa kwenye huduma ya kutuma.",
            "success"
        )

        return redirect(url_for("sms"))

    conn = get_db()

    logs = conn.execute("""
        SELECT *
        FROM sms_logs
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 100
    """, (uid,)).fetchall()

    sent = conn.execute("""
        SELECT COUNT(*) AS total
        FROM sms_logs
        WHERE user_id = ?
          AND status = 'sent'
    """, (uid,)).fetchone()["total"]

    failed = conn.execute("""
        SELECT COUNT(*) AS total
        FROM sms_logs
        WHERE user_id = ?
          AND status = 'failed'
    """, (uid,)).fetchone()["total"]

    conn.close()

    return render_template(
        "sms.html",
        logs=logs,
        sms_sent=sent,
        sms_failed=failed
    )


# ============================================================
# RECEIPT VIEW
# ============================================================

@app.route("/receipt/<int:receipt_id>")
@login_required
def receipt_view(receipt_id):

    conn = get_db()

    receipt = conn.execute("""
        SELECT
            receipts.*,
            users.business_name,
            users.phone_number,
            users.logo_path
        FROM receipts
        LEFT JOIN users
            ON receipts.user_id = users.id
        WHERE receipts.id = ?
          AND receipts.user_id = ?
    """, (
        receipt_id,
        session["user_id"]
    )).fetchone()

    conn.close()

    if not receipt:
        flash(
            "Risiti haipatikani.",
            "danger"
        )
        return redirect(url_for("sales"))

    return render_template(
        "receipt_view.html",
        receipt=receipt
    )


# ============================================================
# PROFILE / BUSINESS SETTINGS
# ============================================================

@app.route("/profile", methods=["GET", "POST"])
@app.route("/settings", methods=["GET", "POST"])
@login_required
def profile():

    uid = session["user_id"]

    if request.method == "POST":

        business_name = request.form.get(
            "business_name",
            "Mkolani Enterprise"
        ).strip()

        business_type = request.form.get(
            "business_type",
            "RETAIL"
        ).strip()

        phone = request.form.get(
            "phone",
            request.form.get(
                "phone_number",
                ""
            )
        ).strip()

        currency = request.form.get(
            "currency",
            "TZS"
        ).strip()

        beem_api_key = request.form.get(
            "beem_api_key",
            ""
        ).strip()

        beem_secret_key = request.form.get(
            "beem_secret_key",
            ""
        ).strip()

        beem_sender_id = request.form.get(
            "beem_sender_id",
            ""
        ).strip()

        conn = get_db()

        conn.execute("""
            UPDATE users
            SET business_name = ?,
                business_type = ?,
                phone_number = ?,
                currency = ?,
                beem_api_key = ?,
                beem_secret_key = ?,
                beem_sender_id = ?
            WHERE id = ?
        """, (
            business_name,
            business_type,
            phone,
            currency,
            beem_api_key,
            beem_secret_key,
            beem_sender_id,
            uid
        ))

        conn.commit()
        conn.close()

        session["business_name"] = business_name

        log_action(
            "PROFILE_UPDATE",
            "Business settings zimebadilishwa."
        )

        flash(
            "Mipangilio imehifadhiwa.",
            "success"
        )

        return redirect(url_for("profile"))

    user = current_user()

    return render_template(
        "user.html",
        user=user
    )


# ============================================================
# MASTER CONTROL CENTER
# ============================================================

@app.route("/master", methods=["GET", "POST"])
@login_required
def master():

    user = current_user()

    if not user:
        session.clear()
        return redirect(url_for("index"))

    # Master access requires PIN
    if user["role"] != "Master":

        if request.method == "POST":

            entered_pin = request.form.get(
                "pin_input",
                ""
            )

            real_pin = get_setting(
                "admin_pin",
                "1234"
            )

            if entered_pin == real_pin:

                conn = get_db()

                # Existing account becomes Master
                conn.execute("""
                    UPDATE users
                    SET role = 'Master',
                        is_admin = 1
                    WHERE id = ?
                """, (user["id"],))

                conn.commit()
                conn.close()

                session["role"] = "Master"

                log_action(
                    "MASTER_LOGIN",
                    "Master Control Center imefunguliwa."
                )

                return redirect(url_for("master"))

            flash(
                "Master PIN si sahihi.",
                "danger"
            )

            return redirect(url_for("dashboard"))

        return render_template(
            "admin_lock.html"
        )

    conn = get_db()

    total_users = conn.execute(
        "SELECT COUNT(*) AS total FROM users"
    ).fetchone()["total"]

    active_users = conn.execute("""
        SELECT COUNT(*) AS total
        FROM users
        WHERE status = 'active'
    """).fetchone()["total"]

    total_sales = conn.execute("""
        SELECT COALESCE(SUM(amount),0) AS total
        FROM receipts
    """).fetchone()["total"]

    total_debt = conn.execute("""
        SELECT COALESCE(SUM(balance),0) AS total
        FROM debts
        WHERE balance > 0
    """).fetchone()["total"]

    total_expenses = conn.execute("""
        SELECT COALESCE(SUM(amount),0) AS total
        FROM expenses
    """).fetchone()["total"]

    total_profit = conn.execute("""
        SELECT COALESCE(SUM(profit),0) AS total
        FROM receipts
    """).fetchone()["total"]

    total_products = conn.execute(
        "SELECT COUNT(*) AS total FROM products"
    ).fetchone()["total"]

    total_customers = conn.execute(
        "SELECT COUNT(*) AS total FROM customers"
    ).fetchone()["total"]

    total_sms = conn.execute("""
        SELECT COUNT(*) AS total
        FROM sms_logs
        WHERE status = 'sent'
    """).fetchone()["total"]

    users = conn.execute("""
        SELECT
            id,
            email,
            business_name,
            phone_number,
            role,
            status,
            is_admin,
            created_at,
            last_login
        FROM users
        ORDER BY id DESC
    """).fetchall()

    recent_sales = conn.execute("""
        SELECT
            receipts.*,
            users.email,
            users.business_name
        FROM receipts
        LEFT JOIN users
            ON receipts.user_id = users.id
        ORDER BY receipts.id DESC
        LIMIT 50
    """).fetchall()

    audit_logs = conn.execute("""
        SELECT
            audit_logs.*,
            users.email
        FROM audit_logs
        LEFT JOIN users
            ON audit_logs.user_id = users.id
        ORDER BY audit_logs.id DESC
        LIMIT 100
    """).fetchall()

    conn.close()

    stats = {
        "users": total_users,
        "active_users": active_users,
        "sales": money(total_sales),
        "debt": money(total_debt),
        "expenses": money(total_expenses),
        "profit": money(total_profit) - money(total_expenses),
        "products": total_products,
        "customers": total_customers,
        "sms": total_sms
    }

    return render_template(
        "admin_dashboard.html",
        stats=stats,
        users=users,
        receipts=recent_sales,
        audit_logs=audit_logs
    )


# Alias for old admin route
@app.route("/admin", methods=["GET", "POST"])
@login_required
def admin_dashboard():
    return master()


# ============================================================
# MASTER - ADD USER
# ============================================================

@app.route(
    "/master/users/add",
    methods=["POST"]
)
@master_required
def master_add_user():

    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    password = request.form.get(
        "password",
        ""
    )

    business_name = request.form.get(
        "business_name",
        "Mkolani Enterprise"
    ).strip()

    phone = request.form.get(
        "phone",
        ""
    ).strip()

    role = request.form.get(
        "role",
        "Staff"
    )

    allowed_roles = [
        "Admin",
        "Manager",
        "Staff"
    ]

    if role not in allowed_roles:
        role = "Staff"

    if not email or not password:
        flash(
            "Email na password vinahitajika.",
            "danger"
        )
        return redirect(url_for("master"))

    conn = get_db()

    exists = conn.execute(
        "SELECT id FROM users WHERE lower(email) = ?",
        (email,)
    ).fetchone()

    if exists:
        conn.close()

        flash(
            "Email hii tayari ipo.",
            "danger"
        )

        return redirect(url_for("master"))

    conn.execute("""
        INSERT INTO users
        (
            email,
            password,
            business_name,
            phone_number,
            role,
            is_admin,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        email,
        generate_password_hash(password),
        business_name,
        phone,
        role,
        1 if role == "Admin" else 0,
        "active"
    ))

    conn.commit()
    conn.close()

    log_action(
        "USER_CREATE",
        f"Master ameongeza user {email} ({role})."
    )

    flash(
        "User ameongezwa kikamilifu.",
        "success"
    )

    return redirect(url_for("master"))


# ============================================================
# MASTER - CHANGE ROLE
# ============================================================

@app.route(
    "/master/users/<int:user_id>/role",
    methods=["POST"]
)
@master_required
def change_user_role(user_id):

    role = request.form.get(
        "role",
        "Staff"
    )

    allowed_roles = [
        "Admin",
        "Manager",
        "Staff"
    ]

    if role not in allowed_roles:
        role = "Staff"

    conn = get_db()

    target = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if not target:
        conn.close()

        flash(
            "User hajapatikana.",
            "danger"
        )

        return redirect(url_for("master"))

    # Never downgrade/delete Master through this route
    if target["role"] == "Master":
        conn.close()

        flash(
            "Master account inalindwa.",
            "danger"
        )

        return redirect(url_for("master"))

    conn.execute("""
        UPDATE users
        SET role = ?,
            is_admin = ?
        WHERE id = ?
    """, (
        role,
        1 if role == "Admin" else 0,
        user_id
    ))

    conn.commit()
    conn.close()

    log_action(
        "ROLE_CHANGE",
        f"User {user_id} amepewa role {role}."
    )

    flash(
        "Role imebadilishwa.",
        "success"
    )

    return redirect(url_for("master"))


# ============================================================
# MASTER - ENABLE / DISABLE USER
# ============================================================

@app.route(
    "/master/users/<int:user_id>/status",
    methods=["POST"]
)
@master_required
def toggle_user_status(user_id):

    conn = get_db()

    target = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if not target:
        conn.close()

        flash(
            "User hajapatikana.",
            "danger"
        )

        return redirect(url_for("master"))

    if target["role"] == "Master":
        conn.close()

        flash(
            "Master account haiwezi kuzimwa.",
            "danger"
        )

        return redirect(url_for("master"))

    new_status = (
        "disabled"
        if target["status"] == "active"
        else "active"
    )

    conn.execute("""
        UPDATE users
        SET status = ?
        WHERE id = ?
    """, (
        new_status,
        user_id
    ))

    conn.commit()
    conn.close()

    log_action(
        "USER_STATUS",
        f"User {user_id} status = {new_status}"
    )

    flash(
        f"User sasa ni {new_status}.",
        "success"
    )

    return redirect(url_for("master"))


# ============================================================
# MASTER - DELETE USER
# ============================================================

@app.route(
    "/master/users/<int:user_id>/delete",
    methods=["POST"]
)
@master_required
def delete_user(user_id):

    if user_id == session["user_id"]:
        flash(
            "Huwezi kujifuta mwenyewe.",
            "danger"
        )
        return redirect(url_for("master"))

    conn = get_db()

    target = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if not target:
        conn.close()

        flash(
            "User hajapatikana.",
            "danger"
        )

        return redirect(url_for("master"))

    if target["role"] == "Master":
        conn.close()

        flash(
            "Master account inalindwa.",
            "danger"
        )

        return redirect(url_for("master"))

    conn.execute(
        "DELETE FROM users WHERE id = ?",
        (user_id,)
    )

    conn.commit()
    conn.close()

    log_action(
        "USER_DELETE",
        f"User {target['email']} amefutwa."
    )

    flash(
        "User amefutwa.",
        "success"
    )

    return redirect(url_for("master"))


# ============================================================
# MASTER PIN
# ============================================================

@app.route(
    "/master/pin",
    methods=["POST"]
)
@master_required
def update_master_pin():

    new_pin = request.form.get(
        "new_pin",
        ""
    ).strip()

    if len(new_pin) < 4:
        flash(
            "PIN iwe na angalau tarakimu 4.",
            "danger"
        )
        return redirect(url_for("master"))

    set_setting(
        "admin_pin",
        new_pin
    )

    log_action(
        "MASTER_PIN_CHANGE",
        "Master PIN imebadilishwa."
    )

    flash(
        "Master PIN imebadilishwa.",
        "success"
    )

    return redirect(url_for("master"))


# ============================================================
# MASTER SYSTEM SETTINGS
# ============================================================

@app.route(
    "/master/settings",
    methods=["POST"]
)
@master_required
def master_settings():

    app_name = request.form.get(
        "app_name",
        "Mkolani POS"
    ).strip()

    company_name = request.form.get(
        "company_name",
        "Mkolani Enterprise"
    ).strip()

    currency = request.form.get(
        "currency",
        "TZS"
    ).strip()

    set_setting(
        "app_name",
        app_name
    )

    set_setting(
        "company_name",
        company_name
    )

    set_setting(
        "currency",
        currency
    )

    log_action(
        "SYSTEM_SETTINGS",
        "Master amebadilisha system settings."
    )

    flash(
        "System settings zimehifadhiwa.",
        "success"
    )

    return redirect(url_for("master"))


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    user_id = session.get("user_id")

    if user_id:
        log_action(
            "LOGOUT",
            "User ametoka kwenye mfumo."
        )

    session.clear()

    return redirect(url_for("index"))


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
            "app": "Mkolani POS"
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def page_not_found(error):

    if session.get("user_id"):
        flash(
            "Ukurasa huo haujapatikana.",
            "warning"
        )
        return redirect(url_for("dashboard"))

    return redirect(url_for("index"))


@app.errorhandler(500)
def server_error(error):

    print("SERVER ERROR:", error)

    return """
    <div style="
        font-family:Arial;
        max-width:700px;
        margin:60px auto;
        padding:30px;
        text-align:center;
    ">
        <h1>Mkolani POS</h1>
        <h2>Server Error</h2>
        <p>Kuna tatizo kwenye server. Angalia Render Logs.</p>
        <a href="/">Rudi Login</a>
    </div>
    """, 500


# ============================================================
# DEVELOPMENT
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=True
    )
