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
import hashlib
import numpy as np
from io import BytesIO
from PIL import Image
from datetime import datetime, date
from functools import wraps
from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for, flash, session
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

# OpenCV for face detection and recognition (works on all Python versions)
import cv2

# Haar cascade face detector (bundled with OpenCV)
_cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
FACE_CASCADE  = cv2.CascadeClassifier(_cascade_path)

# LBP histogram settings
FACE_SIZE     = 128          # resize detected face to this square
LBP_RADIUS    = 1
LBP_POINTS    = 8
HIST_BINS     = 256

# Cosine distance threshold for a positive match (lower = stricter)
FACE_THRESHOLD = 0.18        # tuned for spatial grid LBP histogram cosine similarity
# ─────────────────────────────────────────────
# App Configuration
# ─────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "face-recognition-secret-key"

# Directories
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))

# Vercel Serverless environment uses a read-only filesystem except for /tmp
if os.environ.get("VERCEL"):
    UPLOAD_DIR = "/tmp/uploads"
    DATABASE   = "/tmp/database.db"
else:
    UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
    DATABASE   = os.path.join(BASE_DIR, "database.db")

# Ensure upload folder exists
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ─────────────────────────────────────────────
# Firebase Admin SDK Configuration (Cloud Sync)
# ─────────────────────────────────────────────
FIREBASE_KEY_FILE = os.path.join(BASE_DIR, "firebase-service-key.json")
FIREBASE_ACTIVE = False
firestore_db = None
storage_bucket = None

try:
    import firebase_admin
    from firebase_admin import credentials, firestore, storage
    
    if os.path.exists(FIREBASE_KEY_FILE):
        cred = credentials.Certificate(FIREBASE_KEY_FILE)
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'recognition-app-8770b.firebasestorage.app'
        })
        firestore_db = firestore.client()
        storage_bucket = storage.bucket()
        FIREBASE_ACTIVE = True
        print("[Firebase] Cloud sync initialized successfully using firebase-service-key.json.")
    else:
        print("[Firebase] Credentials file 'firebase-service-key.json' not found. Operating in Local Mode (SQLite).")
except Exception as e:
    print(f"[Firebase] Initialization failed: {e}")

@app.context_processor
def inject_firebase_status():
    return dict(
        firebase_active=FIREBASE_ACTIVE,
        current_user=current_user
    )

# ─────────────────────────────────────────────
# Flask-Login Configuration
# ─────────────────────────────────────────────
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth_login"
login_manager.login_message = "Please log in to access the admin panel."
login_manager.login_message_category = "warning"

class AdminUser(UserMixin):
    """In-memory user object for Flask-Login."""
    def __init__(self, id, username, email, password_hash):
        self.id = str(id)
        self.username = username
        self.email = email
        self.password_hash = password_hash

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM admins WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if row:
        return AdminUser(row["id"], row["username"], row["email"], row["password_hash"])
    return None

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

    # Table: admins — stores admin accounts for system login
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL,
            email         TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def seed_admin():
    """Create the default admin account on first run."""
    DEFAULT_EMAIL    = "shivambisht84@gmail.com"
    DEFAULT_PASSWORD = "@Skye1234"
    DEFAULT_USERNAME = "Shivam Bisht"

    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    if count == 0:
        conn.execute(
            "INSERT INTO admins (username, email, password_hash) VALUES (?, ?, ?)",
            (DEFAULT_USERNAME, DEFAULT_EMAIL, generate_password_hash(DEFAULT_PASSWORD))
        )
        conn.commit()
        print(f"[Auth] Default admin created — Email: {DEFAULT_EMAIL}")
    conn.close()


def seed_settings():
    """Insert default display_settings rows if the table is empty."""
    fields = [
        "name", "mobile", "dob", "email",
        "address", "department", "student_id"
    ]
    if FIREBASE_ACTIVE:
        try:
            doc_ref = firestore_db.collection("config").document("display_settings")
            doc = doc_ref.get()
            if not doc.exists:
                doc_ref.set({field: True for field in fields})
            return
        except Exception as e:
            print(f"[Firebase] Error seeding settings: {e}")
            return

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
    if FIREBASE_ACTIVE:
        try:
            docs = list(firestore_db.collection("persons").limit(1).stream())
            if len(docs) > 0:
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
                    "image_path": "",
                    "face_encoding": [],
                    "created_at": datetime.now().isoformat()
                },
                {
                    "name": "Bob Williams",
                    "mobile": "9123456780",
                    "dob": "2001-07-22",
                    "email": "bob@college.edu",
                    "address": "45, Blue Ave, Shelbyville",
                    "department": "Electronics",
                    "student_id": "EC2021045",
                    "image_path": "",
                    "face_encoding": [],
                    "created_at": datetime.now().isoformat()
                },
                {
                    "name": "Carol Davis",
                    "mobile": "9988776655",
                    "dob": "2003-11-08",
                    "email": "carol@college.edu",
                    "address": "78, Red Rd, Capital City",
                    "department": "Mechanical",
                    "student_id": "ME2023012",
                    "image_path": "",
                    "face_encoding": [],
                    "created_at": datetime.now().isoformat()
                },
            ]
            for s in samples:
                firestore_db.collection("persons").add(s)
            return
        except Exception as e:
            print(f"[Firebase] Error seeding sample data: {e}")
            return

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
    if FIREBASE_ACTIVE:
        try:
            docs = firestore_db.collection("persons").stream()
            result = []
            for doc in docs:
                data = doc.to_dict()
                if "face_encoding" in data and data["face_encoding"]:
                    enc = np.array(data["face_encoding"], dtype=np.float32)
                    result.append((doc.id, enc))
            return result
        except Exception as e:
            print(f"[Firebase] Error loading encodings: {e}")
            return []

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
    Decode a base64-encoded JPEG/PNG string into a numpy RGB array.
    """
    if "," in b64_string:
        b64_string = b64_string.split(",", 1)[1]

    img_bytes = base64.b64decode(b64_string)
    pil_image = Image.open(BytesIO(img_bytes)).convert("RGB")
    return np.array(pil_image)


def get_face_encoding(image_np: np.ndarray):
    """
    Detect the largest face in a numpy RGB image and return a feature vector.

    Strategy:
      1. Convert to greyscale
      2. Run Haar-cascade face detector
      3. Crop the detected face region, resize to FACE_SIZE × FACE_SIZE
      4. Compute uniform LBP histogram (256 bins, normalised)
      5. Return as a 1-D numpy float32 array

    Returns None if no face is found.
    """
    try:
        gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)

        # Detect faces
        faces = FACE_CASCADE.detectMultiScale(
            gray,
            scaleFactor  = 1.1,
            minNeighbors = 5,
            minSize      = (40, 40),
            flags        = cv2.CASCADE_SCALE_IMAGE
        )

        if len(faces) == 0:
            return None

        # Pick the largest face
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])

        # Crop with a small margin, clamped to image bounds
        margin = int(0.15 * min(w, h))
        x1 = max(0, x - margin)
        y1 = max(0, y - margin)
        x2 = min(gray.shape[1], x + w + margin)
        y2 = min(gray.shape[0], y + h + margin)

        face_crop = gray[y1:y2, x1:x2]
        face_resized = cv2.resize(face_crop, (FACE_SIZE, FACE_SIZE))

        # Apply histogram equalisation for lighting robustness
        face_eq = cv2.equalizeHist(face_resized)

        # Compute LBP feature histogram
        hist = _lbp_histogram(face_eq)
        return hist

    except Exception:
        return None


def _lbp_histogram(gray_face: np.ndarray) -> np.ndarray:
    """
    Compute a spatially-aware LBP feature vector by dividing the LBP map
    into an 8x8 grid of blocks, computing normalized histograms for each block,
    and concatenating them.
    """
    img = gray_face.astype(np.int16)
    h, w = img.shape

    # 8 neighbours in clockwise order from top-left
    offsets = [(-1,-1), (-1,0), (-1,1), (0,1), (1,1), (1,0), (1,-1), (0,-1)]
    lbp_map = np.zeros((h - 2, w - 2), dtype=np.uint8)

    center = img[1:-1, 1:-1]
    for bit, (dr, dc) in enumerate(offsets):
        r0, r1 = 1 + dr, h - 1 + dr
        c0, c1 = 1 + dc, w - 1 + dc
        neighbour = img[r0:r1, c0:c1]
        lbp_map  += ((neighbour >= center).astype(np.uint8) << bit)

    # Pad lbp_map back to original dimensions (e.g. 128x128) to divide evenly
    lbp_padded = np.pad(lbp_map, 1, mode='edge')

    # Grid division (8x8 grid)
    grid_rows, grid_cols = 8, 8
    block_h = h // grid_rows
    block_w = w // grid_cols

    histograms = []
    for r in range(grid_rows):
        for c in range(grid_cols):
            block = lbp_padded[r*block_h:(r+1)*block_h, c*block_w:(c+1)*block_w]
            block_hist, _ = np.histogram(block.ravel(), bins=HIST_BINS, range=(0, 256))
            block_hist = block_hist.astype(np.float32)
            total = block_hist.sum()
            if total > 0:
                block_hist /= total
            histograms.append(block_hist)

    # Concatenate all histograms to form a spatially aware feature vector (size 16384)
    return np.concatenate(histograms)


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine distance between two vectors (0 = identical, 1 = opposite)."""
    a_norm = np.linalg.norm(a)
    b_norm = np.linalg.norm(b)
    if a_norm == 0 or b_norm == 0:
        return 1.0
    return float(1.0 - np.dot(a, b) / (a_norm * b_norm))


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
    if FIREBASE_ACTIVE:
        try:
            total_people = len(list(firestore_db.collection("persons").list_documents()))
            logs = firestore_db.collection("recognition_log").stream()
            recognized_today = 0
            unknown_today = 0
            for log in logs:
                data = log.to_dict()
                logged_at = data.get("logged_at", "")
                if logged_at.startswith(today):
                    if data.get("recognized"):
                        recognized_today += 1
                    else:
                        unknown_today += 1
            return jsonify({
                "total_people":      total_people,
                "recognized_today":  recognized_today,
                "unknown_today":     unknown_today,
            })
        except Exception as e:
            print(f"[Firebase] Error fetching stats: {e}")

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
@login_required
def register():
    """Redirect legacy register to admin register."""
    return redirect(url_for("admin_register"), code=307 if request.method == "POST" else 302)





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

    # Get encoding for the incoming frame using LBP
    frame_enc = get_face_encoding(frame_np)
    if frame_enc is None:
        return jsonify({"status": "no_face"})

    # Load all stored encodings from DB
    known = load_all_encodings()  # list of (person_id, np.array)
    if not known:
        return jsonify({"status": "unknown", "reason": "No registered persons"})

    known_ids  = []
    known_encs = []
    for k in known:
        if k[1].shape == frame_enc.shape:
            known_ids.append(k[0])
            known_encs.append(k[1])
        else:
            print(f"[Warning] Skipping encoding for person {k[0]} due to shape mismatch: {k[1].shape} vs {frame_enc.shape}")

    if not known_encs:
        return jsonify({"status": "unknown", "reason": "No valid face signatures matching current format size."})

    # Compute cosine distances to all known encodings
    distances = [cosine_distance(frame_enc, enc) for enc in known_encs]
    best_idx  = int(np.argmin(distances))
    best_dist = distances[best_idx]

    if best_dist <= FACE_THRESHOLD:
        # Match found!
        person_id = known_ids[best_idx]

        # Fetch person details and settings
        if FIREBASE_ACTIVE:
            try:
                doc = firestore_db.collection("persons").document(person_id).get()
                person_data = doc.to_dict() if doc.exists else None

                if person_data:
                    doc_settings = firestore_db.collection("config").document("display_settings").get()
                    settings_data = doc_settings.to_dict() if doc_settings.exists else {}
                    visible = {field: settings_data.get(field, True) for field in ["name", "mobile", "dob", "email", "address", "department", "student_id"]}

                    # Build response
                    result = {
                        "status":     "recognized",
                        "confidence": round((1 - best_dist) * 100, 1),
                        "person": {}
                    }

                    field_map = {
                        "name":       person_data.get("name"),
                        "mobile":     person_data.get("mobile"),
                        "dob":        person_data.get("dob"),
                        "email":      person_data.get("email"),
                        "address":    person_data.get("address"),
                        "department": person_data.get("department"),
                        "student_id": person_data.get("student_id"),
                    }

                    for field, value in field_map.items():
                        if visible.get(field, True):
                            result["person"][field] = value or "—"

                    result["person"]["image_path"] = person_data.get("image_path", "")
                    result["person"]["id"]         = person_id

                    log_recognition(person_id, recognized=True)
                    return jsonify(result)
            except Exception as e:
                print(f"[Firebase] Error retrieving recognized person: {e}")

        # Local Fallback
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

    # No match found within threshold
    log_recognition(None, recognized=False)
    return jsonify({"status": "unknown"})


def log_recognition(person_id, recognized: bool):
    """Write an entry to recognition_log for dashboard stats."""
    if FIREBASE_ACTIVE:
        try:
            doc_ref = firestore_db.collection("recognition_log").document()
            doc_ref.set({
                "person_id": person_id,
                "recognized": recognized,
                "logged_at": datetime.now().isoformat()
            })
            return
        except Exception as e:
            print(f"[Firebase] Error logging recognition: {e}")

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
@login_required
def settings():
    """Redirect legacy settings to admin settings."""
    return redirect(url_for("admin_settings"))


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    """Return current display settings as JSON."""
    if FIREBASE_ACTIVE:
        try:
            doc_ref = firestore_db.collection("config").document("display_settings")
            doc = doc_ref.get()
            data = doc.to_dict() if doc.exists else {}
            result = {}
            for field in ["name", "mobile", "dob", "email", "address", "department", "student_id"]:
                result[field] = data.get(field, True)
            return jsonify(result)
        except Exception as e:
            print(f"[Firebase] Error getting settings: {e}")

    conn   = get_db()
    fields = conn.execute(
        "SELECT field_name, is_visible FROM display_settings"
    ).fetchall()
    conn.close()
    return jsonify({row["field_name"]: bool(row["is_visible"]) for row in fields})


@app.route("/api/settings", methods=["POST"])
@login_required
def api_settings_post():
    """
    Save updated field visibility.
    Expected JSON body: { "name": true, "mobile": false, ... }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data provided"}), 400

    if FIREBASE_ACTIVE:
        try:
            doc_ref = firestore_db.collection("config").document("display_settings")
            doc_ref.set(data, merge=True)
            return jsonify({"success": True, "message": "Settings saved successfully to Firestore."})
        except Exception as e:
            print(f"[Firebase] Error saving settings: {e}")
            return jsonify({"error": str(e)}), 500

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
@login_required
def persons():
    """Redirect legacy persons to admin persons."""
    return redirect(url_for("admin_persons"))


@app.route("/persons/delete/<person_id>", methods=["POST"])
@login_required
def delete_person(person_id):
    """Redirect legacy delete action preserving request method."""
    return redirect(url_for("admin_delete_person", person_id=person_id), code=307)


# ─────────────────────────────────────────────
# Auth Routes — Login / Signup / Logout
# ─────────────────────────────────────────────

@app.route("/auth/login", methods=["GET", "POST"])
def auth_login():
    """Login page for admin access."""
    if current_user.is_authenticated:
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "on"

        conn = get_db()
        row  = conn.execute("SELECT * FROM admins WHERE email=?", (email,)).fetchone()
        conn.close()

        if row and check_password_hash(row["password_hash"], password):
            user = AdminUser(row["id"], row["username"], row["email"], row["password_hash"])
            login_user(user, remember=remember)
            next_page = request.args.get("next")
            flash(f"Welcome back, {user.username}! 👋", "success")
            return redirect(next_page or url_for("admin_dashboard"))
        else:
            flash("Invalid email or password. Please try again.", "danger")

    return render_template("auth/login.html")


@app.route("/auth/signup", methods=["GET", "POST"])
@login_required
def auth_signup():
    """Signup page — only accessible by a logged-in admin."""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm_password", "")

        if not username or not email or not password:
            flash("All fields are required.", "danger")
            return render_template("auth/signup.html")

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("auth/signup.html")

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return render_template("auth/signup.html")

        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO admins (username, email, password_hash) VALUES (?, ?, ?)",
                (username, email, generate_password_hash(password))
            )
            conn.commit()
            conn.close()
            flash(f"Admin account created for {email}. They can now log in.", "success")
            return redirect(url_for("admin_settings"))
        except sqlite3.IntegrityError:
            flash("An admin with that email already exists.", "danger")
            return render_template("auth/signup.html")

    return render_template("auth/signup.html")


@app.route("/auth/logout")
@login_required
def auth_logout():
    """Log out the current admin."""
    logout_user()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("auth_login"))


# ─────────────────────────────────────────────
# Admin Routes — Protected Admin Panel
# ─────────────────────────────────────────────

@app.route("/admin")
@login_required
def admin_index():
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/dashboard")
@login_required
def admin_dashboard():
    """Admin dashboard with stats and recent activity."""
    today = date.today().isoformat()
    conn  = get_db()

    total_people = conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0]
    total_admins = conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    recognized_today = conn.execute(
        "SELECT COUNT(*) FROM recognition_log WHERE recognized=1 AND DATE(logged_at)=?", (today,)
    ).fetchone()[0]
    unknown_today = conn.execute(
        "SELECT COUNT(*) FROM recognition_log WHERE recognized=0 AND DATE(logged_at)=?", (today,)
    ).fetchone()[0]

    # Last 7 days recognition trend
    trend_data = conn.execute("""
        SELECT DATE(logged_at) as day,
               SUM(CASE WHEN recognized=1 THEN 1 ELSE 0 END) as recognized,
               SUM(CASE WHEN recognized=0 THEN 1 ELSE 0 END) as unknown
        FROM recognition_log
        WHERE DATE(logged_at) >= DATE('now', '-6 days')
        GROUP BY DATE(logged_at)
        ORDER BY day ASC
    """).fetchall()

    # Recent 10 recognition events
    recent_logs = conn.execute("""
        SELECT rl.id, rl.recognized, rl.logged_at,
               p.name, p.department, p.student_id
        FROM recognition_log rl
        LEFT JOIN persons p ON rl.person_id = p.id
        ORDER BY rl.logged_at DESC
        LIMIT 10
    """).fetchall()

    conn.close()

    return render_template("admin/dashboard.html",
        total_people=total_people,
        total_admins=total_admins,
        recognized_today=recognized_today,
        unknown_today=unknown_today,
        trend_data=[dict(r) for r in trend_data],
        recent_logs=recent_logs
    )


@app.route("/admin/persons")
@login_required
def admin_persons():
    """Admin persons list with search support."""
    q = request.args.get("q", "").strip()
    conn = get_db()
    if q:
        people = conn.execute(
            """SELECT id, name, department, student_id, mobile, email, dob, created_at
               FROM persons WHERE name LIKE ? OR student_id LIKE ? OR department LIKE ?
               ORDER BY id DESC""",
            (f"%{q}%", f"%{q}%", f"%{q}%")
        ).fetchall()
    else:
        people = conn.execute(
            "SELECT id, name, department, student_id, mobile, email, dob, created_at FROM persons ORDER BY id DESC"
        ).fetchall()
    conn.close()
    return render_template("admin/persons.html", people=people, query=q)


@app.route("/admin/persons/edit/<int:person_id>", methods=["POST"])
@login_required
def admin_edit_person(person_id):
    """Inline edit of a person's details."""
    name       = request.form.get("name", "").strip()
    mobile     = request.form.get("mobile", "").strip()
    email      = request.form.get("email", "").strip()
    dob        = request.form.get("dob", "").strip()
    department = request.form.get("department", "").strip()
    student_id = request.form.get("student_id", "").strip()
    address    = request.form.get("address", "").strip()

    conn = get_db()
    conn.execute("""
        UPDATE persons SET name=?, mobile=?, email=?, dob=?, department=?, student_id=?, address=?
        WHERE id=?
    """, (name, mobile, email, dob, department, student_id, address, person_id))
    conn.commit()
    conn.close()
    flash(f"✅ {name}'s details updated successfully.", "success")
    return redirect(url_for("admin_persons"))


@app.route("/admin/persons/delete/<person_id>", methods=["POST"])
@login_required
def admin_delete_person(person_id):
    """Delete a person — admin protected."""
    # Firebase path
    if FIREBASE_ACTIVE:
        try:
            doc_ref = firestore_db.collection("persons").document(person_id)
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                image_url = data.get("image_path", "")
                if image_url and "storage.googleapis.com" in image_url:
                    try:
                        filename  = image_url.split("/")[-1].split("?")[0]
                        blob_path = f"uploads/{filename}"
                        blob = storage_bucket.blob(blob_path)
                        if blob.exists():
                            blob.delete()
                    except Exception as se:
                        print(f"[Firebase] Storage delete error: {se}")
                doc_ref.delete()
            flash("Person deleted from Firebase.", "success")
            return redirect(url_for("admin_persons"))
        except Exception as e:
            flash(f"Firebase delete error: {e}", "danger")
            return redirect(url_for("admin_persons"))

    # SQLite path
    conn   = get_db()
    person = conn.execute("SELECT image_path FROM persons WHERE id=?", (person_id,)).fetchone()
    if person:
        if person["image_path"]:
            img_file = os.path.join(BASE_DIR, "static", person["image_path"])
            if os.path.exists(img_file):
                os.remove(img_file)
        conn.execute("DELETE FROM encodings WHERE person_id=?", (person_id,))
        conn.execute("DELETE FROM persons WHERE id=?", (person_id,))
        conn.commit()
    conn.close()
    flash("Person deleted successfully.", "success")
    return redirect(url_for("admin_persons"))


@app.route("/admin/register", methods=["GET", "POST"])
@login_required
def admin_register():
    """Admin: register a new student."""
    if request.method == "GET":
        return render_template("admin/register.html")

    name       = request.form.get("name", "").strip()
    mobile     = request.form.get("mobile", "").strip()
    dob        = request.form.get("dob", "").strip()
    email      = request.form.get("email", "").strip()
    address    = request.form.get("address", "").strip()
    department = request.form.get("department", "").strip()
    student_id = request.form.get("student_id", "").strip()

    if not name:
        flash("Name is required.", "danger")
        return render_template("admin/register.html")

    if student_id:
        if FIREBASE_ACTIVE:
            try:
                existing = firestore_db.collection("persons").where("student_id", "==", student_id).limit(1).stream()
                if list(existing):
                    flash(f"A student with Student ID '{student_id}' is already registered.", "danger")
                    return render_template("admin/register.html")
            except Exception as e:
                print(f"[Firebase] Error checking existing student ID: {e}")
        else:
            conn = get_db()
            existing = conn.execute("SELECT id FROM persons WHERE student_id=?", (student_id,)).fetchone()
            conn.close()
            if existing:
                flash(f"A student with Student ID '{student_id}' is already registered.", "danger")
                return render_template("admin/register.html")

    image_np   = None
    image_path = ""
    filename   = ""

    uploaded_file = request.files.get("face_image")
    if uploaded_file and uploaded_file.filename:
        pil_img  = Image.open(uploaded_file.stream).convert("RGB")
        image_np = np.array(pil_img)
    elif request.form.get("webcam_image"):
        try:
            image_np = decode_base64_image(request.form["webcam_image"])
        except Exception:
            flash("Could not read webcam image.", "danger")
            return render_template("admin/register.html")

    face_enc_json = None
    if image_np is not None:
        encoding = get_face_encoding(image_np)
        if encoding is None:
            flash("No face detected. Use a clear frontal photo.", "warning")
            return render_template("admin/register.html")

        face_enc_json = encoding_to_json(encoding)
        filename      = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{name.replace(' ', '_')}.jpg"
        save_path     = os.path.join(UPLOAD_DIR, filename)
        Image.fromarray(image_np).save(save_path, "JPEG")
        image_path    = f"uploads/{filename}"
    else:
        flash("Please provide a face image.", "warning")
        return render_template("admin/register.html")

    if FIREBASE_ACTIVE:
        try:
            image_url = ""
            if image_path:
                local_path = os.path.join(BASE_DIR, "static", image_path)
                if os.path.exists(local_path):
                    blob = storage_bucket.blob(f"uploads/{filename}")
                    blob.upload_from_filename(local_path)
                    blob.make_public()
                    image_url = blob.public_url

            firestore_db.collection("persons").document().set({
                "name": name, "mobile": mobile, "dob": dob,
                "email": email, "address": address, "department": department,
                "student_id": student_id,
                "image_path": image_url or image_path,
                "face_encoding": json.loads(face_enc_json) if face_enc_json else [],
                "created_at": datetime.now().isoformat()
            })
            flash(f"✅ {name} registered in Firebase!", "success")
            return redirect(url_for("admin_register"))
        except Exception as e:
            flash(f"Firebase error: {e}", "danger")
            return render_template("admin/register.html")

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO persons (name, mobile, dob, email, address, department, student_id, image_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, mobile, dob, email, address, department, student_id, image_path))
    pid = cur.lastrowid
    if face_enc_json:
        cur.execute("INSERT INTO encodings (person_id, face_encoding) VALUES (?, ?)", (pid, face_enc_json))
    conn.commit()
    conn.close()
    flash(f"✅ {name} registered successfully!", "success")
    return redirect(url_for("admin_register"))


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
def admin_settings():
    """Admin settings — field visibility + admin management."""
    if request.method == "POST":
        data = request.get_json(silent=True)
        if data:
            if FIREBASE_ACTIVE:
                try:
                    firestore_db.collection("config").document("display_settings").set(data, merge=True)
                    return jsonify({"success": True, "message": "Settings saved to Firestore."})
                except Exception as e:
                    return jsonify({"error": str(e)}), 500

            conn = get_db()
            for field_name, is_visible in data.items():
                conn.execute(
                    "UPDATE display_settings SET is_visible=? WHERE field_name=?",
                    (1 if is_visible else 0, field_name)
                )
            conn.commit()
            conn.close()
            return jsonify({"success": True, "message": "Settings saved."})

    # GET — load settings and admin list
    if FIREBASE_ACTIVE:
        try:
            doc = firestore_db.collection("config").document("display_settings").get()
            data = doc.to_dict() if doc.exists else {}
            fields = [{"field_name": f, "is_visible": data.get(f, True)}
                      for f in ["name", "mobile", "dob", "email", "address", "department", "student_id"]]
        except Exception:
            fields = []
    else:
        conn   = get_db()
        fields = conn.execute("SELECT field_name, is_visible FROM display_settings ORDER BY id").fetchall()
        conn.close()

    conn    = get_db()
    admins  = conn.execute("SELECT id, username, email, created_at FROM admins ORDER BY id").fetchall()
    conn.close()

    return render_template("admin/settings.html", fields=fields, admins=admins)


@app.route("/admin/admins/delete/<int:admin_id>", methods=["POST"])
@login_required
def admin_delete_admin(admin_id):
    """Delete an admin account (can't delete your own)."""
    if str(admin_id) == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("admin_settings"))

    conn  = get_db()
    count = conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    if count <= 1:
        flash("Cannot delete the last admin account.", "danger")
        conn.close()
        return redirect(url_for("admin_settings"))

    conn.execute("DELETE FROM admins WHERE id=?", (admin_id,))
    conn.commit()
    conn.close()
    flash("Admin account deleted.", "success")
    return redirect(url_for("admin_settings"))


@app.route("/admin/logs")
@login_required
def admin_logs():
    """Recognition event log with date/type filters."""
    filter_type = request.args.get("type", "all")
    filter_date = request.args.get("date", "")
    page        = int(request.args.get("page", 1))
    per_page    = 20

    conn = get_db()
    where_clauses, params = [], []

    if filter_type == "recognized":
        where_clauses.append("rl.recognized=1")
    elif filter_type == "unknown":
        where_clauses.append("rl.recognized=0")

    if filter_date:
        where_clauses.append("DATE(rl.logged_at)=?")
        params.append(filter_date)

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    total = conn.execute(f"SELECT COUNT(*) FROM recognition_log rl {where_sql}", params).fetchone()[0]

    logs = conn.execute(f"""
        SELECT rl.id, rl.recognized, rl.logged_at,
               p.name, p.department, p.student_id, p.image_path
        FROM recognition_log rl
        LEFT JOIN persons p ON rl.person_id = p.id
        {where_sql}
        ORDER BY rl.logged_at DESC
        LIMIT ? OFFSET ?
    """, params + [per_page, (page-1)*per_page]).fetchall()
    conn.close()

    total_pages = (total + per_page - 1) // per_page
    return render_template("admin/logs.html",
        logs=logs, total=total, page=page,
        total_pages=total_pages,
        filter_type=filter_type, filter_date=filter_date
    )


@app.route("/admin/profile", methods=["GET", "POST"])
@login_required
def admin_profile():
    """Change admin username or password."""
    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_name":
            username = request.form.get("username", "").strip()
            if not username:
                flash("Username cannot be empty.", "danger")
            else:
                conn = get_db()
                conn.execute("UPDATE admins SET username=? WHERE id=?", (username, current_user.id))
                conn.commit()
                conn.close()
                flash("Username updated successfully.", "success")

        elif action == "update_password":
            current_pw  = request.form.get("current_password", "")
            new_pw      = request.form.get("new_password", "")
            confirm_pw  = request.form.get("confirm_password", "")

            if not current_user.check_password(current_pw):
                flash("Current password is incorrect.", "danger")
            elif new_pw != confirm_pw:
                flash("New passwords do not match.", "danger")
            elif len(new_pw) < 8:
                flash("Password must be at least 8 characters.", "danger")
            else:
                conn = get_db()
                conn.execute("UPDATE admins SET password_hash=? WHERE id=?",
                             (generate_password_hash(new_pw), current_user.id))
                conn.commit()
                conn.close()
                flash("Password changed successfully.", "success")

        return redirect(url_for("admin_profile"))

    return render_template("admin/profile.html")


# ─────────────────────────────────────────────
# Routes — Attendance System
# ─────────────────────────────────────────────

@app.route("/admin/attendance")
@login_required
def admin_attendance():
    """
    Daily attendance report page.
    A student is 'present' if they have at least 1 recognized=1 log on the selected date.
    """
    selected_date = request.args.get("date", date.today().isoformat())
    dept_filter   = request.args.get("department", "").strip()
    page          = int(request.args.get("page", 1))
    per_page      = 20

    conn = get_db()

    # All departments for the filter dropdown
    departments = [
        r[0] for r in
        conn.execute("SELECT DISTINCT department FROM persons WHERE department IS NOT NULL AND department != '' ORDER BY department").fetchall()
    ]

    # Build persons query with optional department filter
    if dept_filter:
        persons_rows = conn.execute(
            "SELECT id, name, student_id, department, image_path FROM persons WHERE department=? ORDER BY name",
            (dept_filter,)
        ).fetchall()
    else:
        persons_rows = conn.execute(
            "SELECT id, name, student_id, department, image_path FROM persons ORDER BY name"
        ).fetchall()

    total_students = len(persons_rows)

    # For each person, check recognition_log for presence on selected_date
    attendance_data = []
    present_count   = 0

    for p in persons_rows:
        pid = p["id"]
        log_row = conn.execute("""
            SELECT MIN(logged_at) as first_seen, COUNT(*) as scan_count
            FROM recognition_log
            WHERE person_id=? AND recognized=1 AND DATE(logged_at)=?
        """, (pid, selected_date)).fetchone()

        is_present  = log_row["scan_count"] > 0 if log_row else False
        first_seen  = log_row["first_seen"]  if log_row else None
        scan_count  = log_row["scan_count"]  if log_row else 0

        if is_present:
            present_count += 1

        attendance_data.append({
            "id":         pid,
            "name":       p["name"],
            "student_id": p["student_id"] or "—",
            "department": p["department"] or "—",
            "image_path": p["image_path"] or "",
            "present":    is_present,
            "first_seen": first_seen,
            "scan_count": scan_count,
        })

    # Sort: present first, then absent; then alphabetically
    attendance_data.sort(key=lambda x: (not x["present"], x["name"]))

    # Paginate
    total_pages = max(1, (total_students + per_page - 1) // per_page)
    page        = max(1, min(page, total_pages))
    paginated   = attendance_data[(page - 1) * per_page: page * per_page]

    absent_count = total_students - present_count

    conn.close()

    return render_template(
        "admin/attendance.html",
        attendance=paginated,
        total_students=total_students,
        present_count=present_count,
        absent_count=absent_count,
        selected_date=selected_date,
        departments=departments,
        dept_filter=dept_filter,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
    )


@app.route("/api/attendance/daily")
@login_required
def api_attendance_daily():
    """
    Return unique present student count per day for the last 30 days.
    Used by the 30-day trend chart on the attendance page.
    """
    conn = get_db()
    rows = conn.execute("""
        SELECT DATE(logged_at) as day,
               COUNT(DISTINCT person_id) as present_count
        FROM recognition_log
        WHERE recognized=1
          AND DATE(logged_at) >= DATE('now', '-29 days')
          AND person_id IS NOT NULL
        GROUP BY DATE(logged_at)
        ORDER BY day ASC
    """).fetchall()
    conn.close()
    return jsonify([{"day": r["day"], "present": r["present_count"]} for r in rows])


@app.route("/api/attendance/hourly")
@login_required
def api_attendance_hourly():
    """
    Return unique recognized student count broken down by hour (0–23)
    for the given date (default: today).
    Used by the hourly heatmap chart on the attendance page.
    """
    selected_date = request.args.get("date", date.today().isoformat())
    conn = get_db()
    rows = conn.execute("""
        SELECT CAST(strftime('%H', logged_at) AS INTEGER) as hour,
               COUNT(DISTINCT person_id) as unique_students
        FROM recognition_log
        WHERE recognized=1
          AND DATE(logged_at)=?
          AND person_id IS NOT NULL
        GROUP BY hour
        ORDER BY hour ASC
    """, (selected_date,)).fetchall()
    conn.close()

    # Build a full 0–23 array; hours with no data get 0
    hourly = {r["hour"]: r["unique_students"] for r in rows}
    result = [{"hour": h, "count": hourly.get(h, 0)} for h in range(24)]
    return jsonify(result)


@app.route("/admin/attendance/export")
@login_required
def admin_attendance_export():
    """
    Export attendance as a CSV file for the selected date and optional department filter.
    """
    import csv
    from io import StringIO
    from flask import Response

    selected_date = request.args.get("date", date.today().isoformat())
    dept_filter   = request.args.get("department", "").strip()

    conn = get_db()

    if dept_filter:
        persons_rows = conn.execute(
            "SELECT id, name, student_id, department FROM persons WHERE department=? ORDER BY name",
            (dept_filter,)
        ).fetchall()
    else:
        persons_rows = conn.execute(
            "SELECT id, name, student_id, department FROM persons ORDER BY name"
        ).fetchall()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Student ID", "Department", "Status", "First Check-in", "Total Scans", "Date"])

    for p in persons_rows:
        log_row = conn.execute("""
            SELECT MIN(logged_at) as first_seen, COUNT(*) as scan_count
            FROM recognition_log
            WHERE person_id=? AND recognized=1 AND DATE(logged_at)=?
        """, (p["id"], selected_date)).fetchone()

        is_present  = log_row["scan_count"] > 0 if log_row else False
        first_seen  = log_row["first_seen"][11:19] if log_row and log_row["first_seen"] else "—"
        scan_count  = log_row["scan_count"] if log_row else 0

        writer.writerow([
            p["name"],
            p["student_id"] or "—",
            p["department"] or "—",
            "Present" if is_present else "Absent",
            first_seen,
            scan_count,
            selected_date,
        ])

    conn.close()

    output.seek(0)
    filename = f"attendance_{selected_date}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


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
    seed_admin()
    seed_settings()
    seed_sample_data()

    # Run Flask in debug mode for development
    app.run(debug=True, host="0.0.0.0", port=5000)
