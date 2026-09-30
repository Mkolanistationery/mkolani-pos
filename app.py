import os
from datetime import datetime, timedelta

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
# SMS CENTER (bado ni onyesho; haitumi SMS halisi hadi gateway iunganishwe)
# ==========================================================
@app.route('/sms-center', methods=['GET', 'POST'])
@login_required
def sms_center():
    if request.method == 'POST':
        message = request.form.get('message')
        if not message:
            flash('Tafadhali andika ujumbe wa SMS.', 'warning')
            return redirect(url_for('sms_center'))
        flash('Ujumbe umehifadhiwa. Kutuma SMS halisi kutawezeshwa baada ya kuunganisha SMS Gateway.', 'info')
        return redirect(url_for('sms_center'))

    try:
        customers_list = Customer.query.filter_by(user_id=current_user.id).all()
    except Exception as e:
        customers_list = []
        print(f"Error fetching customers: {e}")
    return render_template('sms_center.html', customers_list=customers_list)


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
