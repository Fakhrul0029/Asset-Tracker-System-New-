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
# INIT DB (AUTO RUN ON DEPLOY)
# =========================
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT,
            email TEXT UNIQUE,
            password TEXT
        );
    """)

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
            scan_count INTEGER DEFAULT 0
        );
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

    conn.commit()
    cur.close()
    conn.close()


init_db()


# =========================
# TEMP DB SETUP ROUTE (FOR FIXING RENDER ISSUE)
# =========================
@app.route('/setup-db')
def setup_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT,
            email TEXT UNIQUE,
            password TEXT
        );
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

    conn.commit()
    cur.close()
    conn.close()

    return "Database setup completed successfully!"


# =========================
# LOGIN (EMAIL)
# =========================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute("SELECT * FROM users WHERE email=%s AND password=%s", (email, password))
        user = cur.fetchone()

        cur.close()
        conn.close()

        if user:
            session['user'] = user['email']
            return redirect(url_for('index'))
        else:
            flash("Invalid login")
            return redirect(url_for('login'))

    return render_template('login.html')


# =========================
# LOG ACTION FUNCTION
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
    working = len([r for r in data if r['status'] == 'Working'])
    maintenance = len([r for r in data if r['status'] == 'Maintenance'])
    faulty = len([r for r in data if r['status'] == 'Faulty'])

    # =========================
    # ACTIVITY LOG RULE
    # =========================
    if session['user'] == 'admin@admin.com':
        cur.execute("SELECT * FROM activity_logs ORDER BY created_at DESC")
    else:
        cur.execute("""
            SELECT * FROM activity_logs
            WHERE created_at >= NOW() - INTERVAL '24 HOURS'
            ORDER BY created_at DESC
        """)

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


# =========================
# ADD ASSET
# =========================
@app.route('/add', methods=['GET', 'POST'])
def add():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        conn = get_db_connection()
        cur = conn.cursor()

        serial = request.form['serial_number']

        cur.execute("""
            INSERT INTO assets (asset_type, tracking_number, cpu_name, serial_number, ram_size, storage_type, status, location)
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

        log_action(session['user'], "REGISTER ASSET", serial)

        cur.close()
        conn.close()

        return redirect(url_for('index'))

    return render_template('add.html')


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
        serial = asset['serial_number']

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

        log_action(session['user'], "EDIT ASSET", serial)

        cur.close()
        conn.close()

        return redirect(url_for('index'))

    cur.close()
    conn.close()
    return render_template('edit.html', asset=asset)


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

    serial = asset['serial_number']

    cur.execute("DELETE FROM assets WHERE id=%s", (id,))
    conn.commit()

    log_action(session['user'], "DELETE ASSET", serial)

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


if __name__ == '__main__':
    app.run(debug=True)
