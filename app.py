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
        # Create table first
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

        # Safe update for old databases
        cur.execute("""
            ALTER TABLE assets
            ADD COLUMN IF NOT EXISTS asset_type TEXT;
        """)

        cur.execute("""
            ALTER TABLE assets
            ADD COLUMN IF NOT EXISTS tracking_number TEXT;
        """)

        conn.commit()

    except Exception as e:
        conn.rollback()
        print(f"Database initialization error: {e}")

    finally:
        cur.close()
        conn.close()


# Initialize database
init_db()


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        session['user'] = request.form['username']
        return redirect(url_for('index'))

    return render_template('login.html')


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
                request.form['tracking_number'],
                request.form['cpu_name'],
                request.form['serial_number'],
                request.form['ram_size'],
                request.form['storage_type'],
                request.form['status'],
                request.form['location']
            ))

            conn.commit()
            return redirect(url_for('index'))

        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            flash("This Serial Number already exists.")
            return redirect(url_for('add'))

        finally:
            cur.close()
            conn.close()

    return render_template('add.html')


@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute('SELECT * FROM assets WHERE id = %s', (id,))
    asset = cur.fetchone()

    if request.method == 'POST':
        try:
            log_entry = f"{request.form['category']}: {request.form['action']}"

            if asset['maintenance_logs']:
                new_logs = asset['maintenance_logs'] + "\n" + log_entry
            else:
                new_logs = log_entry

            cur.execute('''
                UPDATE assets
                SET
                    asset_type=%s,
                    tracking_number=%s,
                    cpu_name=%s,
                    ram_size=%s,
                    storage_type=%s,
                    location=%s,
                    status=%s,
                    maintenance_logs=%s
                WHERE id=%s
            ''', (
                request.form['asset_type'],
                request.form['tracking_number'],
                request.form['cpu_name'],
                request.form['ram_size'],
                request.form['storage_type'],
                request.form['location'],
                request.form['status'],
                new_logs,
                id
            ))

            conn.commit()
            return redirect(url_for('index'))

        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            flash("Update failed. Serial number already used.")
            return redirect(url_for('edit', id=id))

        finally:
            cur.close()
            conn.close()

    cur.close()
    conn.close()

    return render_template('edit.html', asset=asset)


@app.route('/export')
def export_assets():
    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute('''
        SELECT
            asset_type,
            tracking_number,
            cpu_name,
            serial_number,
            ram_size,
            storage_type,
            location,
            status
        FROM assets
    ''')

    rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        'Type',
        'Tracking No',
        'Brand/Model',
        'Serial Number',
        'RAM',
        'Storage',
        'Agency',
        'Status'
    ])

    writer.writerows(rows)

    cur.close()
    conn.close()

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            "Content-Disposition":
            "attachment;filename=jpkn_report.csv"
        }
    )


@app.route('/asset/<int:id>')
def asset_view(id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute(
        'UPDATE assets SET scan_count = scan_count + 1 WHERE id = %s',
        (id,)
    )

    conn.commit()

    cur.execute('SELECT * FROM assets WHERE id = %s', (id,))
    data = cur.fetchone()

    cur.close()
    conn.close()

    return render_template('asset.html', data=data)


@app.route('/qr/<int:id>')
def qr_display(id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute(
        'SELECT serial_number FROM assets WHERE id = %s',
        (id,)
    )

    asset = cur.fetchone()

    cur.close()
    conn.close()

    qr_url = url_for('asset_view', id=id, _external=True)

    img = qrcode.make(qr_url)

    buf = io.BytesIO()
    img.save(buf)

    qr_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

    return render_template(
        'qr_display.html',
        id=id,
        sn=asset['serial_number'],
        qr_code=qr_b64
    )


@app.route('/delete/<int:id>', methods=['POST'])
def delete_asset(id):
    if 'user' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute('DELETE FROM assets WHERE id = %s', (id,))

    conn.commit()

    cur.close()
    conn.close()

    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
