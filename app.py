import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'mkolani-secret-key-2026')

# DATABASE CONFIGURATION FOR RENDER & LOCAL
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
    password = db.Column(db.String(256), nullable=False)
    business_type = db.Column(db.String(50), default='retail')
    role = db.Column(db.String(20), default='user')  # 'user' au 'master'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# CREATE TABLES AUTOMATICALLY BEFORE FIRST REQUEST
with app.app_context():
    db.create_all()

# HAKIKISHA UTAMBULISHO WA ENDPOINTS UPO KWENYE BASE TEMPLATE
@app.context_processor
def inject_endpoints():
    return dict(endpoints=[rule.endpoint for rule in app.url_map.iter_rules()])

# 1. HOME / INDEX ROUTE
@app.route('/')
def index():
    if current_user.is_authenticated:
        return render_template('dashboard.html')
    return render_template('base.html')

# 2. ROUTE YA KUSAJILI BIASHARA MPYA (REGISTER)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        business_name = request.form.get('business_name')
        owner_name = request.form.get('owner_name')
        phone = request.form.get('phone')
        email = request.form.get('email')
        password = request.form.get('password')
        business_type = request.form.get('business_type', 'retail')

        # Angalia kama email ipo tayari
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Barua pepe hii tayari imeshasajiliwa! Tafadhali ingia au tumia email nyingine.', 'danger')
            return redirect(url_for('register'))

        # Hifadhi mtumiaji mpya
        hashed_password = generate_password_hash(password, method='scrypt')
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

        # Ingiza mtumiaji moja kwa moja
        login_user(new_user)
        flash('Hongera! Biashara yako imesajiliwa kikamilifu.', 'success')
        return redirect(url_for('index'))

    return render_template('register.html')

# 3. ROUTE YA LOG IN
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Karibu tena kwenye Mkolani POS!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Barua pepe au Neno la Siri sio sahihi.', 'danger')

    return redirect(url_for('index'))

# 4. ROUTE YA LOGOUT
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Umetoka kwenye mfumo kikamilifu.', 'info')
    return redirect(url_for('index'))

# 5. FORGOT PASSWORD ROUTE
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        flash('Ombi lako limepokelewa. Wasiliana na msaada kwa wateja kupitia WhatsApp (+255 625 567 603) kwa usaidizi wa haraka.', 'info')
        return redirect(url_for('index'))
    return redirect(url_for('index'))

# 6. ROUTE ZINGINE ZA DASHBOARD
@app.route('/sales')
@login_required
def sales():
    return render_template('sales.html')

@app.route('/sms-center')
@login_required
def sms_center():
    return render_template('sms_center.html')

@app.route('/customers')
@login_required
def customers():
    return render_template('customers.html')

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

@app.route('/profile')
@login_required
def profile():
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
