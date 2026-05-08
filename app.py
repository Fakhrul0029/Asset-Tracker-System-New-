import os
import io
import csv
import base64
import qrcode
import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response

app = Flask(__name__)
app.secret_key = 'jpkn_assets_tracking_final_2026'

DATABASE_URL = os.environ.get('DATABASE_URL')


# =========================
# DB CONNECTION
# =========================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


# =========================
# INIT DATABASE
# =========================
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    try:

        # USERS TABLE
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE,
                email TEXT UNIQUE,
                password TEXT
            );
        """)

        # ASSETS TABLE
        cur.execute("""
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
        """)

        # ACTIVITY LOG TABLE
        cur.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id SERIAL PRIMARY KEY,
                user_email TEXT,
                action TEXT,
                asset_serial TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # DEFAULT ADMIN
        cur.execute("""
            SELECT * FROM users WHERE username = 'admin'
        """)

        admin = cur.fetchone()

        if not admin:
            cur.execute("""
                INSERT INTO users (username, email, password)
                VALUES (%s, %s, %s)
            """, ("admin", "admin@gmail.com", "admin123"))

        conn.commit()

    except Exception as e:
        conn.rollback()
        print("DB Error:", e)

    finally:
        cur.close()
        conn.close()


init_db()


# =========================
# LOG FUNCTION
# =========================
def log_action(email, action, serial):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO activity_logs (user_email, action, asset_serial)
        VALUES (%s, %s, %s)
    """, (email, action, serial))

    conn.commit()
    cur.close()
    conn.close()


# =========================
# LOGIN
# =========================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':

        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute("""
            SELECT * FROM users
            WHERE email=%s AND password=%s
        """, (email, password))

        user = cur.fetchone()

        cur.close()
        conn.close()

        if user:
            session['user'] = user['username']
            session['email'] = user['email']

            if user['username'] == 'admin':
                return redirect(url_for('admin_panel'))

            return redirect(url_for('index'))

        flash("Invalid login")

    return render_template("login.html")


# =========================
# ADMIN PANEL (USER MANAGEMENT)
# =========================
@app.route('/admin')
def admin_panel():

    if 'user' not in session:
        return redirect(url_for('login'))

    if session['user'] != 'admin':
        return redirect(url_for('index'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM users ORDER BY id DESC")
    users = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("admin.html", users=users)


# =========================
# ADD USER
# =========================
@app.route('/add_user', methods=['POST'])
def add_user():

    if session.get('user') != 'admin':
        return redirect(url_for('index'))

    username = request.form['username']
    email = request.form['email']
    password = request.form['password']

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO users (username, email, password)
            VALUES (%s, %s, %s)
        """, (username, email, password))

        conn.commit()
        flash("User added")

    except Exception:
        conn.rollback()
        flash("User already exists")

    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin_panel'))


# =========================
# DELETE USER
# =========================
@app.route('/delete_user/<int:id>', methods=['POST'])
def delete_user(id):

    if session.get('user') != 'admin':
        return redirect(url_for('index'))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM users WHERE id=%s", (id,))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('admin_panel'))


# =========================
# DASHBOARD
# =========================
@app.route('/')
def index():

    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM assets ORDER BY id DESC")
    data = cur.fetchall()

    total = len(data)
    working = len([x for x in data if x['status'] == 'Working'])
    maintenance = len([x for x in data if x['status'] == 'Maintenance'])
    faulty = len([x for x in data if x['status'] == 'Faulty'])

    # =========================
    # ACTIVITY LOG RULE
    # =========================
    if session['user'] == 'admin':
        cur.execute("SELECT * FROM activity_logs ORDER BY created_at DESC")
    else:
        cur.execute("""
            SELECT * FROM activity_logs
            WHERE created_at >= NOW() - INTERVAL '24 HOURS'
            ORDER BY created_at DESC
        """)

    logs = cur.fetchall()

    # =========================
    # DAILY REPORT (ADMIN ONLY)
    # =========================
    report = None

    if session['user'] == 'admin':
        cur.execute("""
            SELECT DATE(created_at) as day,
                   COUNT(*) FILTER (WHERE status='Working') as working,
                   COUNT(*) FILTER (WHERE status='Maintenance') as maintenance,
                   COUNT(*) FILTER (WHERE status='Faulty') as faulty
            FROM assets
            GROUP BY DATE(created_at)
            ORDER BY day DESC;
        """)

        report = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "assets.html",
        data=data,
        total=total,
        working=working,
        maintenance=maintenance,
        faulty=faulty,
        logs=logs,
        report=report
    )


# =========================
# ADD ASSET
# =========================
@app.route('/add', methods=['GET', 'POST'])
def add():

    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':

        serial = request.form['serial_number']

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO assets (
                asset_type, tracking_number, cpu_name,
                serial_number, ram_size, storage_type,
                status, location
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            request.form['asset_type'],
            request.form['tracking_number'],
            request.form['cpu_name'],
            serial,
            request.form['ram_size'],
            request.form['storage_type'],
            request.form['status'],
            request.form['location']
        ))

        conn.commit()

        log_action(session['email'], "REGISTER ASSET", serial)

        cur.close()
        conn.close()

        return redirect(url_for('index'))

    return render_template("add.html")


# =========================
# EDIT ASSET
# =========================
@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):

    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM assets WHERE id=%s", (id,))
    asset = cur.fetchone()

    if request.method == 'POST':

        cur.execute("""
            UPDATE assets
            SET asset_type=%s, tracking_number=%s, cpu_name=%s,
                ram_size=%s, storage_type=%s, location=%s, status=%s
            WHERE id=%s
        """, (
            request.form['asset_type'],
            request.form['tracking_number'],
            request.form['cpu_name'],
            request.form['ram_size'],
            request.form['storage_type'],
            request.form['location'],
            request.form['status'],
            id
        ))

        conn.commit()

        log_action(session['email'], "EDIT ASSET", asset['serial_number'])

        cur.close()
        conn.close()

        return redirect(url_for('index'))

    cur.close()
    conn.close()

    return render_template("edit.html", asset=asset)


# =========================
# DELETE ASSET
# =========================
@app.route('/delete/<int:id>', methods=['POST'])
def delete_asset(id):

    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT serial_number FROM assets WHERE id=%s", (id,))
    asset = cur.fetchone()

    cur.execute("DELETE FROM assets WHERE id=%s", (id,))
    conn.commit()

    log_action(session['email'], "DELETE ASSET", asset['serial_number'])

    cur.close()
    conn.close()

    return redirect(url_for('index'))


# =========================
# LOGOUT
# =========================
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
