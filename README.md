# 🎓 FaceID — Face Recognition Student Information System

A locally-hosted web application that identifies registered students via webcam using AI-powered face recognition.  
Built with **Flask**, **SQLite**, **OpenCV**, and **face_recognition** — no internet or cloud services required.

---

## 📸 Features

| Feature | Description |
|---|---|
| **Live Recognition** | Detects and identifies faces from your webcam in real-time |
| **Student Registration** | Register students with photo (webcam or file upload) + details |
| **Admin Settings** | Toggle which fields appear in recognition results |
| **Dashboard** | View total registrations and today's recognition stats |
| **Persons List** | Browse and delete registered students |
| **Fully Local** | All data stored in SQLite — no cloud, no internet needed |

---

## 🛠️ Tech Stack

- **Backend**: Python 3.8+ / Flask
- **Face Recognition**: `face_recognition` (dlib) + OpenCV
- **Database**: SQLite (auto-created on first run)
- **Frontend**: HTML5 / CSS3 / Vanilla JavaScript
- **Storage**: Local file system (`static/uploads/`)

---

## 🚀 Setup Instructions

### 1. Prerequisites

- Python **3.8 – 3.11** (recommended: 3.10)
- A working **webcam**
- Windows / macOS / Linux

> ⚠️ **Windows users**: `face_recognition` requires `dlib`, which needs CMake and C++ build tools.  
> The easiest way is to install a pre-built wheel — see [Troubleshooting](#troubleshooting) below.

---

### 2. Clone / Download the Project

```bash
# If you have git:
git clone <your-repo-url>
cd face-recognition-app

# Or just download and extract the ZIP, then open a terminal in the folder.
```

---

### 3. Create a Virtual Environment (Recommended)

```bash
python -m venv venv

# Activate it:
# Windows:
venv\Scripts\activate

# macOS / Linux:
source venv/bin/activate
```

---

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `flask` — web framework
- `face-recognition` — face detection + recognition (uses dlib)
- `opencv-python` — image processing
- `numpy` — numerical arrays
- `Pillow` — image handling

---

### 5. Run the App

```bash
python app.py
```

You should see:
```
==================================================
  Face Recognition Student App
  http://127.0.0.1:5000
==================================================
```

Open your browser and go to: **http://127.0.0.1:5000**

---

## 📋 Usage Guide

### Step 1 — Register a Student
1. Click **Register** in the sidebar.
2. Start your webcam and capture a clear face photo (or upload an image file).
3. Fill in the student details (Name is required; rest are optional).
4. Click **Register Person**.

### Step 2 — Recognize a Face
1. Click **Recognize** in the sidebar.
2. Click **Start Recognition**.
3. Look at the camera — the system scans every 1.5 seconds.
4. If matched, the student's info card appears on the right.

### Step 3 — Configure Display Fields
1. Click **Admin Settings** in the sidebar.
2. Toggle any fields ON or OFF.
3. Click **Save Settings**.
4. Go back to Recognize — toggled-off fields will be hidden.

---

## 📁 Project Structure

```
face-recognition-app/
├── app.py                  # Flask application (all routes + DB logic)
├── database.db             # SQLite database (auto-created on first run)
├── requirements.txt        # Python dependencies
├── README.md               # This file
│
├── templates/
│   ├── base.html           # Shared layout (sidebar, topbar, flash messages)
│   ├── dashboard.html      # Dashboard page
│   ├── register.html       # Student registration page
│   ├── recognize.html      # Live recognition page
│   ├── settings.html       # Admin settings page
│   └── persons.html        # All registered persons list
│
└── static/
    ├── css/
    │   └── style.css       # Complete design system
    ├── js/
    │   ├── dashboard.js    # Dashboard stats animation
    │   ├── register.js     # Webcam capture + form logic
    │   ├── recognize.js    # Live recognition loop
    │   └── settings.js     # Toggle + preview logic
    └── uploads/            # Saved face images (auto-created)
```

---

## ⚙️ Configuration

Open `app.py` and look for this constant near the top:

```python
FACE_TOLERANCE = 0.5   # 0.0 = strictest, 1.0 = most lenient
```

- **Lower value** → fewer false matches, but may miss correct ones
- **Higher value** → more matches, but may produce wrong results
- **0.5** is the recommended default for most use cases

---

## 🔧 Troubleshooting

### `dlib` / `face_recognition` install fails on Windows

```bash
# Option 1: Install CMake first
pip install cmake
pip install dlib
pip install face-recognition

# Option 2: Use a pre-built dlib wheel
# Download matching .whl from: https://github.com/z-mahmud22/Dlib_Windows_Python3.x
pip install dlib-<version>-cp310-cp310-win_amd64.whl
pip install face-recognition
```

### Webcam not working in browser

- Make sure you're opening `http://127.0.0.1:5000` (not `file://`)
- Browser requires `localhost` or HTTPS for webcam access
- Allow camera permissions when the browser asks

### Face not detected during registration

- Use a **clear, well-lit**, frontal face photo
- Avoid sunglasses, masks, or heavy shadows
- The face should occupy at least 20% of the image

### Recognition is slow

- Ensure no other heavy programs are running
- Reduce `JPEG_QUALITY` in `recognize.js` from `0.75` to `0.5`
- Increase `SCAN_INTERVAL_MS` in `recognize.js` from `1500` to `2500`

---

## 🗃️ Database Schema

```sql
-- Registered persons
CREATE TABLE persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    mobile TEXT, dob TEXT, email TEXT,
    address TEXT, department TEXT, student_id TEXT,
    image_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Face encodings (128-dimensional vectors stored as JSON)
CREATE TABLE encodings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL REFERENCES persons(id),
    face_encoding TEXT NOT NULL
);

-- Field visibility settings for the admin panel
CREATE TABLE display_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_name TEXT NOT NULL UNIQUE,
    is_visible INTEGER NOT NULL DEFAULT 1
);

-- Recognition events log (for dashboard stats)
CREATE TABLE recognition_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER,
    recognized INTEGER NOT NULL,
    logged_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

## 📝 Notes for College Presentation

- The app comes pre-seeded with **3 sample records** (no real face encodings — for UI demo only).
- To demonstrate recognition, **register yourself first** using your webcam.
- Keep the browser and Flask server on the **same machine**.
- Tested with Python 3.10 on Windows 11.

---

## 📄 License

This project is intended for **educational purposes only** as a college project.
