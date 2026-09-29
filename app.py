import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'mkolani-secret-key-2026')

# DATABASE CONFIGURATION
db_url = os.environ.get('DATABASE_URL', 'sqlite:///mkolani_pos.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'warning'

# MODEL YA MTUMIAJI / BIASHARA
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(150), nullable=False)
    owner_name = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.Text, nullable=False)
    business_type = db.Column(db.String(50), default='retail')
    role = db.Column(db.String(20), default='user')

# MODEL YA WATEJA (CRM)
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

@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except Exception:
        return None

with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"Error creating database tables: {e}")

@app.context_processor
def inject_endpoints():
    return dict(endpoints=[rule.endpoint for rule in app.url_map.iter_rules()])

@app.route('/')
def index():
    if current_user.is_authenticated:
        return render_template('dashboard.html')
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

            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash('Barua pepe hii tayari imeshasajiliwa! Tafadhali ingia.', 'warning')
                return redirect(url_for('login'))

            hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

            new_user = User(
                business_name=business_name,
                owner_name=owner_name,
                phone=phone,
                email=email,
                password=hashed_password,
                business_type=business_type
            )

            db.session.add(new_user)
            db.session.commit()

            login_user(new_user)
            flash(f'Hongera {business_name}! Usajili umekamilika. Karibu kwenye Mkolani POS!', 'success')
            return redirect(url_for('index'))

        except Exception as e:
            db.session.rollback()
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
            else:
                flash('Barua pepe au Neno la Siri sio sahihi.', 'danger')
                return redirect(url_for('login'))
        except Exception as e:
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
    return redirect(url_for('index'))

# ROUTE YA MAUZO & RISITI (POS)
@app.route('/sales', methods=['GET', 'POST'])
@login_required
def sales():
    if request.method == 'POST':
        # Logic ya kuhifadhi mauzo itakuja hapa stoko ikikamilika
        flash('Mauzo yamekamilika na risiti imetolewa!', 'success')
        return redirect(url_for('sales'))

    customers_list = Customer.query.filter_by(user_id=current_user.id).all()
    return render_template('sales.html', customers_list=customers_list)

@app.route('/sms-center', methods=['GET', 'POST'])
@login_required
def sms_center():
    if request.method == 'POST':
        message = request.form.get('message')
        if not message:
            flash('Tafadhali andika ujumbe wa SMS.', 'warning')
            return redirect(url_for('sms_center'))
            
        flash('Ujumbe wako wa SMS umetumwa kikamilifu!', 'success')
        return redirect(url_for('sms_center'))

    try:
        customers_list = Customer.query.filter_by(user_id=current_user.id).all()
    except Exception as e:
        customers_list = []
        print(f"Error fetching customers: {e}")

    return render_template('sms_center.html', customers_list=customers_list)

@app.route('/customers', methods=['GET', 'POST'])
@login_required
def customers():
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        email = request.form.get('email')
        address = request.form.get('address')
        notes = request.form.get('notes')

        if name and phone:
            new_cust = Customer(
                user_id=current_user.id,
                name=name,
                phone=phone,
                email=email,
                address=address,
                notes=notes
            )
            db.session.add(new_cust)
            db.session.commit()
            flash('Mteja amesajiliwa kikamilifu!', 'success')
            return redirect(url_for('customers'))

    customers_list = Customer.query.filter_by(user_id=current_user.id).all()
    return render_template('customers.html', customers_list=customers_list)

@app.route('/debts')
@login_required
def debts():
    return render_template('debts.html')

@app.route('/products')
@login_required
def products():
    return render_template('products.html')

@app.route('/expenses')
@login_required
def expenses():
    return render_template('expenses.html')

@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')

# ==========================================
# ROUTE YA PROFILE / MIPANGILIO (IMEREKEBISHWA)
# ==========================================
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        action = request.form.get('action')
        
        # A. KUBADILISHA TAARIFA ZA BIASHARA
        if action == 'update_info':
            current_user.business_name = request.form.get('business_name')
            current_user.owner_name = request.form.get('owner_name')
            current_user.phone = request.form.get('phone')
            current_user.business_type = request.form.get('business_type')
            
            try:
                db.session.commit()
                flash('Taarifa za biashara zimebadilishwa kikamilifu!', 'success')
            except Exception as e:
                db.session.rollback()
                flash('Kuna tatizo limetokea wakati wa kuhifadhi.', 'danger')
                
        # B. KUBADILISHA PASSWORD
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
