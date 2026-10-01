import os
import re
import base64
import hashlib
from datetime import datetime, timedelta

import requests
from cryptography.fernet import Fernet

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import inspect, text, func

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'mkolani-secret-key-2026')

# ==========================================================
# DATABASE CONFIGURATION
# ==========================================================
db_url = os.environ.get('DATABASE_URL', 'sqlite:///mkolani_pos.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'warning'


def now_tz():
    """Muda wa Tanzania (UTC+3), kwa sababu seva ya Render iko UTC."""
    return datetime.utcnow() + timedelta(hours=3)


# ==========================================================
# MODELS
# ==========================================================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(150), nullable=False)
    owner_name = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.Text, nullable=False)
    business_type = db.Column(db.String(50), default='retail')
    role = db.Column(db.String(20), default='user')


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(150), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    total_spent = db.Column(db.Float, default=0.0)
    debt = db.Column(db.Float, default=0.0)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    buy_price = db.Column(db.Float, default=0.0)
    sell_price = db.Column(db.Float, default=0.0)
    stock = db.Column(db.Integer, default=0)
    min_stock = db.Column(db.Integer, default=5)
    created_at = db.Column(db.DateTime, default=now_tz)


class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receipt_no = db.Column(db.String(30), nullable=True)
    customer_id = db.Column(db.Integer, nullable=True)
    customer_name = db.Column(db.String(150), default='Cash Customer')
    customer_phone = db.Column(db.String(20), nullable=True)
    payment_method = db.Column(db.String(50), default='CASH')
    total = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=now_tz)
    items = db.relationship('SaleItem', backref='sale', cascade='all, delete-orphan')


class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sale.id'), nullable=False)
    product_id = db.Column(db.Integer, nullable=True)
    name = db.Column(db.String(150), nullable=False)
    price = db.Column(db.Float, default=0.0)
    cost = db.Column(db.Float, default=0.0)
    qty = db.Column(db.Integer, default=1)
    total = db.Column(db.Float, default=0.0)


class Debt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    customer_id = db.Column(db.Integer, nullable=True)
    sale_id = db.Column(db.Integer, nullable=True)
    customer_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    amount = db.Column(db.Float, default=0.0)
    paid = db.Column(db.Float, default=0.0)
    interest_rate = db.Column(db.Float, default=0.0)
    note = db.Column(db.String(250), nullable=True)
    due_date = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=now_tz)

    @property
    def balance(self):
        return max((self.amount or 0) - (self.paid or 0), 0)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    amount = db.Column(db.Float, default=0.0)
    note = db.Column(db.String(250), nullable=True)
    created_at = db.Column(db.DateTime, default=now_tz)


class SmsSettings(db.Model):
    """Funguo za Beem za kila mtumiaji (zimefichwa kwa encryption)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    api_key_enc = db.Column(db.Text, nullable=True)
    secret_key_enc = db.Column(db.Text, nullable=True)
    sender_id = db.Column(db.String(20), default='INFO')
    updated_at = db.Column(db.DateTime, default=now_tz)


class SmsLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient = db.Column(db.String(120), nullable=True)
    count = db.Column(db.Integer, default=1)
    parts = db.Column(db.Integer, default=1)
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='sent')
    detail = db.Column(db.String(250), nullable=True)
    request_id = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=now_tz)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except Exception:
        return None


# ==========================================================
# SAFE MIGRATION: meza mpya + columns mpya, bila kufuta data
# ==========================================================
def safe_migrate():
    db.create_all()
    inspector = inspect(db.engine)
    for table_name, table in db.metadata.tables.items():
        if not inspector.has_table(table_name):
            continue
        existing = {c['name'] for c in inspector.get_columns(table_name)}
        for col in table.columns:
            if col.name not in existing:
                col_type = col.type.compile(db.engine.dialect)
                stmt = f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {col_type}'
                try:
                    with db.engine.begin() as conn:
                        conn.execute(text(stmt))
                    print(f"Column mpya: {table_name}.{col.name}")
                except Exception as e:
                    print(f"Migration error {table_name}.{col.name}: {e}")


with app.app_context():
    try:
        safe_migrate()
    except Exception as e:
        print(f"Error creating database tables: {e}")


# ==========================================================
# HELPERS
# ==========================================================
@app.context_processor
def inject_endpoints():
    return dict(endpoints=[rule.endpoint for rule in app.url_map.iter_rules()])


@app.template_filter('money')
def money(value):
    try:
        return f"{float(value or 0):,.0f}"
    except Exception:
        return "0"


def num(value, default=0.0):
    try:
        return float(str(value).replace(',', '').strip())
    except Exception:
        return default


def own_or_404(model, obj_id):
    obj = model.query.filter_by(id=obj_id, user_id=current_user.id).first()
    if not obj:
        abort(404)
    return obj


def period_start(period):
    today = now_tz().replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'today':
        return today
    if period == 'week':
        return today - timedelta(days=6)
    if period == 'month':
        return today.replace(day=1)
    return None


# ==========================================================
# AUTH & PUBLIC
# ==========================================================
@app.route('/')
def index():
    if current_user.is_authenticated:
        stats = {}
        try:
            today = period_start('today')
            uid = current_user.id
            stats['today_sales'] = db.session.query(func.coalesce(func.sum(Sale.total), 0)).filter(
                Sale.user_id == uid, Sale.created_at >= today).scalar()
            stats['today_count'] = Sale.query.filter(Sale.user_id == uid, Sale.created_at >= today).count()
            stats['products'] = Product.query.filter_by(user_id=uid).count()
            stats['customers'] = Customer.query.filter_by(user_id=uid).count()
            stats['low_stock'] = Product.query.filter(Product.user_id == uid, Product.stock <= Product.min_stock).count()
            debts = Debt.query.filter_by(user_id=uid).all()
            stats['debts'] = sum(d.balance for d in debts)
            stats['expenses_month'] = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
                Expense.user_id == uid, Expense.created_at >= period_start('month')).scalar()
        except Exception as e:
            print(f"Dashboard stats error: {e}")
        return render_template('dashboard.html', stats=stats)
    return render_template('base.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            business_name = request.form.get('business_name')
            owner_name = request.form.get('owner_name')
            phone = request.form.get('phone')
            email = request.form.get('email', '').lower().strip()
            password = request.form.get('password')
            business_type = request.form.get('business_type', 'retail')

            if not email or not password or not business_name:
                flash('Tafadhali jaza taarifa zote zinazohitajika.', 'danger')
                return redirect(url_for('register'))

            if User.query.filter_by(email=email).first():
                flash('Barua pepe hii tayari imeshasajiliwa! Tafadhali ingia.', 'warning')
                return redirect(url_for('login'))

            new_user = User(
                business_name=business_name,
                owner_name=owner_name,
                phone=phone,
                email=email,
                password=generate_password_hash(password, method='pbkdf2:sha256'),
                business_type=business_type
            )
            db.session.add(new_user)
            db.session.commit()

            login_user(new_user)
            flash(f'Hongera {business_name}! Usajili umekamilika. Karibu kwenye Mkolani POS!', 'success')
            return redirect(url_for('index'))

        except Exception as e:
            db.session.rollback()
            print(f"Register error: {e}")
            flash('Kuna tatizo limetokea wakati wa usajili. Tafadhali jaribu tena.', 'danger')
            return redirect(url_for('register'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            email = request.form.get('email', '').lower().strip()
            password = request.form.get('password')
            user = User.query.filter_by(email=email).first()

            if user and check_password_hash(user.password, password):
                login_user(user)
                flash('Karibu tena kwenye Mkolani POS!', 'success')
                return redirect(url_for('index'))
            flash('Barua pepe au Neno la Siri sio sahihi.', 'danger')
            return redirect(url_for('login'))
        except Exception as e:
            print(f"Login error: {e}")
            flash('Kuna tatizo limetokea wakati wa kuingia. Jaribu tena.', 'danger')
            return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Umetoka kwenye mfumo kikamilifu.', 'info')
    return redirect(url_for('index'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        flash('Ombi lako limepokelewa. Wasiliana na msaada kupitia WhatsApp (+255 625 567 603) kwa usaidizi wa haraka.', 'info')
    return redirect(url_for('index'))


# ==========================================================
# MAUZO & RISITI (POS)
# ==========================================================
@app.route('/sales')
@login_required
def sales():
    customers_list = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.name).all()
    products_list = Product.query.filter_by(user_id=current_user.id).order_by(Product.name).all()
    recent_sales = Sale.query.filter_by(user_id=current_user.id).order_by(Sale.id.desc()).limit(10).all()
    return render_template('sales.html', customers_list=customers_list,
                           products_list=products_list, recent_sales=recent_sales)


@app.route('/sales/save', methods=['POST'])
@login_required
def sales_save():
    data = request.get_json(silent=True) or {}
    items = data.get('items') or []
    if not items:
        return jsonify(ok=False, error='Kikapu kiko wazi.'), 400

    payment = str(data.get('payment_method') or 'CASH')[:50]
    cust_name = (data.get('customer_name') or 'Cash Customer').strip()[:150] or 'Cash Customer'
    cust_phone = (data.get('customer_phone') or '').strip()[:20]
    is_credit = payment.upper().startswith('DENI')

    try:
        customer = None
        cid = data.get('customer_id')
        if cid:
            customer = Customer.query.filter_by(id=int(cid), user_id=current_user.id).first()
            if customer:
                cust_name = customer.name
                cust_phone = cust_phone or customer.phone

        if is_credit and not customer and cust_name == 'Cash Customer':
            raise ValueError('Kwa mauzo ya DENI, chagua mteja aliyesajiliwa au andika jina la mteja.')

        sale = Sale(user_id=current_user.id, customer_id=customer.id if customer else None,
                    customer_name=cust_name, customer_phone=cust_phone, payment_method=payment)
        total = 0.0

        for it in items:
            name = str(it.get('name', '')).strip()[:150]
            qty = int(it.get('qty', 0))
            price = float(it.get('price', 0))
            if not name or qty <= 0 or price <= 0:
                raise ValueError('Kuna bidhaa yenye taarifa zisizo sahihi.')

            product, cost = None, 0.0
            pid = it.get('product_id')
            if pid:
                product = Product.query.filter_by(id=int(pid), user_id=current_user.id).first()
            if product:
                if (product.stock or 0) < qty:
                    raise ValueError(f'Stoko ya "{product.name}" haitoshi. Iliyobaki: {product.stock}.')
                product.stock = (product.stock or 0) - qty
                cost = product.buy_price or 0.0

            sale.items.append(SaleItem(product_id=product.id if product else None, name=name,
                                       price=price, cost=cost, qty=qty, total=price * qty))
            total += price * qty

        sale.total = total
        db.session.add(sale)
        db.session.flush()
        sale.receipt_no = f"MKL-{sale.id:06d}"

        if customer:
            customer.total_spent = (customer.total_spent or 0) + total

        if is_credit:
            db.session.add(Debt(user_id=current_user.id, customer_id=customer.id if customer else None,
                                sale_id=sale.id, customer_name=cust_name, phone=cust_phone,
                                amount=total, paid=0, note=f'Deni la risiti {sale.receipt_no}'))
            if customer:
                customer.debt = (customer.debt or 0) + total

        db.session.commit()
        return jsonify(ok=True, receipt_no=sale.receipt_no, total=total,
                       date=sale.created_at.strftime('%d/%m/%Y %H:%M'))

    except ValueError as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:
        db.session.rollback()
        print(f"Sale save error: {e}")
        return jsonify(ok=False, error='Kuna tatizo la seva. Jaribu tena.'), 500


@app.route('/receipt/<int:sale_id>')
@login_required
def receipt(sale_id):
    sale = own_or_404(Sale, sale_id)
    return render_template('receipt.html', sale=sale)


@app.route('/sales/<int:sale_id>/delete', methods=['POST'])
@login_required
def sale_delete(sale_id):
    """Futa mauzo na rudisha stoko."""
    sale = own_or_404(Sale, sale_id)
    try:
        for it in sale.items:
            if it.product_id:
                p = Product.query.filter_by(id=it.product_id, user_id=current_user.id).first()
                if p:
                    p.stock = (p.stock or 0) + it.qty
        if sale.customer_id:
            c = Customer.query.filter_by(id=sale.customer_id, user_id=current_user.id).first()
            if c:
                c.total_spent = max((c.total_spent or 0) - sale.total, 0)
        for d in Debt.query.filter_by(user_id=current_user.id, sale_id=sale.id).all():
            if d.customer_id:
                c = Customer.query.filter_by(id=d.customer_id, user_id=current_user.id).first()
                if c:
                    c.debt = max((c.debt or 0) - d.balance, 0)
            db.session.delete(d)
        db.session.delete(sale)
        db.session.commit()
        flash('Mauzo yamefutwa na stoko imerudishwa.', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"Sale delete error: {e}")
        flash('Imeshindikana kufuta mauzo.', 'danger')
    return redirect(request.referrer or url_for('reports'))


# ==========================================================
# SMS CENTER (BEEM SMS) - kila mtumiaji anaweka funguo zake
# ==========================================================
BEEM_SEND_URL = 'https://apisms.beem.africa/v1/send'
BEEM_BALANCE_URL = 'https://apisms.beem.africa/public/v1/vendors/balance'
SMS_BATCH_SIZE = 100
SMS_MAX_RECIPIENTS = 500


def _fernet():
    seed = os.environ.get('ENCRYPTION_KEY') or app.config['SECRET_KEY']
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(seed.encode()).digest()))


def enc(value):
    return _fernet().encrypt(value.encode()).decode()


def dec(value):
    try:
        return _fernet().decrypt(value.encode()).decode()
    except Exception:
        return None


def get_sms_creds(user_id):
    """Rudisha (api_key, secret, sender_id) au None kama hazijawekwa / haziwezi kusomwa."""
    s = SmsSettings.query.filter_by(user_id=user_id).first()
    if not s or not s.api_key_enc or not s.secret_key_enc:
        return None
    key, secret = dec(s.api_key_enc), dec(s.secret_key_enc)
    if not key or not secret:
        return None
    return key, secret, (s.sender_id or 'INFO')


def normalize_phone(raw):
    """Badilisha namba za Tanzania kuwa muundo wa 255XXXXXXXXX. Rudisha None kama si sahihi."""
    d = re.sub(r'\D', '', str(raw or ''))
    if d.startswith('255') and len(d) == 12:
        return d
    if d.startswith('0') and len(d) == 10:
        return '255' + d[1:]
    if len(d) == 9 and d[0] in '67':
        return '255' + d
    return None


_SMS_CHAR_MAP = {'\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
                 '\u2013': '-', '\u2014': '-', '\u2026': '...', '\u00a0': ' '}


def clean_sms_text(text_in):
    t = ''.join(_SMS_CHAR_MAP.get(ch, ch) for ch in (text_in or '')).strip()
    if any(ord(ch) > 126 for ch in t):
        return None
    return t


def sms_parts(message):
    n = len(message)
    return 1 if n <= 160 else -(-n // 153)


def beem_send(creds, numbers, message):
    """Tuma kwa Beem. Rudisha (ok, ujumbe, request_id, valid_count)."""
    api_key, secret, sender = creds
    payload = {
        "source_addr": sender,
        "schedule_time": "",
        "encoding": 0,
        "message": message,
        "recipients": [{"recipient_id": i + 1, "dest_addr": n} for i, n in enumerate(numbers)],
    }
    try:
        r = requests.post(BEEM_SEND_URL, json=payload, auth=(api_key, secret), timeout=20)
    except requests.RequestException as e:
        print(f"Beem send network error: {e}")
        return False, 'Imeshindikana kuwasiliana na Beem (mtandao). Jaribu tena.', None, 0
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code in (401, 403):
        return False, 'Beem imekataa funguo zako (API Key / Secret Key si sahihi).', None, 0
    ok = r.status_code == 200 and (data.get('successful') is True or data.get('code') == 100)
    msg = str(data.get('message') or data.get('error') or f'HTTP {r.status_code}')
    return ok, msg, data.get('request_id'), data.get('valid')


def beem_balance(creds):
    """Rudisha (salio, kosa). kosa ni 'auth', 'network' au 'format' kama imeshindikana."""
    api_key, secret, _ = creds
    try:
        r = requests.get(BEEM_BALANCE_URL, auth=(api_key, secret), timeout=10)
    except requests.RequestException:
        return None, 'network'
    if r.status_code in (401, 403):
        return None, 'auth'
    try:
        data = r.json()
        block = data.get('data', data) if isinstance(data, dict) else {}
        for k in ('credit_balance', 'balance'):
            if k in block:
                return float(block[k]), None
    except Exception:
        pass
    return None, 'format'


@app.route('/sms-center')
@login_required
def sms_center():
    uid = current_user.id
    try:
        customers_list = Customer.query.filter_by(user_id=uid).order_by(Customer.name).all()
        logs = SmsLog.query.filter_by(user_id=uid).order_by(SmsLog.id.desc()).limit(30).all()
        sent_total = db.session.query(func.coalesce(func.sum(SmsLog.count * SmsLog.parts), 0)).filter(
            SmsLog.user_id == uid, SmsLog.status == 'sent').scalar()
        failed_total = db.session.query(func.coalesce(func.sum(SmsLog.count), 0)).filter(
            SmsLog.user_id == uid, SmsLog.status == 'failed').scalar()
    except Exception as e:
        print(f"SMS center load error: {e}")
        customers_list, logs, sent_total, failed_total = [], [], 0, 0

    settings = SmsSettings.query.filter_by(user_id=uid).first()
    creds = get_sms_creds(uid)
    masked_key = ''
    if creds:
        k = creds[0]
        masked_key = (k[:4] + '*' * 6 + k[-3:]) if len(k) > 8 else '*' * len(k)
    return render_template('sms_center.html', customers_list=customers_list, logs=logs,
                           configured=bool(creds), masked_key=masked_key,
                           sender_id=(settings.sender_id if settings else 'INFO'),
                           key_unreadable=bool(settings and settings.api_key_enc and not creds),
                           sent_total=sent_total, failed_total=failed_total)


@app.route('/sms-center/settings', methods=['POST'])
@login_required
def sms_settings():
    api_key = (request.form.get('api_key') or '').strip()
    secret = (request.form.get('secret_key') or '').strip()
    sender = (request.form.get('sender_id') or 'INFO').strip() or 'INFO'

    if not re.fullmatch(r'[A-Za-z0-9 ]{1,11}', sender):
        flash('Sender ID iwe herufi/namba 1 hadi 11 tu, bila alama maalum.', 'warning')
        return redirect(url_for('sms_center'))

    s = SmsSettings.query.filter_by(user_id=current_user.id).first()
    if not s:
        s = SmsSettings(user_id=current_user.id)
        db.session.add(s)

    if api_key:
        s.api_key_enc = enc(api_key)
    if secret:
        s.secret_key_enc = enc(secret)
    s.sender_id = sender
    s.updated_at = now_tz()

    if not s.api_key_enc or not s.secret_key_enc:
        db.session.rollback()
        flash('Weka API Key na Secret Key zote mbili kutoka Beem.', 'warning')
        return redirect(url_for('sms_center'))

    db.session.commit()

    creds = get_sms_creds(current_user.id)
    balance, err = beem_balance(creds)
    if err == 'auth':
        flash('Funguo zimehifadhiwa, lakini Beem imezikataa. Hakikisha umenakili API Key na Secret Key sahihi.', 'danger')
    elif err == 'network':
        flash('Funguo zimehifadhiwa, lakini sikuweza kuwasiliana na Beem kuzithibitisha sasa.', 'warning')
    else:
        flash('Funguo za Beem zimehifadhiwa na kuthibitishwa.', 'success')
    return redirect(url_for('sms_center'))


@app.route('/sms-center/settings/delete', methods=['POST'])
@login_required
def sms_settings_delete():
    s = SmsSettings.query.filter_by(user_id=current_user.id).first()
    if s:
        db.session.delete(s)
        db.session.commit()
    flash('Funguo za Beem zimeondolewa.', 'success')
    return redirect(url_for('sms_center'))


@app.route('/sms-center/balance')
@login_required
def sms_balance():
    creds = get_sms_creds(current_user.id)
    if not creds:
        return jsonify(ok=False, error='not_configured')
    balance, err = beem_balance(creds)
    if err:
        return jsonify(ok=False, error=err)
    return jsonify(ok=True, balance=balance)


@app.route('/sms-center/send', methods=['POST'])
@login_required
def sms_send():
    creds = get_sms_creds(current_user.id)
    if not creds:
        flash('Weka funguo zako za Beem kwanza kabla ya kutuma SMS.', 'warning')
        return redirect(url_for('sms_center'))

    message = clean_sms_text(request.form.get('message'))
    if message is None:
        flash('Ujumbe una herufi/alama zisizoruhusiwa (emoji au herufi maalum). Tumia herufi za kawaida tu.', 'warning')
        return redirect(url_for('sms_center'))
    if not message:
        flash('Tafadhali andika ujumbe wa SMS.', 'warning')
        return redirect(url_for('sms_center'))

    rtype = request.form.get('recipient_type', 'all')
    raw_numbers, label = [], ''
    if rtype == 'all':
        custs = Customer.query.filter_by(user_id=current_user.id).all()
        raw_numbers = [c.phone for c in custs]
        label = f'Wateja Wote ({len(custs)})'
    elif rtype == 'single':
        raw_numbers = [request.form.get('single_customer')]
    else:
        raw_numbers = re.split(r'[,\n;\s]+', request.form.get('custom_phones') or '')

    numbers, invalid = [], 0
    for raw in raw_numbers:
        if not raw:
            continue
        n = normalize_phone(raw)
        if n is None:
            invalid += 1
        elif n not in numbers:
            numbers.append(n)

    if not numbers:
        flash('Hakuna namba sahihi ya kutuma. Namba ziwe kama 0768XXXXXX au 255768XXXXXX.', 'warning')
        return redirect(url_for('sms_center'))
    if len(numbers) > SMS_MAX_RECIPIENTS:
        flash(f'Unaweza kutuma kwa watu {SMS_MAX_RECIPIENTS} kwa wakati mmoja. Gawanya orodha.', 'warning')
        return redirect(url_for('sms_center'))

    if not label:
        label = numbers[0] if len(numbers) == 1 else f'Namba {len(numbers)}'

    parts = sms_parts(message)
    sent_count, failed_count, last_msg, first_error = 0, 0, '', ''
    for i in range(0, len(numbers), SMS_BATCH_SIZE):
        batch = numbers[i:i + SMS_BATCH_SIZE]
        ok, msg, req_id, _valid = beem_send(creds, batch, message)
        last_msg = msg
        db.session.add(SmsLog(user_id=current_user.id, recipient=label, count=len(batch), parts=parts,
                              message=message, status='sent' if ok else 'failed',
                              detail=msg[:250], request_id=str(req_id) if req_id else None))
        if ok:
            sent_count += len(batch)
        else:
            failed_count += len(batch)
            first_error = first_error or msg
    db.session.commit()

    if sent_count and not failed_count:
        extra = f' ({invalid} namba zisizo sahihi ziliachwa)' if invalid else ''
        flash(f'SMS zimewasilishwa kwa Beem kwa watu {sent_count}{extra}. Zitafika kwa simu muda mfupi.', 'success')
    elif sent_count:
        flash(f'Zimetumwa {sent_count}, zimeshindwa {failed_count}. Sababu: {first_error}', 'warning')
    else:
        flash(f'SMS hazikutumwa. Sababu kutoka Beem: {first_error or last_msg}', 'danger')
    return redirect(url_for('sms_center'))


# ==========================================================
# WATEJA (CRM)
# ==========================================================
@app.route('/customers', methods=['GET', 'POST'])
@login_required
def customers():
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        if name and phone:
            db.session.add(Customer(
                user_id=current_user.id, name=name, phone=phone,
                email=request.form.get('email'), address=request.form.get('address'),
                notes=request.form.get('notes')))
            db.session.commit()
            flash('Mteja amesajiliwa kikamilifu!', 'success')
        else:
            flash('Jina na simu vinahitajika.', 'warning')
        return redirect(url_for('customers'))

    customers_list = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.name).all()
    return render_template('customers.html', customers_list=customers_list)


@app.route('/customers/<int:cid>/edit', methods=['POST'])
@login_required
def customer_edit(cid):
    c = own_or_404(Customer, cid)
    name = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    if not name or not phone:
        flash('Jina na simu vinahitajika.', 'warning')
        return redirect(url_for('customers'))
    c.name, c.phone = name, phone
    c.email = request.form.get('email')
    c.address = request.form.get('address')
    c.notes = request.form.get('notes')
    db.session.commit()
    flash('Taarifa za mteja zimebadilishwa.', 'success')
    return redirect(url_for('customers'))


@app.route('/customers/<int:cid>/delete', methods=['POST'])
@login_required
def customer_delete(cid):
    c = own_or_404(Customer, cid)
    db.session.delete(c)
    db.session.commit()
    flash('Mteja amefutwa.', 'success')
    return redirect(url_for('customers'))


# ==========================================================
# STOKO & BIDHAA
# ==========================================================
@app.route('/products', methods=['GET', 'POST'])
@login_required
def products():
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        if not name:
            flash('Jina la bidhaa linahitajika.', 'warning')
            return redirect(url_for('products'))
        db.session.add(Product(
            user_id=current_user.id, name=name[:150],
            category=(request.form.get('category') or '').strip()[:100],
            buy_price=num(request.form.get('buy_price')),
            sell_price=num(request.form.get('sell_price')),
            stock=int(num(request.form.get('stock'))),
            min_stock=int(num(request.form.get('min_stock'), 5))))
        db.session.commit()
        flash('Bidhaa imeongezwa kwenye stoko!', 'success')
        return redirect(url_for('products'))

    products_list = Product.query.filter_by(user_id=current_user.id).order_by(Product.name).all()
    stock_value = sum((p.stock or 0) * (p.buy_price or 0) for p in products_list)
    low_count = sum(1 for p in products_list if (p.stock or 0) <= (p.min_stock or 0))
    return render_template('products.html', products_list=products_list,
                           stock_value=stock_value, low_count=low_count)


@app.route('/products/<int:pid>/edit', methods=['POST'])
@login_required
def product_edit(pid):
    p = own_or_404(Product, pid)
    name = (request.form.get('name') or '').strip()
    if not name:
        flash('Jina la bidhaa linahitajika.', 'warning')
        return redirect(url_for('products'))
    p.name = name[:150]
    p.category = (request.form.get('category') or '').strip()[:100]
    p.buy_price = num(request.form.get('buy_price'))
    p.sell_price = num(request.form.get('sell_price'))
    p.stock = int(num(request.form.get('stock')))
    p.min_stock = int(num(request.form.get('min_stock'), 5))
    db.session.commit()
    flash('Bidhaa imebadilishwa.', 'success')
    return redirect(url_for('products'))


@app.route('/products/<int:pid>/restock', methods=['POST'])
@login_required
def product_restock(pid):
    p = own_or_404(Product, pid)
    qty = int(num(request.form.get('qty')))
    if qty <= 0:
        flash('Weka idadi sahihi ya kuongeza.', 'warning')
    else:
        p.stock = (p.stock or 0) + qty
        db.session.commit()
        flash(f'Stoko ya {p.name} imeongezeka kwa {qty}.', 'success')
    return redirect(url_for('products'))


@app.route('/products/<int:pid>/delete', methods=['POST'])
@login_required
def product_delete(pid):
    p = own_or_404(Product, pid)
    db.session.delete(p)
    db.session.commit()
    flash('Bidhaa imefutwa.', 'success')
    return redirect(url_for('products'))


# ==========================================================
# MIKOPO & MADENI
# ==========================================================
@app.route('/debts', methods=['GET', 'POST'])
@login_required
def debts():
    if request.method == 'POST':
        cid = request.form.get('customer_id')
        customer = None
        if cid:
            customer = Customer.query.filter_by(id=int(cid), user_id=current_user.id).first()
        name = customer.name if customer else (request.form.get('customer_name') or '').strip()
        amount = num(request.form.get('amount'))
        if not name or amount <= 0:
            flash('Jina la mdaiwa na kiasi sahihi vinahitajika.', 'warning')
            return redirect(url_for('debts'))
        rate = num(request.form.get('interest_rate'))
        total = round(amount + amount * rate / 100.0)
        db.session.add(Debt(
            user_id=current_user.id, customer_id=customer.id if customer else None,
            customer_name=name[:150],
            phone=(customer.phone if customer else (request.form.get('phone') or '').strip())[:20],
            amount=total, paid=0, interest_rate=rate,
            note=(request.form.get('note') or '').strip()[:250],
            due_date=(request.form.get('due_date') or '').strip()[:20]))
        if customer:
            customer.debt = (customer.debt or 0) + total
        db.session.commit()
        flash('Deni/Mkopo umerekodiwa.', 'success')
        return redirect(url_for('debts'))

    customers_list = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.name).all()
    debts_list = Debt.query.filter_by(user_id=current_user.id).order_by(Debt.id.desc()).all()
    total_owed = sum(d.balance for d in debts_list)
    total_paid = sum(d.paid or 0 for d in debts_list)
    return render_template('debts.html', debts_list=debts_list, customers_list=customers_list,
                           total_owed=total_owed, total_paid=total_paid)


@app.route('/debts/<int:did>/pay', methods=['POST'])
@login_required
def debt_pay(did):
    d = own_or_404(Debt, did)
    amount = num(request.form.get('amount'))
    if amount <= 0:
        flash('Weka kiasi sahihi cha malipo.', 'warning')
    elif amount > d.balance + 0.001:
        flash(f'Kiasi kinazidi deni lililobaki (TZS {d.balance:,.0f}).', 'warning')
    else:
        d.paid = (d.paid or 0) + amount
        if d.customer_id:
            c = Customer.query.filter_by(id=d.customer_id, user_id=current_user.id).first()
            if c:
                c.debt = max((c.debt or 0) - amount, 0)
        db.session.commit()
        flash(f'Malipo ya TZS {amount:,.0f} yamepokelewa.', 'success')
    return redirect(url_for('debts'))


@app.route('/debts/<int:did>/delete', methods=['POST'])
@login_required
def debt_delete(did):
    d = own_or_404(Debt, did)
    if d.customer_id:
        c = Customer.query.filter_by(id=d.customer_id, user_id=current_user.id).first()
        if c:
            c.debt = max((c.debt or 0) - d.balance, 0)
    db.session.delete(d)
    db.session.commit()
    flash('Rekodi ya deni imefutwa.', 'success')
    return redirect(url_for('debts'))


# ==========================================================
# MATUMIZI
# ==========================================================
@app.route('/expenses', methods=['GET', 'POST'])
@login_required
def expenses():
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        amount = num(request.form.get('amount'))
        if not title or amount <= 0:
            flash('Maelezo na kiasi sahihi vinahitajika.', 'warning')
            return redirect(url_for('expenses'))
        db.session.add(Expense(user_id=current_user.id, title=title[:150],
                               category=(request.form.get('category') or '').strip()[:100],
                               amount=amount, note=(request.form.get('note') or '').strip()[:250]))
        db.session.commit()
        flash('Matumizi yamerekodiwa.', 'success')
        return redirect(url_for('expenses'))

    expenses_list = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.id.desc()).all()
    month_start = period_start('month')
    month_total = sum(e.amount or 0 for e in expenses_list if e.created_at and e.created_at >= month_start)
    all_total = sum(e.amount or 0 for e in expenses_list)
    return render_template('expenses.html', expenses_list=expenses_list,
                           month_total=month_total, all_total=all_total)


@app.route('/expenses/<int:eid>/delete', methods=['POST'])
@login_required
def expense_delete(eid):
    e = own_or_404(Expense, eid)
    db.session.delete(e)
    db.session.commit()
    flash('Matumizi yamefutwa.', 'success')
    return redirect(url_for('expenses'))


# ==========================================================
# RIPOTI
# ==========================================================
@app.route('/reports')
@login_required
def reports():
    period = request.args.get('period', 'month')
    if period not in ('today', 'week', 'month', 'all'):
        period = 'month'
    start = period_start(period)
    uid = current_user.id

    sales_q = Sale.query.filter(Sale.user_id == uid)
    exp_q = Expense.query.filter(Expense.user_id == uid)
    if start:
        sales_q = sales_q.filter(Sale.created_at >= start)
        exp_q = exp_q.filter(Expense.created_at >= start)

    sales_list = sales_q.order_by(Sale.id.desc()).all()
    total_sales = sum(s.total or 0 for s in sales_list)
    gross_profit = sum(sum((i.price - (i.cost or 0)) * i.qty for i in s.items) for s in sales_list)
    total_expenses = sum(e.amount or 0 for e in exp_q.all())

    pay_breakdown, top = {}, {}
    for s in sales_list:
        pay_breakdown[s.payment_method] = pay_breakdown.get(s.payment_method, 0) + (s.total or 0)
        for i in s.items:
            row = top.setdefault(i.name, {'qty': 0, 'total': 0})
            row['qty'] += i.qty
            row['total'] += i.total or 0
    top_products = sorted(top.items(), key=lambda kv: kv[1]['total'], reverse=True)[:5]

    debts_list = Debt.query.filter_by(user_id=uid).all()
    total_debts = sum(d.balance for d in debts_list)
    low_stock = Product.query.filter(Product.user_id == uid, Product.stock <= Product.min_stock).all()

    return render_template('reports.html', period=period, sales_list=sales_list[:50],
                           sales_count=len(sales_list), total_sales=total_sales,
                           gross_profit=gross_profit, total_expenses=total_expenses,
                           net_profit=gross_profit - total_expenses, pay_breakdown=pay_breakdown,
                           top_products=top_products, total_debts=total_debts, low_stock=low_stock)


# ==========================================================
# MIPANGILIO / PROFILE
# ==========================================================
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update_info':
            current_user.business_name = request.form.get('business_name')
            current_user.owner_name = request.form.get('owner_name')
            current_user.phone = request.form.get('phone')
            current_user.business_type = request.form.get('business_type')
            try:
                db.session.commit()
                flash('Taarifa za biashara zimebadilishwa kikamilifu!', 'success')
            except Exception:
                db.session.rollback()
                flash('Kuna tatizo limetokea wakati wa kuhifadhi.', 'danger')

        elif action == 'change_password':
            old_password = request.form.get('old_password')
            new_password = request.form.get('new_password')
            if check_password_hash(current_user.password, old_password):
                current_user.password = generate_password_hash(new_password, method='pbkdf2:sha256')
                db.session.commit()
                flash('Neno la siri limebadilishwa kikamilifu!', 'success')
            else:
                flash('Neno la siri la zamani sio sahihi!', 'danger')

        return redirect(url_for('profile'))

    return render_template('profile.html')


@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'master':
        flash('Huna ruhusa ya kuingia hapa!', 'danger')
        return redirect(url_for('index'))
    return render_template('admin.html')


if __name__ == '__main__':
    app.run(debug=True)
