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

        cur.execute("SELECT * FROM users WHERE username='admin'")
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO users (username, email, password)
                VALUES (%s,%s,%s)
            """, ("admin", "admin@gmail.com", "admin123"))

        conn.commit()

    except Exception as e:
        conn.rollback()
        print("DB ERROR:", e)

    finally:
        cur.close()
        conn.close()


init_db()


# =========================
# LOG
# =========================
def log_action(email, action, serial):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO activity_logs (user_email, action, asset_serial)
            VALUES (%s,%s,%s)
        """, (email, action, serial))

        conn.commit()

    finally:
        cur.close()
        conn.close()


# =========================
# QR GENERATOR
# =========================
def generate_qr(data):
    img = qrcode.make(data)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


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
            session['user'] = user['username']
            session['email'] = user['email']
            return redirect(url_for('index'))

        flash("Invalid login")

    return render_template("login.html")


# =========================
# ADMIN PANEL (FIXED ADD USER)
# =========================
@app.route('/admin')
def admin():

    if session.get('user') != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM users ORDER BY id DESC")
    users = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("admin.html", users=users)


@app.route('/add_user', methods=['POST'])
def add_user():

    if session.get('user') != 'admin':
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO users (username,email,password)
            VALUES (%s,%s,%s)
        """, (
            request.form['username'],
            request.form['email'],
            request.form['password']
        ))

        conn.commit()

    except Exception as e:
        conn.rollback()
        flash("User already exists or invalid data!")

    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin'))


@app.route('/delete_user/<int:id>', methods=['POST'])
def delete_user(id):

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM users WHERE id=%s", (id,))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('admin'))


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
# VIEW ASSET (FIXED QR SCAN COUNT)
# =========================
@app.route('/asset/<int:id>')
def view(id):

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM assets WHERE id=%s", (id,))
    asset = cur.fetchone()

    cur.execute("UPDATE assets SET scan_count = scan_count + 1 WHERE id=%s", (id,))
    conn.commit()

    cur.close()
    conn.close()

    return render_template("view.html", asset=asset)


# =========================
# QR (FIXED → FULL LINK)
# =========================
@app.route('/qr/<int:id>')
def qr(id):

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM assets WHERE id=%s", (id,))
    asset = cur.fetchone()

    cur.close()
    conn.close()

    qr_data = url_for('view', id=id, _external=True)
    qr_code = generate_qr(qr_data)

    return render_template("qr_display.html",
        id=asset['id'],
        qr_code=qr_code,
        sn=asset['serial_number']
    )


# =========================
# ADD ASSET (FIXED ERROR HANDLING)
# =========================
@app.route('/add', methods=['GET','POST'])
def add():

    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':

        try:
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
                request.form['serial_number'],
                request.form['ram_size'],
                request.form['storage_type'],
                request.form['status'],
                request.form['location']
            ))

            conn.commit()
            log_action(session['email'], "ADD ASSET", request.form['serial_number'])

        except Exception as e:
            conn.rollback()
            flash("Error adding asset: serial number may already exist")

        finally:
            cur.close()
            conn.close()

        return redirect(url_for('index'))

    return render_template("add.html")


# =========================
# EDIT ASSET (FIXED)
# =========================
@app.route('/edit/<int:id>', methods=['GET','POST'])
def edit(id):

    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM assets WHERE id=%s", (id,))
    asset = cur.fetchone()

    if request.method == 'POST':

        try:
            cur.execute("""
                UPDATE assets
                SET asset_type=%s, tracking_number=%s, cpu_name=%s,
                    ram_size=%s, storage_type=%s, location=%s,
                    status=%s, serial_number=%s
                WHERE id=%s
            """, (
                request.form['asset_type'],
                request.form['tracking_number'],
                request.form['cpu_name'],
                request.form['ram_size'],
                request.form['storage_type'],
                request.form['location'],
                request.form['status'],
                request.form['serial_number'],
                id
            ))

            conn.commit()
            log_action(session['email'], "EDIT ASSET", request.form['serial_number'])

        except Exception as e:
            conn.rollback()
            flash("Update failed")

        finally:
            cur.close()
            conn.close()

        return redirect(url_for('index'))

    cur.close()
    conn.close()

    return render_template("edit.html", asset=asset)


# =========================
# DELETE
# =========================
@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):

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
# EXPORT CSV (FIXED)
# =========================
@app.route('/export')
def export():

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM assets")
    rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([desc[0] for desc in cur.description])
    writer.writerows(rows)

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=assets.csv"}
    )


# =========================
# ACTIVITY
# =========================
@app.route('/activity')
def activity():

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM activity_logs ORDER BY created_at DESC")
    logs = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("activity.html", logs=logs)


# =========================
# LOGOUT
# =========================
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
