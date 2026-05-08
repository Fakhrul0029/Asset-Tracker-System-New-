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


def init_db():

    conn = get_db_connection()
    cur = conn.cursor()

    try:

        # =========================
        # ASSETS TABLE
        # =========================
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
                scan_count INTEGER DEFAULT 0
            );
        ''')

        # =========================
        # USERS TABLE
        # =========================
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password TEXT NOT NULL
            );
        ''')

        # =========================
        # ACTIVITY LOG TABLE (NEW)
        # =========================
        cur.execute('''
            CREATE TABLE IF NOT EXISTS activity_logs (
                id SERIAL PRIMARY KEY,
                action TEXT,
                asset_id INTEGER,
                username TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')

        # =========================
        # DEFAULT ADMIN
        # =========================
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

        cur.execute('''
            SELECT * FROM users
            WHERE email = %s AND password = %s
        ''', (email, password))

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


# =========================
# ADMIN PANEL
# =========================
@app.route('/admin')
def admin_panel():

    if session.get('user') != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute('SELECT * FROM users ORDER BY id ASC')
    users = cur.fetchall()

    cur.execute('SELECT * FROM activity_logs ORDER BY timestamp DESC')
    logs = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('admin.html', users=users, logs=logs)


# =========================
# ADD USER
# =========================
@app.route('/add_user', methods=['POST'])
def add_user():

    if session.get('user') != 'admin':
        return redirect(url_for('login'))

    username = request.form['username']
    email = request.form['email']
    password = request.form['password']

    conn = get_db_connection()
    cur = conn.cursor()

    try:

        cur.execute('''
            INSERT INTO users (username, email, password)
            VALUES (%s, %s, %s)
        ''', (username, email, password))

        conn.commit()
        flash('User Added Successfully')

    except Exception as e:
        conn.rollback()
        flash('Error adding user')

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
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute('DELETE FROM users WHERE id = %s', (id,))

    conn.commit()

    cur.close()
    conn.close()

    return redirect(url_for('admin_panel'))


# =========================
# INDEX (USER VIEW)
# =========================
@app.route('/')
def index():

    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute('SELECT * FROM assets ORDER BY id DESC')
    data = cur.fetchall()

    total = len(data)

    working = len([r for r in data if r['status'] == 'Working'])
    maintenance = len([r for r in data if r['status'] == 'Maintenance'])
    faulty = len([r for r in data if r['status'] == 'Faulty'])

    # =========================
    # ACTIVITY LOG FILTER (24 HOURS)
    # =========================
    cur.execute('''
        SELECT * FROM activity_logs
        WHERE timestamp >= NOW() - INTERVAL '24 hours'
        ORDER BY timestamp DESC
    ''')

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
# LOGOUT
# =========================
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# =========================
# LOG ACTIVITY FUNCTION
# =========================
def log_activity(action, asset_id):

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute('''
        INSERT INTO activity_logs (action, asset_id, username)
        VALUES (%s, %s, %s)
    ''', (
        action,
        asset_id,
        session.get('user')
    ))

    conn.commit()
    cur.close()
    conn.close()


# =========================
# RUN
# =========================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
