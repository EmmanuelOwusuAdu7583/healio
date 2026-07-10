import os
import sqlite3
import secrets
import string
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "healio-fallback-key-for-local-dev-only")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "healio-fallback-admin-for-local-dev-only")

DB_PATH = "healio.db"


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


# ---------- Database ----------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_database():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_code TEXT UNIQUE NOT NULL,
            doctor_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            password TEXT NOT NULL,
            diagnosis TEXT,
            medication TEXT,
            treatment_duration TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (doctor_id) REFERENCES doctors(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            check_date DATE NOT NULL,
            took_medication BOOLEAN NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS weekly_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            week_number INTEGER NOT NULL,
            symptoms TEXT,
            side_effects TEXT,
            noticeable_changes TEXT,
            symptom_trend TEXT,
            satisfaction_rating INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctor_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            doctor_id INTEGER NOT NULL,
            note_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id),
            FOREIGN KEY (doctor_id) REFERENCES doctors(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            flag_reason TEXT NOT NULL,
            resolved BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        )
    """)

    conn.commit()
    conn.close()


# ---------- Helpers ----------

def generate_code(prefix, length=6):
    chars = string.ascii_uppercase + string.digits
    return prefix + "".join(secrets.choice(chars) for _ in range(length))


def generate_password(length=10):
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def login_required_doctor(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "doctor_id" not in session:
            return redirect(url_for("doctor_login"))
        return f(*args, **kwargs)
    return decorated


def login_required_patient(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "patient_id" not in session:
            return redirect(url_for("patient_login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


def check_and_create_flags(patient_id):
    """Run after check-ins / weekly reports. Flags missed doses and worsening symptom trends."""
    conn = get_db()
    cursor = conn.cursor()

    # Missed dose flag: last 2 daily check-ins both "No"
    cursor.execute("""
        SELECT took_medication FROM daily_checkins
        WHERE patient_id = ?
        ORDER BY check_date DESC LIMIT 2
    """, (patient_id,))
    recent = cursor.fetchall()
    if len(recent) == 2 and not recent[0]["took_medication"] and not recent[1]["took_medication"]:
        cursor.execute("""
            SELECT id FROM flags WHERE patient_id = ? AND flag_reason = 'missed_doses' AND resolved = 0
        """, (patient_id,))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO flags (patient_id, flag_reason) VALUES (?, 'missed_doses')
            """, (patient_id,))

    # Worsening symptoms flag: last 2 weekly reports both "worse"
    cursor.execute("""
        SELECT symptom_trend FROM weekly_reports
        WHERE patient_id = ?
        ORDER BY week_number DESC LIMIT 2
    """, (patient_id,))
    recent_weeks = cursor.fetchall()
    if len(recent_weeks) == 2 and recent_weeks[0]["symptom_trend"] == "worse" and recent_weeks[1]["symptom_trend"] == "worse":
        cursor.execute("""
            SELECT id FROM flags WHERE patient_id = ? AND flag_reason = 'worsening_symptoms' AND resolved = 0
        """, (patient_id,))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO flags (patient_id, flag_reason) VALUES (?, 'worsening_symptoms')
            """, (patient_id,))

    conn.commit()
    conn.close()


# ---------- Public / Welcome ----------

@app.route("/")
def index():
    return render_template("welcome.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------- Admin ----------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_doctors"))
        flash("Incorrect admin password.")
    return render_template("admin_login.html")


@app.route("/admin/doctors", methods=["GET", "POST"])
@admin_required
def admin_doctors():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            doctor_code = generate_code("DR-")
            password = generate_password()
            cursor.execute("""
                INSERT INTO doctors (doctor_code, name, password) VALUES (?, ?, ?)
            """, (doctor_code, name, password))
            conn.commit()
            flash(f"Doctor added — Code: {doctor_code} | Password: {password} (save this, it won't be shown again in full)")

    cursor.execute("SELECT id, doctor_code, name, created_at FROM doctors ORDER BY created_at DESC")
    doctors = cursor.fetchall()
    conn.close()
    return render_template("admin_doctors.html", doctors=doctors)


# ---------- Doctor ----------

@app.route("/doctor/login", methods=["GET", "POST"])
def doctor_login():
    if request.method == "POST":
        doctor_code = request.form.get("doctor_code", "").strip().upper()
        password = request.form.get("password", "")

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM doctors WHERE doctor_code = ?", (doctor_code,))
        doctor = cursor.fetchone()
        conn.close()

        if doctor and doctor["password"] == password:
            session["doctor_id"] = doctor["id"]
            session["doctor_name"] = doctor["name"]
            return redirect(url_for("doctor_dashboard"))
        flash("Invalid doctor code or password.")
    return render_template("doctor_login.html")


@app.route("/doctor/dashboard")
@login_required_doctor
def doctor_dashboard():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT p.id, p.patient_code, p.name, p.diagnosis,
        (SELECT COUNT(*) FROM flags f WHERE f.patient_id = p.id AND f.resolved = 0) as active_flags
        FROM patients p WHERE p.doctor_id = ?
        ORDER BY active_flags DESC, p.created_at DESC
    """, (session["doctor_id"],))
    patients = cursor.fetchall()
    conn.close()

    total_patients = len(patients)
    flagged_count = sum(1 for p in patients if p["active_flags"] > 0)

    hour = datetime.now().hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    return render_template(
        "doctor_dashboard.html",
        patients=patients,
        total_patients=total_patients,
        flagged_count=flagged_count,
        active="home",
        greeting=greeting,
    )


@app.route("/doctor/patients/new", methods=["GET", "POST"])
@login_required_doctor
def new_patient():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        diagnosis = request.form.get("diagnosis", "").strip()
        medication = request.form.get("medication", "").strip()
        treatment_duration = request.form.get("treatment_duration", "").strip()

        if name:
            patient_code = generate_code("PT-")
            password = generate_password()

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO patients (patient_code, doctor_id, name, password, diagnosis, medication, treatment_duration)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (patient_code, session["doctor_id"], name, password, diagnosis, medication, treatment_duration))
            conn.commit()
            conn.close()

            flash(f"Patient added — Code: {patient_code} | Password: {password} (share these with the patient securely)")
            return redirect(url_for("doctor_dashboard"))

    return render_template("new_patient.html", active="add")


@app.route("/doctor/patients/<int:patient_id>", methods=["GET", "POST"])
@login_required_doctor
def patient_detail(patient_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM patients WHERE id = ? AND doctor_id = ?", (patient_id, session["doctor_id"]))
    patient = cursor.fetchone()
    if not patient:
        conn.close()
        return redirect(url_for("doctor_dashboard"))

    if request.method == "POST":
        note_text = request.form.get("note_text", "").strip()
        if note_text:
            cursor.execute("""
                INSERT INTO doctor_notes (patient_id, doctor_id, note_text) VALUES (?, ?, ?)
            """, (patient_id, session["doctor_id"], note_text))
            conn.commit()

    cursor.execute("""
        SELECT * FROM weekly_reports WHERE patient_id = ? ORDER BY week_number DESC
    """, (patient_id,))
    weekly_reports = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM daily_checkins WHERE patient_id = ? ORDER BY check_date DESC LIMIT 14
    """, (patient_id,))
    daily_checkins = cursor.fetchall()

    cursor.execute("""
        SELECT dn.*, d.name as doctor_name FROM doctor_notes dn
        JOIN doctors d ON dn.doctor_id = d.id
        WHERE dn.patient_id = ? ORDER BY dn.created_at DESC
    """, (patient_id,))
    notes = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM flags WHERE patient_id = ? AND resolved = 0 ORDER BY created_at DESC
    """, (patient_id,))
    active_flags = cursor.fetchall()

    conn.close()

    adherence_pct = None
    if daily_checkins:
        taken = sum(1 for c in daily_checkins if c["took_medication"])
        adherence_pct = round(100 * taken / len(daily_checkins))

    trend_points = []
    reports_asc = list(reversed(weekly_reports))
    rated_reports = [r for r in reports_asc if r["satisfaction_rating"]]
    for i, r in enumerate(rated_reports):
        x = 0 if len(rated_reports) == 1 else round(i * 800 / (len(rated_reports) - 1))
        y = round(180 - (r["satisfaction_rating"] - 1) / 4 * 160)
        trend_points.append({"x": x, "y": y, "week": r["week_number"], "rating": r["satisfaction_rating"]})

    return render_template(
        "patient_detail.html",
        patient=patient,
        weekly_reports=weekly_reports,
        daily_checkins=daily_checkins,
        notes=notes,
        active_flags=active_flags,
        adherence_pct=adherence_pct,
        trend_points=trend_points,
        active="patients",
    )


@app.route("/doctor/flags/<int:flag_id>/resolve", methods=["POST"])
@login_required_doctor
def resolve_flag(flag_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE flags SET resolved = 1 WHERE id = ?
        AND patient_id IN (SELECT id FROM patients WHERE doctor_id = ?)
    """, (flag_id, session["doctor_id"]))
    conn.commit()
    patient_id = request.form.get("patient_id")
    conn.close()
    return redirect(url_for("patient_detail", patient_id=patient_id))


# ---------- Patient ----------

@app.route("/patient/login", methods=["GET", "POST"])
def patient_login():
    if request.method == "POST":
        patient_code = request.form.get("patient_code", "").strip().upper()
        doctor_code = request.form.get("doctor_code", "").strip().upper()
        password = request.form.get("password", "")

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.*, d.doctor_code FROM patients p
            JOIN doctors d ON p.doctor_id = d.id
            WHERE p.patient_code = ? AND d.doctor_code = ?
        """, (patient_code, doctor_code))
        patient = cursor.fetchone()
        conn.close()

        if patient and patient["password"] == password:
            session["patient_id"] = patient["id"]
            session["patient_name"] = patient["name"]
            return redirect(url_for("patient_dashboard"))
        flash("Invalid patient code, doctor code, or password.")
    return render_template("patient_login.html")


@app.route("/patient/dashboard")
@login_required_patient
def patient_dashboard():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM patients WHERE id = ?", (session["patient_id"],))
    patient = cursor.fetchone()

    today = date.today().isoformat()
    cursor.execute("""
        SELECT * FROM daily_checkins WHERE patient_id = ? AND check_date = ?
    """, (session["patient_id"], today))
    todays_checkin = cursor.fetchone()

    cursor.execute("""
        SELECT dn.*, d.name as doctor_name FROM doctor_notes dn
        JOIN doctors d ON dn.doctor_id = d.id
        WHERE dn.patient_id = ? ORDER BY dn.created_at DESC LIMIT 3
    """, (session["patient_id"],))
    recent_notes = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM weekly_reports WHERE patient_id = ? ORDER BY week_number DESC LIMIT 1
    """, (session["patient_id"],))
    latest_report = cursor.fetchone()

    conn.close()

    return render_template(
        "patient_dashboard.html",
        patient=patient,
        todays_checkin=todays_checkin,
        recent_notes=recent_notes,
        latest_report=latest_report,
        active="home",
    )


@app.route("/patient/checkin", methods=["GET", "POST"])
@login_required_patient
def patient_checkin():
    today = date.today().isoformat()

    if request.method == "POST":
        took_medication = request.form.get("took_medication") == "yes"

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM daily_checkins WHERE patient_id = ? AND check_date = ?
        """, (session["patient_id"], today))
        existing = cursor.fetchone()

        if existing:
            cursor.execute("""
                UPDATE daily_checkins SET took_medication = ? WHERE id = ?
            """, (took_medication, existing["id"]))
        else:
            cursor.execute("""
                INSERT INTO daily_checkins (patient_id, check_date, took_medication)
                VALUES (?, ?, ?)
            """, (session["patient_id"], today, took_medication))
        conn.commit()
        conn.close()

        check_and_create_flags(session["patient_id"])

        flash("Check-in saved. Thank you!")
        return redirect(url_for("patient_dashboard"))

    # Build current week's day strip (Mon-Sun) with check-in status
    today_date = date.today()
    monday = today_date - timedelta(days=today_date.weekday())
    conn = get_db()
    cursor = conn.cursor()
    week_days = []
    for i in range(7):
        d = monday + timedelta(days=i)
        cursor.execute("""
            SELECT took_medication FROM daily_checkins WHERE patient_id = ? AND check_date = ?
        """, (session["patient_id"], d.isoformat()))
        row = cursor.fetchone()
        week_days.append({
            "letter": d.strftime("%a")[0],
            "num": d.day,
            "is_today": d == today_date,
            "status": (None if not row else ("yes" if row["took_medication"] else "no")),
        })
    taken_count = sum(1 for d in week_days if d["status"] == "yes")
    conn.close()

    return render_template("patient_checkin.html", active="checkin", week_days=week_days, taken_count=taken_count)


@app.route("/patient/weekly-tracker", methods=["GET", "POST"])
@login_required_patient
def weekly_tracker():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COALESCE(MAX(week_number), 0) + 1 as next_week FROM weekly_reports WHERE patient_id = ?
    """, (session["patient_id"],))
    next_week = cursor.fetchone()["next_week"]

    if request.method == "POST":
        symptoms = request.form.get("symptoms", "").strip()
        side_effects = request.form.get("side_effects", "").strip()
        noticeable_changes = request.form.get("noticeable_changes", "").strip()
        symptom_trend = request.form.get("symptom_trend", "same")
        satisfaction_rating = int(request.form.get("satisfaction_rating", 3))

        cursor.execute("""
            INSERT INTO weekly_reports
            (patient_id, week_number, symptoms, side_effects, noticeable_changes, symptom_trend, satisfaction_rating)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session["patient_id"], next_week, symptoms, side_effects, noticeable_changes, symptom_trend, satisfaction_rating))
        conn.commit()
        conn.close()

        check_and_create_flags(session["patient_id"])

        flash("Weekly report submitted. Thank you!")
        return redirect(url_for("patient_dashboard"))

    conn.close()
    return render_template("weekly_tracker.html", next_week=next_week, active="checkin")


@app.route("/patient/history")
@login_required_patient
def patient_history():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM weekly_reports WHERE patient_id = ? ORDER BY week_number DESC
    """, (session["patient_id"],))
    reports = cursor.fetchall()
    conn.close()
    return render_template("patient_history.html", reports=reports, active="history")


@app.route("/patient/notes")
@login_required_patient
def patient_notes():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT dn.*, d.name as doctor_name FROM doctor_notes dn
        JOIN doctors d ON dn.doctor_id = d.id
        WHERE dn.patient_id = ? ORDER BY dn.created_at DESC
    """, (session["patient_id"],))
    notes = cursor.fetchall()
    conn.close()
    return render_template("patient_notes.html", notes=notes, active="notes")


# ---------- App startup ----------

create_database()

if __name__ == "__main__":
    app.run(debug=True)
