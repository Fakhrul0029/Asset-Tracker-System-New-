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
                password TEXT NOT NULL
            );
        ''')

        # =========================
        # AUTO UPDATE OLD DATABASE
        # =========================
        cur.execute('''
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS email TEXT;
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

        else:

            cur.execute('''
                UPDATE users
                SET email = %s
                WHERE username = %s
            ''', (
                'admin@gmail.com',
                'admin'
            ))

        conn.commit()

    except Exception as e:

        conn.rollback()
        print(f"Database Error: {e}")

    finally:

        cur.close()
        conn.close()


init_db()


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

    cur.close()
    conn.close()

    return render_template(
        'admin.html',
        users=users
    )


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

        flash('User Added Successfully')

    except psycopg2.errors.UniqueViolation:

        conn.rollback()

        flash('Username or Email already exists')

    finally:

        cur.close()
        conn.close()

    return redirect(url_for('admin_panel'))


@app.route('/delete_user/<int:id>', methods=['POST'])
def delete_user(id):

    if 'user' not in session:
        return redirect(url_for('login'))

    if session['user'] != 'admin':
        return redirect(url_for('index'))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        'DELETE FROM users WHERE id = %s',
        (id,)
    )

    conn.commit()

    cur.close()
    conn.close()

    return redirect(url_for('admin_panel'))


@app.route('/')
def index():

    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.DictCursor
    )

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

    cur.close()
    conn.close()

    return render_template(
        'assets.html',
        data=data,
        total=total,
        working=working,
        maintenance=maintenance,
        faulty=faulty
    )


@app.route('/logout')
def logout():

    session.clear()

    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
