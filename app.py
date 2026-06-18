"""
Face Recognition Student Information Web App
=============================================
A Flask-based web application that registers students with face images,
recognizes them via webcam, and displays their information based on
admin-configured field visibility settings.

Run: python app.py
Open: http://127.0.0.1:5000
"""

import os
import json
import base64
import sqlite3
import numpy as np
import face_recognition
from io import BytesIO
from PIL import Image
from datetime import datetime, date
from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for, flash
)

# ─────────────────────────────────────────────
# App Configuration
# ─────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "face-recognition-secret-key"

# Directories
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR   = os.path.join(BASE_DIR, "static", "uploads")
DATABASE     = os.path.join(BASE_DIR, "database.db")

# Face recognition tolerance (lower = stricter match, 0.0–1.0)
FACE_TOLERANCE = 0.5

# Ensure upload folder exists
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ─────────────────────────────────────────────
# Database Helpers
# ─────────────────────────────────────────────

def get_db():
    """Open a database connection and return it."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row   # rows behave like dicts
    return conn


def init_db():
    """Create all tables if they do not exist."""
    conn = get_db()
    cur  = conn.cursor()

    # Table: persons — stores all registered person details
    cur.execute("""
        CREATE TABLE IF NOT EXISTS persons (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            mobile      TEXT,
            dob         TEXT,
            email       TEXT,
            address     TEXT,
            department  TEXT,
            student_id  TEXT,
            image_path  TEXT,
            created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Table: encodings — stores face encoding as a JSON array per person
    cur.execute("""
        CREATE TABLE IF NOT EXISTS encodings (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id    INTEGER NOT NULL,
            face_encoding TEXT   NOT NULL,
            FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE CASCADE
        )
    """)

    # Table: display_settings — controls which fields appear in recognition results
    cur.execute("""
        CREATE TABLE IF NOT EXISTS display_settings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            field_name TEXT    NOT NULL UNIQUE,
            is_visible INTEGER NOT NULL DEFAULT 1
        )
    """)

    # Table: recognition_log — tracks recognition events for dashboard stats
    cur.execute("""
        CREATE TABLE IF NOT EXISTS recognition_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id   INTEGER,
            recognized  INTEGER NOT NULL,
            logged_at   TEXT    DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def seed_settings():
    """Insert default display_settings rows if the table is empty."""
    fields = [
        "name", "mobile", "dob", "email",
        "address", "department", "student_id"
    ]
    conn = get_db()
    cur  = conn.cursor()
    for field in fields:
        cur.execute(
            "INSERT OR IGNORE INTO display_settings (field_name, is_visible) VALUES (?, 1)",
            (field,)
        )
    conn.commit()
    conn.close()


def seed_sample_data():
    """
    Insert 3 sample records on first run so the dashboard is not empty.
    NOTE: These records use placeholder images and NO real face encodings,
    so they will never be matched during recognition — they are demo data only.
    """
    conn = get_db()
    cur  = conn.cursor()
    count = cur.execute("SELECT COUNT(*) FROM persons").fetchone()[0]
    if count > 0:
        conn.close()
        return  # already seeded

    samples = [
        {
            "name": "Alice Johnson",
            "mobile": "9876543210",
            "dob": "2002-03-15",
            "email": "alice@college.edu",
            "address": "12, Green St, Springfield",
            "department": "Computer Science",
            "student_id": "CS2022001",
        },
        {
            "name": "Bob Williams",
            "mobile": "9123456780",
            "dob": "2001-07-22",
            "email": "bob@college.edu",
            "address": "45, Blue Ave, Shelbyville",
            "department": "Electronics",
            "student_id": "EC2021045",
        },
        {
            "name": "Carol Davis",
            "mobile": "9988776655",
            "dob": "2003-11-08",
            "email": "carol@college.edu",
            "address": "78, Red Rd, Capital City",
            "department": "Mechanical",
            "student_id": "ME2023012",
        },
    ]

    for s in samples:
        cur.execute("""
            INSERT INTO persons (name, mobile, dob, email, address, department, student_id, image_path)
            VALUES (:name, :mobile, :dob, :email, :address, :department, :student_id, '')
        """, s)

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# Face Encoding Helpers
# ─────────────────────────────────────────────

def load_all_encodings():
    """
    Load every face encoding from the database.
    Returns a list of (person_id, numpy_encoding) tuples.
    """
    conn = get_db()
    rows = conn.execute("SELECT person_id, face_encoding FROM encodings").fetchall()
    conn.close()

    result = []
    for row in rows:
        try:
            enc = np.array(json.loads(row["face_encoding"]))
            result.append((row["person_id"], enc))
        except Exception:
            pass  # skip corrupted entries
    return result


def encoding_to_json(encoding: np.ndarray) -> str:
    """Convert a numpy face encoding to a JSON string for storage."""
    return json.dumps(encoding.tolist())


def decode_base64_image(b64_string: str):
    """
    Decode a base64-encoded JPEG/PNG string into a numpy RGB array
    that face_recognition can process.
    """
    # Strip the data URI prefix if present (data:image/jpeg;base64,...)
    if "," in b64_string:
        b64_string = b64_string.split(",", 1)[1]

    img_bytes = base64.b64decode(b64_string)
    pil_image = Image.open(BytesIO(img_bytes)).convert("RGB")
    return np.array(pil_image)


# ─────────────────────────────────────────────
# Routes — Dashboard
# ─────────────────────────────────────────────

@app.route("/")
def dashboard():
    """Main dashboard page showing statistics and quick-action buttons."""
    return render_template("dashboard.html")


@app.route("/api/stats")
def api_stats():
    """Return JSON stats for the dashboard cards."""
    today = date.today().isoformat()
    conn  = get_db()

    total_people = conn.execute(
        "SELECT COUNT(*) FROM persons"
    ).fetchone()[0]

    recognized_today = conn.execute(
        "SELECT COUNT(*) FROM recognition_log WHERE recognized=1 AND DATE(logged_at)=?",
        (today,)
    ).fetchone()[0]

    unknown_today = conn.execute(
        "SELECT COUNT(*) FROM recognition_log WHERE recognized=0 AND DATE(logged_at)=?",
        (today,)
    ).fetchone()[0]

    conn.close()
    return jsonify({
        "total_people":      total_people,
        "recognized_today":  recognized_today,
        "unknown_today":     unknown_today,
    })


# ─────────────────────────────────────────────
# Routes — Register Person
# ─────────────────────────────────────────────

@app.route("/register", methods=["GET", "POST"])
def register():
    """Show the registration form (GET) or process a new person (POST)."""
    if request.method == "GET":
        return render_template("register.html")

    # ── Collect form fields ──────────────────
    name       = request.form.get("name", "").strip()
    mobile     = request.form.get("mobile", "").strip()
    dob        = request.form.get("dob", "").strip()
    email      = request.form.get("email", "").strip()
    address    = request.form.get("address", "").strip()
    department = request.form.get("department", "").strip()
    student_id = request.form.get("student_id", "").strip()

    # Validate required field
    if not name:
        flash("Name is required.", "danger")
        return render_template("register.html")

    # ── Handle image ─────────────────────────
    image_np   = None
    image_path = ""

    # Option 1: file upload
    uploaded_file = request.files.get("face_image")
    if uploaded_file and uploaded_file.filename:
        pil_img    = Image.open(uploaded_file.stream).convert("RGB")
        image_np   = np.array(pil_img)

    # Option 2: webcam capture (base64 string in hidden field)
    elif request.form.get("webcam_image"):
        try:
            image_np = decode_base64_image(request.form["webcam_image"])
        except Exception:
            flash("Could not read webcam image. Please try again.", "danger")
            return render_template("register.html")

    # ── Detect and encode face ───────────────
    face_enc_json = None
    if image_np is not None:
        encodings = face_recognition.face_encodings(image_np)
        if not encodings:
            flash("No face detected in the image. Please use a clear frontal photo.", "warning")
            return render_template("register.html")

        face_enc_json = encoding_to_json(encodings[0])

        # Save the image to disk
        filename   = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{name.replace(' ', '_')}.jpg"
        save_path  = os.path.join(UPLOAD_DIR, filename)
        pil_save   = Image.fromarray(image_np)
        pil_save.save(save_path, "JPEG")
        image_path = f"uploads/{filename}"  # relative to static/
    else:
        flash("Please upload an image or capture one from your webcam.", "warning")
        return render_template("register.html")

    # ── Save to database ─────────────────────
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO persons (name, mobile, dob, email, address, department, student_id, image_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, mobile, dob, email, address, department, student_id, image_path))
    person_id = cur.lastrowid

    if face_enc_json:
        cur.execute(
            "INSERT INTO encodings (person_id, face_encoding) VALUES (?, ?)",
            (person_id, face_enc_json)
        )

    conn.commit()
    conn.close()

    flash(f"✅ {name} registered successfully!", "success")
    return redirect(url_for("register"))


# ─────────────────────────────────────────────
# Routes — Face Recognition
# ─────────────────────────────────────────────

@app.route("/recognize")
def recognize():
    """Render the live recognition page."""
    return render_template("recognize.html")


@app.route("/api/recognize", methods=["POST"])
def api_recognize():
    """
    Accept a base64 image frame from the browser webcam,
    run face recognition, and return the result as JSON.

    Expected JSON body: { "image": "<base64 string>" }
    """
    data = request.get_json(silent=True)
    if not data or "image" not in data:
        return jsonify({"error": "No image provided"}), 400

    # Decode the frame
    try:
        frame_np = decode_base64_image(data["image"])
    except Exception as e:
        return jsonify({"error": f"Image decode failed: {str(e)}"}), 400

    # Detect faces in the frame
    face_locations = face_recognition.face_locations(frame_np)
    if not face_locations:
        return jsonify({"status": "no_face"})

    # Get encodings for detected faces
    frame_encodings = face_recognition.face_encodings(frame_np, face_locations)

    # Load all stored encodings from DB
    known = load_all_encodings()  # list of (person_id, np.array)

    if not known:
        return jsonify({"status": "unknown", "reason": "No registered persons"})

    known_ids  = [k[0] for k in known]
    known_encs = [k[1] for k in known]

    # Try to match each detected face
    for frame_enc in frame_encodings:
        distances = face_recognition.face_distance(known_encs, frame_enc)
        best_idx  = int(np.argmin(distances))
        best_dist = float(distances[best_idx])

        if best_dist <= FACE_TOLERANCE:
            # Match found!
            person_id = known_ids[best_idx]

            # Fetch person details
            conn   = get_db()
            person = conn.execute(
                "SELECT * FROM persons WHERE id=?", (person_id,)
            ).fetchone()

            # Fetch visible field settings
            settings = conn.execute(
                "SELECT field_name, is_visible FROM display_settings"
            ).fetchall()
            conn.close()

            visible = {row["field_name"]: bool(row["is_visible"]) for row in settings}

            # Build the response, only including visible fields
            result = {
                "status":     "recognized",
                "confidence": round((1 - best_dist) * 100, 1),
                "person": {}
            }

            field_map = {
                "name":       person["name"],
                "mobile":     person["mobile"],
                "dob":        person["dob"],
                "email":      person["email"],
                "address":    person["address"],
                "department": person["department"],
                "student_id": person["student_id"],
            }

            for field, value in field_map.items():
                if visible.get(field, True):
                    result["person"][field] = value or "—"

            # Always include the image path (not controlled by settings)
            result["person"]["image_path"] = person["image_path"]
            result["person"]["id"]         = person_id

            # Log this recognition
            log_recognition(person_id, recognized=True)

            return jsonify(result)

    # No match found within tolerance
    log_recognition(None, recognized=False)
    return jsonify({"status": "unknown"})


def log_recognition(person_id, recognized: bool):
    """Write an entry to recognition_log for dashboard stats."""
    conn = get_db()
    conn.execute(
        "INSERT INTO recognition_log (person_id, recognized) VALUES (?, ?)",
        (person_id, 1 if recognized else 0)
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# Routes — Admin Settings
# ─────────────────────────────────────────────

@app.route("/settings")
def settings():
    """Render the admin settings page."""
    conn   = get_db()
    fields = conn.execute(
        "SELECT field_name, is_visible FROM display_settings ORDER BY id"
    ).fetchall()
    conn.close()
    return render_template("settings.html", fields=fields)


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    """Return current display settings as JSON."""
    conn   = get_db()
    fields = conn.execute(
        "SELECT field_name, is_visible FROM display_settings"
    ).fetchall()
    conn.close()
    return jsonify({row["field_name"]: bool(row["is_visible"]) for row in fields})


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    """
    Save updated field visibility.
    Expected JSON body: { "name": true, "mobile": false, ... }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data provided"}), 400

    conn = get_db()
    for field_name, is_visible in data.items():
        conn.execute(
            "UPDATE display_settings SET is_visible=? WHERE field_name=?",
            (1 if is_visible else 0, field_name)
        )
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Settings saved successfully."})


# ─────────────────────────────────────────────
# Routes — Persons List (for admin reference)
# ─────────────────────────────────────────────

@app.route("/persons")
def persons():
    """List all registered persons."""
    conn    = get_db()
    people  = conn.execute(
        "SELECT id, name, department, student_id, mobile, created_at FROM persons ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return render_template("persons.html", people=people)


@app.route("/persons/delete/<int:person_id>", methods=["POST"])
def delete_person(person_id):
    """Delete a person and their encodings from the database."""
    conn   = get_db()
    person = conn.execute("SELECT image_path FROM persons WHERE id=?", (person_id,)).fetchone()

    if person:
        # Remove image file if it exists
        if person["image_path"]:
            img_file = os.path.join(BASE_DIR, "static", person["image_path"])
            if os.path.exists(img_file):
                os.remove(img_file)

        conn.execute("DELETE FROM encodings WHERE person_id=?", (person_id,))
        conn.execute("DELETE FROM persons WHERE id=?", (person_id,))
        conn.commit()

    conn.close()
    flash("Person deleted successfully.", "success")
    return redirect(url_for("persons"))


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  Face Recognition Student App")
    print("  http://127.0.0.1:5000")
    print("=" * 50)

    # Initialize database tables and seed default data
    init_db()
    seed_settings()
    seed_sample_data()

    # Run Flask in debug mode for development
    app.run(debug=True, host="0.0.0.0", port=5000)
