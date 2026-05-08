import os
import io
import csv
import base64
import qrcode
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response

app = Flask(__name__)
app.secret_key = 'jpkn_assets_tracking_final_2026'

DATABASE_URL = os.environ.get('DATABASE_URL')


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


# =====================================
# ACTIVITY LOGGER
# =====================================
def log_activity(username, action, details):

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute('''
        INSERT INTO activity_logs (
            username,
            action,
            details
        )
        VALUES (%s, %s, %s)
    ''', (
        username,
        action,
        details
    ))

    conn.commit()

    cur.close()
    conn.close()


# =====================================
# DATABASE
# =====================================
def init_db():

    conn = get_db_connection()
    cur = conn.cursor()

    try:

        # =====================================
        # ASSETS TABLE
        # =====================================
        cur.execute('''
            CREATE TABLE IF NOT EXISTS assets (
                id SERIAL PRIMARY KEY,
                asset_type TEXT,
                tracking_number TEXT,
                cpu_name TEXT,
                ram_size TEXT,
                storage_type TEXT,
                serial_number TEXT UNIQUE,
                location TEXT,
                status TEXT,
                maintenance_logs TEXT,
                scan_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')

        # =====================================
        # USERS TABLE
        # =====================================
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password TEXT NOT NULL
            );
        ''')

        # =====================================
        # ACTIVITY LOG TABLE
        # =====================================
        cur.execute('''
            CREATE TABLE IF NOT EXISTS activity_logs (
                id SERIAL PRIMARY KEY,
                username TEXT,
                action TEXT,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')

        # =====================================
        # AUTO UPDATE OLD DATABASE
        # =====================================
        cur.execute('''
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS email TEXT;
        ''')

        cur.execute('''
            ALTER TABLE assets
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
        ''')

        # =====================================
        # DEFAULT ADMIN
        # =====================================
        cur.execute('''
            SELECT * FROM users
            WHERE username = %s
        ''', ('admin',))

        admin_exists = cur.fetchone()

        if not admin_exists:

            cur.execute('''
                INSERT INTO users (
                    username,
                    email,
                    password
                )
                VALUES (%s, %s, %s)
            ''', (
                'admin',
                'admin@gmail.com',
                'admin123'
            ))

        conn.commit()

    except Exception as e:

        conn.rollback()
        print(f"Database Error: {e}")

    finally:

        cur.close()
        conn.close()


init_db()


# =====================================
# LOGIN
# =====================================
@app.route('/login', methods=['GET', 'POST'])
def login():

    if request.method == 'POST':

        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()

        cur = conn.cursor(
            cursor_factory=psycopg2.extras.DictCursor
        )

        cur.execute(
            '''
            SELECT * FROM users
            WHERE email = %s
            AND password = %s
            ''',
            (email, password)
        )

        user = cur.fetchone()

        cur.close()
        conn.close()

        if user:

            session['user'] = user['username']
            session['email'] = user['email']

            if user['username'] == 'admin':
                return redirect(url_for('admin_panel'))

            return redirect(url_for('index'))

        flash('Invalid Email or Password')

    return render_template('login.html')


# =====================================
# ADMIN PANEL
# =====================================
@app.route('/admin')
def admin_panel():

    if 'user' not in session:
        return redirect(url_for('login'))

    if session['user'] != 'admin':
        return redirect(url_for('index'))

    conn = get_db_connection()

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.DictCursor
    )

    cur.execute('SELECT * FROM users ORDER BY id ASC')
    users = cur.fetchall()

    # ALL activity logs
    cur.execute('''
        SELECT * FROM activity_logs
        ORDER BY created_at DESC
    ''')

    logs = cur.fetchall()

    # REPORT HISTORY
    cur.execute('''
        SELECT
            DATE(created_at) as day,
            COUNT(*) FILTER (WHERE status = 'Working') as working,
            COUNT(*) FILTER (WHERE status = 'Maintenance') as maintenance,
            COUNT(*) FILTER (WHERE status = 'Faulty') as faulty,
            COUNT(*) as total
        FROM assets
        GROUP BY DATE(created_at)
        ORDER BY day DESC
    ''')

    reports = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        'admin.html',
        users=users,
        logs=logs,
        reports=reports
    )


# =====================================
# ADD USER
# =====================================
@app.route('/add_user', methods=['POST'])
def add_user():

    if 'user' not in session:
        return redirect(url_for('login'))

    if session['user'] != 'admin':
        return redirect(url_for('index'))

    username = request.form['username']
    email = request.form['email']
    password = request.form['password']

    conn = get_db_connection()
    cur = conn.cursor()

    try:

        cur.execute(
            '''
            INSERT INTO users (
                username,
                email,
                password
            )
            VALUES (%s, %s, %s)
            ''',
            (username, email, password)
        )

        conn.commit()

        log_activity(
            session['user'],
            'ADD USER',
            f'Added user: {username}'
        )

        flash('User Added Successfully')

    except psycopg2.errors.UniqueViolation:

        conn.rollback()

        flash('Username or Email already exists')

    finally:

        cur.close()
        conn.close()

    return redirect(url_for('admin_panel'))


# =====================================
# DELETE USER
# =====================================
@app.route('/delete_user/<int:id>', methods=['POST'])
def delete_user(id):

    if 'user' not in session:
        return redirect(url_for('login'))

    if session['user'] != 'admin':
        return redirect(url_for('index'))

    conn = get_db_connection()
    cur = conn.cursor(
        cursor_factory=psycopg2.extras.DictCursor
    )

    cur.execute(
        'SELECT * FROM users WHERE id = %s',
        (id,)
    )

    target_user = cur.fetchone()

    cur.execute(
        'DELETE FROM users WHERE id = %s',
        (id,)
    )

    conn.commit()

    if target_user:
        log_activity(
            session['user'],
            'DELETE USER',
            f'Deleted user: {target_user["username"]}'
        )

    cur.close()
    conn.close()

    return redirect(url_for('admin_panel'))


# =====================================
# USER DASHBOARD
# =====================================
@app.route('/')
def index():

    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.DictCursor
    )

    # ASSETS
    cur.execute('SELECT * FROM assets ORDER BY id DESC')
    data = cur.fetchall()

    total = len(data)

    working = len([
        r for r in data
        if r['status'] == 'Working'
    ])

    maintenance = len([
        r for r in data
        if r['status'] == 'Maintenance'
    ])

    faulty = len([
        r for r in data
        if r['status'] == 'Faulty'
    ])

    # USER ONLY SEE 24 HOURS LOGS
    yesterday = datetime.now() - timedelta(hours=24)

    cur.execute('''
        SELECT * FROM activity_logs
        WHERE created_at >= %s
        ORDER BY created_at DESC
    ''', (yesterday,))

    logs = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        'assets.html',
        data=data,
        total=total,
        working=working,
        maintenance=maintenance,
        faulty=faulty,
        logs=logs
    )


# =====================================
# ADD ASSET
# =====================================
@app.route('/add', methods=['GET', 'POST'])
def add():

    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':

        conn = get_db_connection()
        cur = conn.cursor()

        try:

            cur.execute('''
                INSERT INTO assets (
                    asset_type,
                    tracking_number,
                    cpu_name,
                    serial_number,
                    ram_size,
                    storage_type,
                    status,
                    location
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                request.form['asset_type'],
             
