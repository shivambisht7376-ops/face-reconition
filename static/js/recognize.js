/**
 * recognize.js
 * Handles the live face recognition flow:
 *  1. Start webcam
 *  2. Capture a frame every SCAN_INTERVAL_MS milliseconds
 *  3. POST the frame as base64 to /api/recognize
 *  4. Parse the response and update the result card
 */

// ─── Config ──────────────────────────────────────
const SCAN_INTERVAL_MS = 1500;   // How often to scan (ms)
const JPEG_QUALITY     = 0.75;   // Lower = faster upload, less accurate

// ─── State ───────────────────────────────────────
let stream      = null;
let scanTimer   = null;
let isScanning  = false;

// ─── DOM Shortcuts ────────────────────────────────
const video          = () => document.getElementById('rec-video');
const canvas         = () => document.getElementById('rec-canvas');
const scanOverlay    = () => document.getElementById('scan-overlay');
const placeholder    = () => document.getElementById('rec-placeholder');
const statusBadge    = () => document.getElementById('camera-status-badge');
const startBtn       = () => document.getElementById('btn-rec-start');
const stopBtn        = () => document.getElementById('btn-rec-stop');
const scanInfo       = () => document.getElementById('scan-info');

// Result state divs
const stateWaiting   = () => document.getElementById('result-waiting');
const stateScanning  = () => document.getElementById('result-scanning');
const stateNoFace    = () => document.getElementById('result-no-face');
const stateUnknown   = () => document.getElementById('result-unknown');
const stateMatch     = () => document.getElementById('result-match');

// ─── State Display Helper ─────────────────────────
function showState(activeId) {
    ['result-waiting', 'result-scanning', 'result-no-face', 'result-unknown', 'result-match']
        .forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = (id === activeId) ? '' : 'none';
        });
}

// ─── Start Recognition ────────────────────────────
async function startRecognition() {
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
            audio: false
        });

        const v = video();
        v.srcObject = stream;

        v.addEventListener('playing', () => {
            // Hide placeholder, show scan overlay
            placeholder().style.display = 'none';
            scanOverlay().style.display  = '';
        }, { once: true });

        // Update UI
        statusBadge().textContent = '🟢 Live';
        statusBadge().classList.add('live');
        startBtn().style.display = 'none';
        stopBtn().style.display  = '';
        scanInfo().style.display = '';

        isScanning = true;

        // Show scanning state immediately
        showState('result-scanning');

        // Begin sending frames
        scanTimer = setInterval(captureAndRecognize, SCAN_INTERVAL_MS);

    } catch (err) {
        alert('Could not access webcam: ' + err.message);
    }
}

// ─── Stop Recognition ─────────────────────────────
function stopRecognition() {
    isScanning = false;

    // Clear scan timer
    if (scanTimer) {
        clearInterval(scanTimer);
        scanTimer = null;
    }

    // Stop camera tracks
    if (stream) {
        stream.getTracks().forEach(t => t.stop());
        stream = null;
    }

    // Reset UI
    statusBadge().textContent = '⭕ Camera Off';
    statusBadge().classList.remove('live');
    startBtn().style.display = '';
    stopBtn().style.display  = 'none';
    scanInfo().style.display = 'none';
    scanOverlay().style.display = 'none';
    placeholder().style.display = '';

    showState('result-waiting');
}

// ─── Capture & Send Frame ─────────────────────────
async function captureAndRecognize() {
    if (!isScanning) return;

    const v = video();
    const c = canvas();

    // The video might not be ready yet
    if (!v || !v.videoWidth) return;

    // Draw current frame to hidden canvas
    c.width  = v.videoWidth;
    c.height = v.videoHeight;
    c.getContext('2d').drawImage(v, 0, 0);

    // Convert to base64 JPEG
    const base64 = c.toDataURL('image/jpeg', JPEG_QUALITY);

    try {
        const res  = await fetch('/api/recognize', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ image: base64 })
        });

        if (!res.ok) {
            console.warn('Recognition API error:', res.status);
            return;
        }

        const data = await res.json();
        handleRecognitionResult(data);

    } catch (err) {
        console.error('Network error during recognition:', err);
    }
}

// ─── Handle API Response ──────────────────────────
function handleRecognitionResult(data) {
    if (!isScanning) return;

    switch (data.status) {
        case 'no_face':
            showState('result-no-face');
            break;

        case 'unknown':
            showState('result-unknown');
            break;

        case 'recognized':
            renderMatch(data);
            break;

        default:
            showState('result-scanning');
    }
}

// ─── Render Match Card ────────────────────────────
function renderMatch(data) {
    const person = data.person || {};

    // Person photo
    const photoEl = document.getElementById('match-photo');
    if (person.image_path) {
        photoEl.src   = `/static/${person.image_path}`;
        photoEl.style.display = '';
    } else {
        photoEl.style.display = 'none';
    }

    // Confidence bar
    const pct = data.confidence || 0;
    document.getElementById('confidence-fill').style.width = pct + '%';
    document.getElementById('confidence-pct').textContent  = pct + '%';

    // Field icons map
    const icons = {
        name:       { icon: '👤', label: 'Name'       },
        mobile:     { icon: '📱', label: 'Mobile'     },
        dob:        { icon: '🎂', label: 'Date of Birth' },
        email:      { icon: '✉️', label: 'Email'      },
        address:    { icon: '🏠', label: 'Address'    },
        department: { icon: '🏫', label: 'Department' },
        student_id: { icon: '🪪', label: 'Student ID' },
    };

    // Build info rows from visible fields
    const infoDiv = document.getElementById('match-info');
    infoDiv.innerHTML = '';

    const excludeKeys = ['image_path', 'id'];

    Object.entries(person).forEach(([key, value]) => {
        if (excludeKeys.includes(key)) return;
        if (!value || value === '—') return;

        const meta = icons[key] || { icon: '📋', label: key };

        const row = document.createElement('div');
        row.className = 'info-row';
        row.innerHTML = `
            <span class="info-row-icon">${meta.icon}</span>
            <span class="info-row-label">${meta.label}</span>
            <span class="info-row-value">${escapeHtml(value)}</span>
        `;
        infoDiv.appendChild(row);
    });

    // Show the match state
    showState('result-match');
}

// ─── Utility ──────────────────────────────────────
function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// Stop camera if user navigates away
window.addEventListener('beforeunload', () => {
    if (stream) stream.getTracks().forEach(t => t.stop());
});
