import os
# =========================
# RESTORE
# =========================

@app.route('/restore/<int:id>', methods=['POST'])
@admin_required
def restore(id):

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("UPDATE assets SET is_deleted=FALSE WHERE id=%s", (id,))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('admin'))

# =========================
# EXPORT
# =========================

@app.route('/export')
@login_required
def export():

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM assets WHERE is_deleted=FALSE")
    rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([desc[0] for desc in cur.description])
    writer.writerows(rows)

    output.seek(0)

    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":"attachment;filename=assets.csv"})

# =========================
# LOGOUT
# =========================

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
