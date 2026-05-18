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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE,
                email TEXT UNIQUE,
                password TEXT,
                role TEXT DEFAULT 'user'
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
                description TEXT,
                qr_code TEXT,
                scan_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

        cur.execute("""
            CREATE TABLE IF NOT EXISTS access_logs (
                id SERIAL PRIMARY KEY,
                user_email TEXT,
                action TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # default admin
        cur.execute("SELECT * FROM users WHERE username='admin'")
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
# GET CURRENT USER (DB AUTHORITATIVE)
# =========================
def get_current_user():
    if 'email' not in session:
        return None

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM users WHERE email=%s", (session['email'],))
    user = cur.fetchone()

    cur.close()
    conn.close()

    return user


# =========================
# LOGIN
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
            session['email'] = user['email']
            session['username'] = user['username']
            log_access(user['email'], "LOGIN")
            return redirect(url_for('index'))

        flash("Invalid login")

    return render_template("login.html")


# =========================
# INDEX
# =========================
@app.route('/')
def index():

    user = get_current_user()

    if not user:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM assets ORDER BY id DESC")
    data = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("assets.html", data=data, user=user)


# =========================
# ADMIN (STRICT DB CHECK)
# =========================
@app.route('/admin')
def admin():

    user = get_current_user()

    if not user:
        return redirect(url_for('login'))

    if user['role'] != 'admin':
        return redirect(url_for('index'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM users ORDER BY id DESC")
    users = cur.fetchall()

    cur.execute("SELECT * FROM access_logs ORDER BY created_at DESC LIMIT 20")
    logs = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("admin.html", users=users, access_logs=logs, user=user)


# =========================
# ADD USER
# =========================
@app.route('/add_user', methods=['POST'])
def add_user():

    user = get_current_user()

    if not user or user['role'] != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO users (username, email, password, role)
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
        flash("Error creating user")

    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin'))


# =========================
# DELETE USER
# =========================
@app.route('/delete_user/<int:id>', methods=['POST'])
def delete_user(id):

    user = get_current_user()

    if not user or user['role'] != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM users WHERE id=%s", (id,))

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


# =========================
# LOG FUNCTIONS
# =========================
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
