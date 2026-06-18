/**
 * register.js
 * Handles:
 *   - Tab switching between "Webcam" and "Upload File" modes
 *   - Starting the webcam stream
 *   - Capturing a photo from the webcam into a base64 string
 *   - Previewing an uploaded image file
 *   - Validating the form before submission
 *   - Dragging & dropping images onto the upload zone
 */

// ─── State ───────────────────────────────────────
let stream          = null;   // MediaStream from webcam
let capturedBase64  = '';     // Captured photo (base64 JPEG)
let activeTab       = 'webcam'; // 'webcam' | 'upload'
let selectedFile    = null;   // File chosen via file input

// ─── Tab Switching ────────────────────────────────
function switchTab(tab) {
    activeTab = tab;

    // Update button states
    document.getElementById('tab-webcam-btn').classList.toggle('active', tab === 'webcam');
    document.getElementById('tab-upload-btn').classList.toggle('active', tab === 'upload');

    // Show/hide panels
    document.getElementById('tab-webcam').style.display = tab === 'webcam' ? '' : 'none';
    document.getElementById('tab-upload').style.display = tab === 'upload'  ? '' : 'none';

    // Stop camera if switching away from webcam
    if (tab !== 'webcam' && stream) {
        stopCam();
    }
}

// ─── Webcam ───────────────────────────────────────
async function startCam() {
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
            audio: false
        });

        const video = document.getElementById('reg-video');
        video.srcObject = stream;

        // Hide the placeholder when video starts playing
        video.addEventListener('playing', () => {
            const placeholder = document.getElementById('cam-placeholder');
            if (placeholder) placeholder.style.display = 'none';
        }, { once: true });

        document.getElementById('btn-start-cam').disabled   = true;
        document.getElementById('btn-capture').disabled     = false;

    } catch (err) {
        alert('Could not access webcam.\n\nPlease allow camera permissions in your browser, or use the "Upload File" tab instead.\n\nError: ' + err.message);
    }
}

function stopCam() {
    if (stream) {
        stream.getTracks().forEach(track => track.stop());
        stream = null;
    }
    document.getElementById('btn-start-cam').disabled = false;
    document.getElementById('btn-capture').disabled   = true;

    const placeholder = document.getElementById('cam-placeholder');
    if (placeholder) placeholder.style.display = '';
}

function capturePhoto() {
    const video  = document.getElementById('reg-video');
    const canvas = document.getElementById('reg-canvas');

    if (!stream || !video.videoWidth) {
        alert('Camera is not ready yet. Please wait a moment.');
        return;
    }

    // Draw the current video frame onto the hidden canvas
    canvas.width  = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);

    // Convert canvas to base64 JPEG
    capturedBase64 = canvas.toDataURL('image/jpeg', 0.9);

    // Show the preview
    const previewDiv = document.getElementById('capture-preview');
    const img        = document.getElementById('captured-img');
    img.src          = capturedBase64;
    previewDiv.style.display = '';

    // Stop the camera after capture
    stopCam();
}

function retakePhoto() {
    capturedBase64 = '';
    document.getElementById('capture-preview').style.display = 'none';
    document.getElementById('cam-placeholder').style.display = '';
    startCam();
}

// ─── File Upload ──────────────────────────────────
function previewUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    selectedFile = file;

    const reader = new FileReader();
    reader.onload = (e) => {
        const previewDiv = document.getElementById('upload-preview');
        const img        = document.getElementById('uploaded-img');
        img.src          = e.target.result;
        previewDiv.style.display = '';
    };
    reader.readAsDataURL(file);
}

// Drag-and-drop support for the upload zone
document.addEventListener('DOMContentLoaded', () => {
    const zone = document.getElementById('upload-zone');
    if (!zone) return;

    zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.style.borderColor = 'var(--primary)';
        zone.style.background  = 'var(--primary-light)';
    });

    zone.addEventListener('dragleave', () => {
        zone.style.borderColor = '';
        zone.style.background  = '';
    });

    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.style.borderColor = '';
        zone.style.background  = '';

        const file = e.dataTransfer.files[0];
        if (file && file.type.startsWith('image/')) {
            // Manually trigger the file input change
            const dt = new DataTransfer();
            dt.items.add(file);
            const input = document.getElementById('face_image_input');
            input.files = dt.files;
            previewUpload({ target: input });
        }
    });
});

// ─── Form Submission ──────────────────────────────
function prepareSubmit() {
    const nameField = document.getElementById('name');
    const errName   = document.getElementById('err-name');

    // Clear previous errors
    errName.textContent = '';

    // Validate name
    if (!nameField.value.trim()) {
        errName.textContent = 'Name is required.';
        nameField.focus();
        return false;
    }

    // Webcam mode — inject base64 into hidden field
    if (activeTab === 'webcam') {
        if (!capturedBase64) {
            alert('Please capture a photo using the webcam first,\nor switch to "Upload File" to upload an image.');
            return false;
        }
        document.getElementById('form-webcam-image').value = capturedBase64;

        // Make sure no file is submitted alongside
        const fileInput = document.getElementById('face_image_input');
        fileInput.value = '';
    }
    // Upload mode — file input is submitted by the form directly,
    // but we also need to name it correctly (name="face_image")
    else {
        if (!selectedFile) {
            alert('Please select or drag-and-drop a face image to upload.');
            return false;
        }
        // Rename the file input so Flask picks it up as "face_image"
        document.getElementById('face_image_input').name = 'face_image';

        // Clear the webcam hidden field
        document.getElementById('form-webcam-image').value = '';
    }

    // Show loading state on button
    const btn = document.getElementById('btn-submit');
    btn.innerHTML = '⏳ Saving…';
    btn.disabled  = true;

    return true;  // allow form submit
}
