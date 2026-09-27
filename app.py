import os
import random
import sqlite3
import threading
from datetime import datetime
from functools import wraps

import requests
from flask import (
    Flask, render_template, request, jsonify, redirect, url_for, session, flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# Config & Directory Setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "pos.db"))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-in-render")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # Max 5MB file upload

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}


# Database Helpers
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def column_exists(conn, table, column):
    return any(r["name"] == column for r in conn.execute(f"PRAGMA table_info({table})").fetchall())


def add_column_if_missing(conn, table, column, definition):
    if not column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    # Base Tables
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        phone_number TEXT UNIQUE NOT NULL,
        business_name TEXT DEFAULT 'Mkolani Enterprise',
        business_type TEXT DEFAULT 'retail',
        currency TEXT DEFAULT 'TZS',
        is_admin INTEGER DEFAULT 0,
        reset_otp TEXT,
        logo_path TEXT,
        beem_api_key TEXT,
        beem_secret_key TEXT,
        beem_sender_id TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        business_type TEXT DEFAULT 'retail',
        customer_name TEXT NOT NULL,
        service_or_item TEXT NOT NULL,
        amount_paid REAL NOT NULL,
        amount_remaining REAL DEFAULT 0,
        customer_phone TEXT NOT NULL,
        payment_method TEXT DEFAULT 'Cash',
        cash_received REAL DEFAULT 0,
        change_given REAL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY DEFAULT 1,
        admin_pin TEXT DEFAULT '1234',
        beem_api_key TEXT,
        beem_secret_key TEXT,
        beem_sender_id TEXT,
        app_url TEXT
    )""")

    # Advanced Tables
    c.execute("""CREATE TABLE IF NOT EXISTS businesses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        business_type TEXT DEFAULT 'retail',
        currency TEXT DEFAULT 'TZS',
        phone TEXT,
        logo_path TEXT,
        owner_user_id INTEGER,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS branches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        location TEXT,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER NOT NULL,
        branch_id INTEGER,
        sku TEXT,
        name TEXT NOT NULL,
        category TEXT,
        unit TEXT DEFAULT 'pcs',
        cost_price REAL DEFAULT 0,
        selling_price REAL DEFAULT 0,
        stock_qty REAL DEFAULT 0,
        reorder_level REAL DEFAULT 5,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        phone TEXT,
        email TEXT,
        address TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER NOT NULL,
        branch_id INTEGER,
        user_id INTEGER NOT NULL,
        customer_id INTEGER,
        customer_name TEXT,
        item TEXT NOT NULL,
        qty REAL DEFAULT 1,
        total_amount REAL NOT NULL,
        cost_total REAL DEFAULT 0,
        discount REAL DEFAULT 0,
        amount_paid REAL DEFAULT 0,
        amount_remaining REAL DEFAULT 0,
        payment_method TEXT DEFAULT 'Cash',
        cash_received REAL DEFAULT 0,
        change_given REAL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER NOT NULL,
        sale_id INTEGER,
        customer_id INTEGER,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        payment_method TEXT DEFAULT 'Cash',
        note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER NOT NULL,
        branch_id INTEGER,
        user_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        description TEXT,
        amount REAL NOT NULL,
        payment_method TEXT DEFAULT 'Cash',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS stock_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        movement_type TEXT NOT NULL,
        quantity REAL NOT NULL,
        reference TEXT,
        note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS sms_wallets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER UNIQUE NOT NULL,
        balance REAL DEFAULT 0,
        total_purchased REAL DEFAULT 0,
        total_used REAL DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS sms_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER NOT NULL,
        user_id INTEGER,
        recipient TEXT NOT NULL,
        message TEXT NOT NULL,
        sender_id TEXT,
        status TEXT DEFAULT 'queued',
        provider_message_id TEXT,
        cost REAL DEFAULT 0,
        selling_price REAL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS sms_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER,
        user_id INTEGER,
        action TEXT NOT NULL,
        entity TEXT,
        entity_id INTEGER,
        details TEXT,
        ip_address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER,
        user_id INTEGER,
        type TEXT DEFAULT 'info',
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    # Migrations
    migrations = [
        ("users", "role", "TEXT DEFAULT 'staff'"),
        ("users", "business_id", "INTEGER"),
        ("users", "owner_user_id", "INTEGER"),
        ("users", "is_active", "INTEGER DEFAULT 1"),
        ("users", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("users", "last_login_at", "TIMESTAMP"),
    ]
    for table, col, definition in migrations:
        add_column_if_missing(conn, table, col, definition)

    c.execute("INSERT OR IGNORE INTO settings (id, admin_pin) VALUES (1, '1234')")

    # Backfill missing business entities for existing users
    users = c.execute("SELECT * FROM users ORDER BY id").fetchall()
    for u in users:
        if not u["business_id"]:
            c.execute("""INSERT INTO businesses
                (name, business_type, currency, phone, logo_path, owner_user_id)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (u["business_name"] or "Mkolani Enterprise", u["business_type"] or "retail",
                 u["currency"] or "TZS", u["phone_number"], u["logo_path"], u["id"]))
            bid = c.lastrowid
            c.execute("UPDATE users SET business_id=?, owner_user_id=?, role=? WHERE id=?",
                      (bid, u["id"], "master" if u["is_admin"] else "admin", u["id"]))
            c.execute("INSERT OR IGNORE INTO branches (business_id, name) VALUES (?, ?)", (bid, "Main Branch"))
            c.execute("INSERT OR IGNORE INTO sms_wallets (business_id, balance) VALUES (?, 0)", (bid,))
        else:
            if not u["role"]:
                c.execute("UPDATE users SET role=? WHERE id=?", ("admin" if u["is_admin"] else "staff", u["id"]))

    master = c.execute("SELECT id FROM users WHERE role='master' ORDER BY id LIMIT 1").fetchone()
    if not master:
        first_admin = c.execute("SELECT id FROM users WHERE is_admin=1 ORDER BY id LIMIT 1").fetchone()
        if first_admin:
            c.execute("UPDATE users SET role='master', is_admin=1 WHERE id=?", (first_admin["id"],))

    conn.commit()
    conn.close()


init_db()


# Auth & Middleware Helpers
def current_user():
    if not session.get("logged_in"):
        return None
    conn = get_db_connection()
    u = conn.execute("SELECT * FROM users WHERE id=?", (session.get("user_id"),)).fetchone()
    conn.close()
    return u


def log_action(action, entity=None, entity_id=None, details=""):
    u = current_user()
    if not u:
        return
    conn = get_db_connection()
    conn.execute("""INSERT INTO audit_logs
        (business_id, user_id, action, entity, entity_id, details, ip_address)
        VALUES (?,?,?,?,?,?,?)""",
        (u["business_id"], u["id"], action, entity, entity_id, details,
         request.headers.get("X-Forwarded-For", request.remote_addr)))
    conn.commit()
    conn.close()


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        u = current_user()
        if not u or not u["is_active"]:
            session.clear()
            flash("Akaunti yako haijawezeshwa au imezimwa.", "danger")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login"))
            u = current_user()
            if not u or u["role"] not in roles:
                flash("Huruhusiwi kufungua ukurasa huu.", "warning")
                return redirect(url_for("index"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def master_required(fn):
    return role_required("master")(fn)


def normalize_phone(phone):
    p = str(phone or "").strip().replace(" ", "").replace("-", "")
    if p.startswith("+255"):
        return p[1:]
    if p.startswith("0"):
        return "255" + p[1:]
    return p


def beem_credentials(user_id=None):
    conn = get_db_connection()
    api_key = secret_key = sender_id = None
    if user_id:
        row = conn.execute("SELECT beem_api_key, beem_secret_key, beem_sender_id FROM users WHERE id=?", (user_id,)).fetchone()
        if row:
            api_key, secret_key, sender_id = row["beem_api_key"], row["beem_secret_key"], row["beem_sender_id"]
    if not api_key or not secret_key:
        row = conn.execute("SELECT beem_api_key, beem_secret_key, beem_sender_id FROM settings WHERE id=1").fetchone()
        if row:
            api_key = api_key or row["beem_api_key"]
            secret_key = secret_key or row["beem_secret_key"]
            sender_id = sender_id or row["beem_sender_id"]
    conn.close()
    return api_key, secret_key, sender_id or "INFO"


def send_beem_sms(user_id, phone, message, business_id_value=None):
    phone = normalize_phone(phone)
    api_key, secret_key, sender_id = beem_credentials(user_id)
    if not api_key or not secret_key:
        return False, "Taarifa za Beem API hazijawekwa"

    if not business_id_value:
        u = current_user()
        business_id_value = u["business_id"] if u else None

    conn = get_db_connection()
    cur = conn.execute("""INSERT INTO sms_messages
        (business_id, user_id, recipient, message, sender_id, status) VALUES (?,?,?,?,?,?)""",
        (business_id_value, user_id, phone, message, sender_id, "queued"))
    msg_id = cur.lastrowid
    conn.commit()
    conn.close()

    def task():
        status = "failed"
        provider_id = None
        try:
            payload = {
                "source_addr": sender_id,
                "schedule_time": "",
                "message": message,
                "recipients": [{"recipient_id": 1, "dest_addr": phone}]
            }
            res = requests.post(
                "https://api.beem.africa/v1/send",
                json=payload,
                auth=(api_key, secret_key),
                headers={"Content-Type": "application/json"},
                timeout=15
            )
            try:
                data = res.json()
                provider_id = str(data.get("request_id") or data.get("message_id") or "")
            except Exception:
                provider_id = None
            if 200 <= res.status_code < 300:
                status = "sent"
        except Exception:
            status = "failed"

        conn2 = get_db_connection()
        conn2.execute("UPDATE sms_messages SET status=?, provider_message_id=? WHERE id=?",
                      (status, provider_id, msg_id))
        if status == "sent":
            wallet = conn2.execute("SELECT * FROM sms_wallets WHERE business_id=?", (business_id_value,)).fetchone()
            if wallet and wallet["balance"] > 0:
                conn2.execute("""UPDATE sms_wallets
                    SET balance=MAX(balance-1,0), total_used=total_used+1, updated_at=CURRENT_TIMESTAMP
                    WHERE business_id=?""", (business_id_value,))
        conn2.commit()
        conn2.close()

    threading.Thread(target=task, daemon=True).start()
    return True, "SMS imewekwa kwenye foleni"


@app.context_processor
def inject_globals():
    u = current_user()
    notifications = []
    if u:
        conn = get_db_connection()
        notifications = conn.execute("""SELECT * FROM notifications
            WHERE business_id=? AND (user_id IS NULL OR user_id=?)
            ORDER BY id DESC LIMIT 5""", (u["business_id"], u["id"])).fetchall()
        conn.close()
    return {"current_user": u, "notifications": notifications}


# Application Routes
@app.route("/")
@login_required
def index():
    u = current_user()
    bid = u["business_id"]
    conn = get_db_connection()

    totals = conn.execute("""SELECT
        COALESCE(SUM(total_amount),0) sales,
        COALESCE(SUM(amount_paid),0) paid,
        COALESCE(SUM(amount_remaining),0) debt,
        COALESCE(SUM(cost_total),0) costs,
        COUNT(*) count
        FROM sales WHERE business_id=?""", (bid,)).fetchone()
    expenses = conn.execute("SELECT COALESCE(SUM(amount),0) total FROM expenses WHERE business_id=?", (bid,)).fetchone()["total"]
    profit = totals["paid"] - totals["costs"] - expenses
    
    today = conn.execute("""SELECT
        COALESCE(SUM(total_amount),0) sales,
        COALESCE(SUM(amount_paid),0) paid,
        COUNT(*) count
        FROM sales WHERE business_id=? AND date(created_at)=date('now','localtime')""", (bid,)).fetchone()
        
    stock_alerts = conn.execute("""SELECT * FROM products
        WHERE business_id=? AND active=1 AND stock_qty<=reorder_level
        ORDER BY stock_qty ASC LIMIT 8""", (bid,)).fetchall()
        
    debt_customers = conn.execute("""SELECT c.*, COALESCE(SUM(s.amount_remaining),0) debt
        FROM customers c LEFT JOIN sales s ON s.customer_id=c.id
        WHERE c.business_id=? GROUP BY c.id HAVING debt>0
        ORDER BY debt DESC LIMIT 8""", (bid,)).fetchall()
        
    recent = conn.execute("""SELECT s.*, u.email FROM sales s
        LEFT JOIN users u ON u.id=s.user_id
        WHERE s.business_id=? ORDER BY s.id DESC LIMIT 10""", (bid,)).fetchall()
    conn.close()

    insights = []
    if totals["count"]:
        insights.append(f"Jumla ya mauzo yote ni {u['currency']} {totals['sales']:,.0f}.")
    if profit > 0:
        insights.append(f"Makadirio ya faida halisi ni {u['currency']} {profit:,.0f}.")
    if stock_alerts:
        insights.append(f"Kuna bidhaa {len(stock_alerts)} zinazohitaji kuongezwa stoko.")
    if totals["debt"] > 0:
        insights.append(f"Jumla ya madeni ya wateja ni {u['currency']} {totals['debt']:,.0f}.")
        
    return render_template("dashboard.html", totals=totals, expenses=expenses, profit=profit,
                           today=today, stock_alerts=stock_alerts, debt_customers=debt_customers,
                           recent=recent, insights=insights)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pwd = request.form.get("password", "")
        conn = get_db_connection()
        account = conn.execute("SELECT * FROM users WHERE lower(email)=?", (email,)).fetchone()
        if account and account["is_active"] and check_password_hash(account["password"], pwd):
            conn.execute("UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?", (account["id"],))
            conn.commit()
            conn.close()
            session.clear()
            session.update(logged_in=True, username=account["email"], user_id=account["id"],
                           is_admin=int(account["is_admin"]), role=account["role"])
            log_action("login", "user", account["id"], "Uingiaji umefanikiwa")
            return redirect(url_for("index"))
        conn.close()
        return render_template("login.html", error="Barua pepe au nenosiri si sahihi, au akaunti imezimwa.")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        phone = request.form.get("phone_number", "").strip()
        name = request.form.get("business_name", "Mkolani Enterprise").strip()
        btype = request.form.get("business_type", "retail")
        currency = request.form.get("currency", "TZS")
        
        if password != confirm:
            return render_template("register.html", error="Nenosiri hazifanani!")
        if len(password) < 6:
            return render_template("register.html", error="Nenosiri iwe na angalau herufi 6.")
            
        conn = get_db_connection()
        try:
            existing = conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
            role = "master" if existing == 0 else "admin"
            conn.execute("""INSERT INTO users
                (email, password, phone_number, business_name, business_type, currency, is_admin, role)
                VALUES (?,?,?,?,?,?,?,?)""",
                (email, generate_password_hash(password), phone, name, btype, currency, 1 if role == "master" else 0, role))
            uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("""INSERT INTO businesses
                (name, business_type, currency, phone, owner_user_id) VALUES (?,?,?,?,?)""",
                (name, btype, currency, phone, uid))
            bid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("UPDATE users SET business_id=?, owner_user_id=? WHERE id=?", (bid, uid, uid))
            conn.execute("INSERT INTO branches (business_id, name) VALUES (?,?)", (bid, "Main Branch"))
            conn.execute("INSERT INTO sms_wallets (business_id, balance) VALUES (?,0)", (bid,))
            conn.commit()
            conn.close()
            flash("Usajili umefanikiwa! Tafadhali ingia.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            conn.close()
            return render_template("register.html", error="Barua pepe au namba hii ya simu imeshasajiliwa.")
    return render_template("register.html")


@app.route("/logout")
def logout():
    if session.get("logged_in"):
        log_action("logout", "user", session.get("user_id"))
    session.clear()
    return redirect(url_for("login"))


@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        phone = request.form.get("phone_number", "").strip()
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE phone_number=?", (phone,)).fetchone()
        if not user:
            conn.close()
            return render_template("forgot_password.html", error="Namba hii ya simu haijasajiliwa!")
        otp = str(random.randint(100000, 999999))
        conn.execute("UPDATE users SET reset_otp=? WHERE id=?", (otp, user["id"]))
        conn.commit()
        conn.close()
        send_beem_sms(user["id"], phone, f"MKOLANI POS: Kode yako ya kubadilisha nenosiri ni {otp}.")
        session["reset_user_id"] = user["id"]
        return redirect(url_for("reset_password"))
    return render_template("forgot_password.html")


@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    uid = session.get("reset_user_id")
    if not uid:
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        otp = request.form.get("otp", "").strip()
        new_password = request.form.get("new_password", "").strip()
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if user and user["reset_otp"] == otp and len(new_password) >= 6:
            conn.execute("UPDATE users SET password=?, reset_otp=NULL WHERE id=?",
                         (generate_password_hash(new_password), uid))
            conn.commit()
            conn.close()
            session.pop("reset_user_id", None)
            flash("Nenosiri limebadilishwa kikamilifu.", "success")
            return redirect(url_for("login"))
        conn.close()
        return render_template("reset_password.html", error="Kode ya OTP si sahihi au nenosiri ni fupi mno.")
    return render_template("reset_password.html")


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    u = current_user()
    if request.method == "POST":
        name = request.form.get("business_name", u["business_name"]).strip()
        btype = request.form.get("business_type", u["business_type"])
        currency = request.form.get("currency", u["currency"])
        api = request.form.get("beem_api_key", "").strip()
        secret = request.form.get("beem_secret_key", "").strip()
        sender = request.form.get("beem_sender_id", "").strip()
        
        conn = get_db_connection()
        logo_path = u["logo_path"]
        file = request.files.get("logo")
        if file and file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
            if ext in ALLOWED_IMAGE_EXTENSIONS:
                fname = f"logo_{u['id']}.{ext}"
                file.save(os.path.join(UPLOAD_FOLDER, secure_filename(fname)))
                logo_path = f"uploads/{fname}"
                
        conn.execute("""UPDATE users SET business_name=?, business_type=?, currency=?,
            beem_api_key=?, beem_secret_key=?, beem_sender_id=?, logo_path=? WHERE id=?""",
            (name, btype, currency, api, secret, sender, logo_path, u["id"]))
        conn.execute("""UPDATE businesses SET name=?, business_type=?, currency=?, phone=?, logo_path=? WHERE id=?""",
            (name, btype, currency, u["phone_number"], logo_path, u["business_id"]))
        conn.commit()
        conn.close()
        log_action("update_profile", "business", u["business_id"], "Taarifa za biashara zimesasishwa")
        flash("Mipangilio imehifadhiwa vizuri.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=u)


@app.route("/sales", methods=["GET", "POST"])
@login_required
def sales():
    u = current_user()
    bid = u["business_id"]
    conn = get_db_connection()
    if request.method == "POST":
        item = request.form.get("item", "").strip()
        qty = float(request.form.get("qty", 1) or 1)
        total = float(request.form.get("total_amount", 0) or 0)
        cost = float(request.form.get("cost_total", 0) or 0)
        discount = float(request.form.get("discount", 0) or 0)
        paid = float(request.form.get("amount_paid", 0) or 0)
        phone = request.form.get("customer_phone", "").strip()
        cname = request.form.get("customer_name", "Walk-in Customer").strip()
        method = request.form.get("payment_method", "Cash")
        remaining = max(total - discount - paid, 0)
        cash = float(request.form.get("cash_received", 0) or 0)
        change = max(cash - paid, 0)
        
        customer_id = None
        if phone:
            row = conn.execute("SELECT id FROM customers WHERE business_id=? AND phone=?", (bid, phone)).fetchone()
            if row:
                customer_id = row["id"]
            else:
                conn.execute("INSERT INTO customers (business_id, name, phone) VALUES (?,?,?)", (bid, cname, phone))
                customer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                
        conn.execute("""INSERT INTO sales
            (business_id, user_id, customer_id, customer_name, item, qty, total_amount, cost_total, discount,
             amount_paid, amount_remaining, payment_method, cash_received, change_given)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (bid, u["id"], customer_id, cname, item, qty, total, cost, discount, paid, remaining, method, cash, change))
        sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        
        conn.execute("""INSERT INTO receipts
            (user_id, business_type, customer_name, service_or_item, amount_paid, amount_remaining,
             customer_phone, payment_method, cash_received, change_given)
             VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (u["id"], u["business_type"], cname, item, paid, remaining, phone, method, cash, change))
        rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        
        if customer_id:
            conn.execute("INSERT INTO payments (business_id, sale_id, customer_id, user_id, amount, payment_method) VALUES (?,?,?,?,?,?)",
                         (bid, sid, customer_id, u["id"], paid, method))
        conn.commit()
        conn.close()
        
        if phone:
            send_beem_sms(u["id"], phone, f"{u['business_name']}: Risiti #{rid}. {item}: {u['currency']} {paid:,.0f}. Deni: {u['currency']} {remaining:,.0f}. Asante!", bid)
            
        log_action("create_sale", "sale", sid, f"Receipt #{rid}")
        flash(f"Mauzo yamehifadhiwa kikamilifu. Risiti Namba #{rid}", "success")
        return redirect(url_for("sales"))
        
    rows = conn.execute("SELECT * FROM sales WHERE business_id=? ORDER BY id DESC LIMIT 100", (bid,)).fetchall()
    customers = conn.execute("SELECT * FROM customers WHERE business_id=? ORDER BY name", (bid,)).fetchall()
    conn.close()
    return render_template("sales.html", sales=rows, customers=customers)


@app.route("/products", methods=["GET", "POST"])
@login_required
def products():
    u = current_user()
    bid = u["business_id"]
    conn = get_db_connection()
    if request.method == "POST":
        conn.execute("""INSERT INTO products
            (business_id, sku, name, category, unit, cost_price, selling_price, stock_qty, reorder_level)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (bid, request.form.get("sku", "").strip(), request.form.get("name", "").strip(),
             request.form.get("category", "").strip(), request.form.get("unit", "pcs"),
             float(request.form.get("cost_price", 0) or 0), float(request.form.get("selling_price", 0) or 0),
             float(request.form.get("stock_qty", 0) or 0), float(request.form.get("reorder_level", 5) or 5)))
        conn.commit()
        conn.close()
        flash("Bidhaa mpya imeongezwa.", "success")
        return redirect(url_for("products"))
        
    rows = conn.execute("SELECT * FROM products WHERE business_id=? AND active=1 ORDER BY id DESC", (bid,)).fetchall()
    conn.close()
    return render_template("products.html", products=rows)


@app.route("/products/<int:product_id>/stock", methods=["POST"])
@login_required
def stock_adjust(product_id):
    u = current_user()
    bid = u["business_id"]
    qty = float(request.form.get("quantity", 0) or 0)
    movement = request.form.get("movement_type", "in")
    signed = qty if movement == "in" else -qty
    
    conn = get_db_connection()
    p = conn.execute("SELECT * FROM products WHERE id=? AND business_id=?", (product_id, bid)).fetchone()
    if not p:
        conn.close()
        return ("Bidhaa haipatikani", 404)
        
    conn.execute("UPDATE products SET stock_qty=MAX(stock_qty+?,0) WHERE id=?", (signed, product_id))
    conn.execute("""INSERT INTO stock_movements
        (business_id, product_id, user_id, movement_type, quantity, reference, note)
        VALUES (?,?,?,?,?,?,?)""", (bid, product_id, u["id"], movement, qty, "manual", request.form.get("note", "")))
    conn.commit()
    conn.close()
    
    log_action("stock_adjustment", "product", product_id, f"{movement} {qty}")
    flash("Idadi ya stoko imesasishwa.", "success")
    return redirect(url_for("products"))


@app.route("/customers", methods=["GET", "POST"])
@login_required
def customers():
    u = current_user()
    bid = u["business_id"]
    conn = get_db_connection()
    if request.method == "POST":
        conn.execute("INSERT INTO customers (business_id, name, phone, email, address, notes) VALUES (?,?,?,?,?,?)",
                     (bid, request.form.get("name", "").strip(), request.form.get("phone", "").strip(),
                      request.form.get("email", "").strip(), request.form.get("address", "").strip(),
                      request.form.get("notes", "").strip()))
        conn.commit()
        conn.close()
        flash("Mteja mpya ameongezwa.", "success")
        return redirect(url_for("customers"))
        
    rows = conn.execute("""SELECT c.*, COALESCE(SUM(s.amount_remaining),0) debt,
        COALESCE(SUM(s.total_amount),0) purchases
        FROM customers c LEFT JOIN sales s ON s.customer_id=c.id
        WHERE c.business_id=? GROUP BY c.id ORDER BY c.id DESC""", (bid,)).fetchall()
    conn.close()
    return render_template("customers.html", customers=rows)


@app.route("/debts")
@login_required
def debts():
    u = current_user()
    conn = get_db_connection()
    rows = conn.execute("""SELECT s.*, c.phone FROM sales s LEFT JOIN customers c ON c.id=s.customer_id
        WHERE s.business_id=? AND s.amount_remaining>0 ORDER BY s.id DESC""", (u["business_id"],)).fetchall()
    conn.close()
    return render_template("debts.html", debts=rows)


@app.route("/debts/<int:sale_id>/pay", methods=["POST"])
@login_required
def pay_debt(sale_id):
    u = current_user()
    amount = float(request.form.get("amount", 0) or 0)
    method = request.form.get("payment_method", "Cash")
    
    conn = get_db_connection()
    sale = conn.execute("SELECT * FROM sales WHERE id=? AND business_id=?", (sale_id, u["business_id"])).fetchone()
    if not sale or amount <= 0:
        conn.close()
        flash("Kiasi cha malipo si sahihi.", "danger")
        return redirect(url_for("debts"))
        
    amount = min(amount, sale["amount_remaining"])
    conn.execute("UPDATE sales SET amount_paid=amount_paid+?, amount_remaining=amount_remaining-? WHERE id=?", (amount, amount, sale_id))
    conn.execute("INSERT INTO payments (business_id, sale_id, customer_id, user_id, amount, payment_method) VALUES (?,?,?,?,?,?)",
                 (u["business_id"], sale_id, sale["customer_id"], u["id"], amount, method))
                 
    cust = conn.execute("SELECT phone FROM customers WHERE id=?", (sale["customer_id"],)).fetchone() if sale["customer_id"] else None
    conn.commit()
    conn.close()
    
    if cust and cust["phone"]:
        new_balance = max(sale["amount_remaining"] - amount, 0)
        send_beem_sms(u["id"], cust["phone"], f"{u['business_name']}: Malipo ya {u['currency']} {amount:,.0f} yamepokelewa. Salio la deni: {u['currency']} {new_balance:,.0f}.", u["business_id"])
        
    log_action("debt_payment", "sale", sale_id, f"Malipo {amount}")
    flash("Malipo ya deni yamehifadhiwa.", "success")
    return redirect(url_for("debts"))


@app.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses():
    u = current_user()
    conn = get_db_connection()
    if request.method == "POST":
        conn.execute("""INSERT INTO expenses (business_id, user_id, category, description, amount, payment_method)
            VALUES (?,?,?,?,?,?)""", (u["business_id"], u["id"], request.form.get("category", "Other"),
                                     request.form.get("description", ""), float(request.form.get("amount", 0) or 0),
                                     request.form.get("payment_method", "Cash")))
        conn.commit()
        conn.close()
        flash("Matumizi yamehifadhiwa kikamilifu.", "success")
        return redirect(url_for("expenses"))
        
    rows = conn.execute("SELECT e.*, u.email FROM expenses e LEFT JOIN users u ON u.id=e.user_id WHERE e.business_id=? ORDER BY e.id DESC", (u["business_id"],)).fetchall()
    total = conn.execute("SELECT COALESCE(SUM(amount),0) t FROM expenses WHERE business_id=?", (u["business_id"],)).fetchone()["t"]
    conn.close()
    return render_template("expenses.html", expenses=rows, total=total)


@app.route("/sms", methods=["GET", "POST"])
@login_required
def sms_center():
    u = current_user()
    bid = u["business_id"]
    conn = get_db_connection()
    if request.method == "POST":
        recipients = [x.strip() for x in request.form.get("recipients", "").split(",") if x.strip()]
        message = request.form.get("message", "").strip()
        for phone in recipients:
            send_beem_sms(u["id"], phone, message, bid)
        flash(f"SMS {len(recipients)} zimewekwa kwenye foleni ya kutumwa.", "success")
        return redirect(url_for("sms_center"))
        
    wallet = conn.execute("SELECT * FROM sms_wallets WHERE business_id=?", (bid,)).fetchone()
    messages = conn.execute("SELECT * FROM sms_messages WHERE business_id=? ORDER BY id DESC LIMIT 100", (bid,)).fetchall()
    templates = conn.execute("SELECT * FROM sms_templates WHERE business_id=? ORDER BY id DESC", (bid,)).fetchall()
    conn.close()
    return render_template("sms.html", wallet=wallet, messages=messages, templates=templates)


@app.route("/sms/templates/add", methods=["POST"])
@login_required
def add_sms_template():
    u = current_user()
    conn = get_db_connection()
    conn.execute("INSERT INTO sms_templates (business_id, name, message) VALUES (?,?,?)",
                 (u["business_id"], request.form.get("name", "").strip(), request.form.get("message", "").strip()))
    conn.commit()
    conn.close()
    flash("Kiolezo cha SMS kimehifadhiwa.", "success")
    return redirect(url_for("sms_center"))


@app.route("/reports")
@login_required
def reports():
    u = current_user()
    bid = u["business_id"]
    conn = get_db_connection()
    sales = conn.execute("""SELECT date(created_at) day, COALESCE(SUM(total_amount),0) sales,
        COALESCE(SUM(amount_paid),0) paid, COALESCE(SUM(cost_total),0) costs, COUNT(*) count
        FROM sales WHERE business_id=? GROUP BY date(created_at) ORDER BY day DESC LIMIT 31""", (bid,)).fetchall()
    expenses = conn.execute("""SELECT date(created_at) day, COALESCE(SUM(amount),0) total
        FROM expenses WHERE business_id=? GROUP BY date(created_at) ORDER BY day DESC LIMIT 31""", (bid,)).fetchall()
    conn.close()
    return render_template("reports.html", sales=sales, expenses=expenses)


@app.route("/api/insights")
@login_required
def api_insights():
    u = current_user()
    bid = u["business_id"]
    conn = get_db_connection()
    s = conn.execute("SELECT COALESCE(SUM(amount_paid),0) paid, COALESCE(SUM(cost_total),0) costs, COALESCE(SUM(amount_remaining),0) debt FROM sales WHERE business_id=?", (bid,)).fetchone()
    e = conn.execute("SELECT COALESCE(SUM(amount),0) x FROM expenses WHERE business_id=?", (bid,)).fetchone()["x"]
    low = conn.execute("SELECT COUNT(*) n FROM products WHERE business_id=? AND active=1 AND stock_qty<=reorder_level", (bid,)).fetchone()["n"]
    conn.close()
    return jsonify({
        "summary": [
            f"Mauzo yaliyolipwa: {u['currency']} {s['paid']:,.0f}",
            f"Madeni yanayodaiwa: {u['currency']} {s['debt']:,.0f}",
            f"Makadirio ya faida: {u['currency']} {s['paid']-s['costs']-e:,.0f}",
            f"Bidhaa zenye stoko ndogo: {low}"
        ]
    })


@app.route("/admin", methods=["GET", "POST"])
@master_required
def admin_dashboard():
    conn = get_db_connection()
    pin = conn.execute("SELECT admin_pin FROM settings WHERE id=1").fetchone()["admin_pin"]
    if request.method == "POST":
        if request.form.get("admin_password", "").strip() != pin:
            conn.close()
            return render_template("admin_dashboard.html", locked=True, error="Master PIN si sahihi.")
        session["admin_unlocked"] = True
        
    if not session.get("admin_unlocked"):
        conn.close()
        return render_template("admin_dashboard.html", locked=True)
        
    users = conn.execute("""SELECT u.*, b.name business FROM users u
        LEFT JOIN businesses b ON b.id=u.business_id ORDER BY u.id DESC""").fetchall()
    businesses = conn.execute("SELECT * FROM businesses ORDER BY id DESC").fetchall()
    feed = conn.execute("""SELECT a.*, u.email FROM audit_logs a LEFT JOIN users u ON u.id=a.user_id
        ORDER BY a.id DESC LIMIT 100""").fetchall()
    sms = conn.execute("""SELECT COALESCE(SUM(cost),0) cost, COALESCE(SUM(selling_price),0) revenue,
        COUNT(*) count FROM sms_messages""").fetchone()
    conn.close()
    return render_template("admin_dashboard.html", locked=False, users=users, businesses=businesses, feed=feed, sms=sms)


@app.route("/admin/users/add", methods=["POST"])
@master_required
def admin_add_user():
    u = current_user()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    phone = request.form.get("phone_number", "").strip()
    role = request.form.get("role", "staff")
    business_id_value = int(request.form.get("business_id") or u["business_id"])
    
    conn = get_db_connection()
    try:
        conn.execute("""INSERT INTO users (email, password, phone_number, business_id, owner_user_id, role, is_admin)
            VALUES (?,?,?,?,?,?,?)""", (email, generate_password_hash(password), phone, business_id_value, u["id"], role, 1 if role in ("master", "admin") else 0))
        conn.commit()
        conn.close()
        log_action("add_user", "user", None, email)
        flash("Mtumiaji mpya ameongezwa.", "success")
    except sqlite3.IntegrityError:
        conn.close()
        flash("Barua pepe au namba ya simu tayari imeshasajiliwa.", "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@master_required
def admin_toggle_user(user_id):
    conn = get_db_connection()
    row = conn.execute("SELECT is_active FROM users WHERE id=?", (user_id,)).fetchone()
    if row:
        conn.execute("UPDATE users SET is_active=? WHERE id=?", (0 if row["is_active"] else 1, user_id))
        conn.commit()
    conn.close()
    log_action("toggle_user", "user", user_id)
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/users/<int:user_id>/role", methods=["POST"])
@master_required
def admin_role(user_id):
    role = request.form.get("role", "staff")
    if role not in ("admin", "manager", "staff"):
        role = "staff"
    conn = get_db_connection()
    conn.execute("UPDATE users SET role=?, is_admin=? WHERE id=?", (role, 1 if role == "admin" else 0, user_id))
    conn.commit()
    conn.close()
    log_action("change_role", "user", user_id, role)
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/pin", methods=["POST"])
@master_required
def update_admin_pin():
    newpin = request.form.get("new_pin", "").strip()
    if len(newpin) < 4:
        flash("PIN lazima iwe na angalau tarakimu 4.", "danger")
    else:
        conn = get_db_connection()
        conn.execute("UPDATE settings SET admin_pin=? WHERE id=1", (newpin,))
        conn.commit()
        conn.close()
        flash("Master PIN imebadilishwa kikamilifu.", "success")
        log_action("change_master_pin", "settings", 1)
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/sms-wallet/<int:bid>", methods=["POST"])
@master_required
def topup_sms(bid):
    amount = float(request.form.get("amount", 0) or 0)
    conn = get_db_connection()
    conn.execute("""INSERT OR IGNORE INTO sms_wallets (business_id, balance, total_purchased)
        VALUES (?,?,0)""", (bid, 0))
    conn.execute("""UPDATE sms_wallets SET balance=balance+?, total_purchased=total_purchased+?, updated_at=CURRENT_TIMESTAMP
        WHERE business_id=?""", (amount, amount, bid))
    conn.commit()
    conn.close()
    log_action("sms_wallet_topup", "business", bid, str(amount))
    flash("Salio la SMS limeongezwa kikamilifu.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/receipt/<int:receipt_id>")
@login_required
def receipt_view(receipt_id):
    u = current_user()
    conn = get_db_connection()
    r = conn.execute("""SELECT r.*, u.business_name, u.phone_number, u.logo_path, u.currency
        FROM receipts r JOIN users u ON u.id=r.user_id
        WHERE r.id=? AND r.user_id=?""", (receipt_id, u["id"])).fetchone()
    conn.close()
    if not r:
        return ("Risiti haipatikani.", 404)
    return render_template("receipt_view.html", receipt=r)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "app": "Mkolani POS", "time": datetime.utcnow().isoformat()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
