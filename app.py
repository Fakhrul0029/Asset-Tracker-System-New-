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
# INIT DB
# =========================
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # USERS TABLE (ROLE ADDED)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE,
                email TEXT UNIQUE,
                password TEXT,
                role TEXT DEFAULT 'user'
            );
        """)

        # ASSETS TABLE (SOFT DELETE ADDED)
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
                description TEXT,
                qr_code TEXT,
                scan_count INTEGER DEFAULT 0,
                deleted BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            ALTER TABLE assets
            ADD COLUMN IF NOT EXISTS deleted BOOLEAN DEFAULT FALSE;
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id SERIAL PRIMARY KEY,
                user_email TEXT,
                action TEXT,
                asset_serial TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS access_logs (
                id SERIAL PRIMARY KEY,
                user_email TEXT,
                action TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # DEFAULT ADMIN
        cur.execute("SELECT * FROM users WHERE email='admin@gmail.com'")
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO users (username, email, password, role)
                VALUES (%s,%s,%s,%s)
            """, ("admin", "admin@gmail.com", "admin123", "admin"))

        conn.commit()

    except Exception as e:
        conn.rollback()
        print("DB ERROR:", e)

    finally:
        cur.close()
        conn.close()


init_db()


# =========================
# LOGS
# =========================
def log_action(email, action, serial):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO activity_logs (user_email, action, asset_serial)
        VALUES (%s,%s,%s)
    """, (email, action, serial))
    conn.commit()
    cur.close()
    conn.close()


def log_access(email, action):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO access_logs (user_email, action)
        VALUES (%s,%s)
    """, (email, action))
    conn.commit()
    cur.close()
    conn.close()


# =========================
# QR
# =========================
def generate_qr(data):
    img = qrcode.make(data)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


# =========================
# LOGIN (ROLE SYSTEM)
# =========================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute("""
            SELECT * FROM users
            WHERE email=%s AND password=%s
        """, (request.form['email'], request.form['password']))

        user = cur.fetchone()

        cur.close()
        conn.close()

        if user:
            session['user'] = user['username']
            session['email'] = user['email']
            session['role'] = user['role']

            log_access(user['email'], "LOGIN")

            # ROLE REDIRECT
            if user['role'] == 'admin':
                return redirect(url_for('admin'))
            else:
                return redirect(url_for('index'))

        flash("Invalid login")

    return render_template("login.html")


# =========================
# ADMIN PANEL
# =========================
@app.route('/admin')
def admin():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM users ORDER BY id DESC")
    users = cur.fetchall()

    cur.execute("SELECT * FROM access_logs ORDER BY created_at DESC LIMIT 20")
    access_logs = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("admin.html", users=users, access_logs=access_logs)


# =========================
# ADD USER (WITH ROLE)
# =========================
@app.route('/add_user', methods=['POST'])
def add_user():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO users (username,email,password,role)
            VALUES (%s,%s,%s,%s)
        """, (
            request.form['username'],
            request.form['email'],
            request.form['password'],
            request.form['role']
        ))

        conn.commit()

    except Exception:
        conn.rollback()
        flash("User already exists or invalid data!")

    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin'))


# =========================
# DASHBOARD (USER VIEW)
# =========================
@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM assets WHERE deleted = FALSE ORDER BY id DESC")
    data = cur.fetchall()

    total = len(data)
    working = len([x for x in data if x['status'] == 'Working'])
    maintenance = len([x for x in data if x['status'] == 'Maintenance'])
    faulty = len([x for x in data if x['status'] == 'Faulty'])

    cur.close()
    conn.close()

    return render_template("assets.html",
        data=data,
        total=total,
        working=working,
        maintenance=maintenance,
        faulty=faulty
    )


# =========================
# SOFT DELETE (NEW)
# =========================
@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT serial_number FROM assets WHERE id=%s", (id,))
    asset = cur.fetchone()

    cur.execute("""
        UPDATE assets
        SET deleted = TRUE
        WHERE id=%s
    """, (id,))

    conn.commit()

    log_action(session['email'], "ASSET DELETED", asset['serial_number'])

    cur.close()
    conn.close()

    return redirect(url_for('index'))


# =========================
# RESTORE ASSET (ADMIN ONLY)
# =========================
@app.route('/restore/<int:id>', methods=['POST'])
def restore(id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE assets
        SET deleted = FALSE
        WHERE id=%s
    """, (id,))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('admin'))


# =========================
# LOGOUT
# =========================
@app.route('/logout')
def logout():
    if 'email' in session:
        log_access(session['email'], "LOGOUT")

    session.clear()
    return redirect(url_for('login'))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
