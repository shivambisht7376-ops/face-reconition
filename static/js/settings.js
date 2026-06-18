/**
 * settings.js
 * Handles the Admin Settings page:
 *  - Reads toggle states and POSTs to /api/settings
 *  - Updates the preview card in real-time as toggles change
 *  - Provides a "Reset to Defaults" action
 */

// ─── Field Metadata (for preview card) ───────────
const FIELD_META = {
    name:       { label: 'Name',         sample: 'Alice Johnson'   },
    mobile:     { label: 'Mobile',       sample: '9876543210'      },
    dob:        { label: 'Date of Birth',sample: '15 Mar 2002'     },
    email:      { label: 'Email',        sample: 'alice@college.edu'},
    address:    { label: 'Address',      sample: '12 Green St'     },
    department: { label: 'Department',   sample: 'Computer Science'},
    student_id: { label: 'Student ID',   sample: 'CS2022001'       },
};

// ─── Update Preview Card ──────────────────────────
function updatePreview() {
    const container = document.getElementById('preview-fields');
    if (!container) return;

    container.innerHTML = '';

    const toggles = document.querySelectorAll('.toggle-input');
    let hasVisible = false;

    toggles.forEach(toggle => {
        if (toggle.checked) {
            hasVisible = true;
            const field = toggle.dataset.field;
            const meta  = FIELD_META[field] || { label: field, sample: '—' };

            const div = document.createElement('div');
            div.className = 'preview-field-item';
            div.innerHTML = `
                <span class="pf-label">${meta.label}</span>
                <span class="pf-value">${meta.sample}</span>
            `;
            container.appendChild(div);
        }
    });

    if (!hasVisible) {
        container.innerHTML = '<p style="font-size:0.78rem; color:var(--text-muted); text-align:center; padding:8px;">No fields are visible.</p>';
    }
}

// ─── Called on Each Toggle Change ─────────────────
function onFieldToggle(checkbox) {
    updatePreview();

    // Highlight the row based on toggle state
    const row = document.getElementById(`row-${checkbox.dataset.field}`);
    if (row) {
        row.style.opacity = checkbox.checked ? '1' : '0.5';
    }
}

// ─── Save Settings ────────────────────────────────
async function saveSettings() {
    const toggles  = document.querySelectorAll('.toggle-input');
    const settings = {};

    toggles.forEach(toggle => {
        settings[toggle.dataset.field] = toggle.checked;
    });

    const btn     = document.getElementById('btn-save-settings');
    const msgDiv  = document.getElementById('save-msg');

    // Loading state
    btn.disabled    = true;
    btn.textContent = 'Saving…';

    try {
        const res  = await fetch('/api/settings', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(settings)
        });

        const data = await res.json();

        if (res.ok && data.success) {
            showMsg('✅ Settings saved successfully!', 'success');
        } else {
            showMsg('❌ Failed to save: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (err) {
        showMsg('❌ Network error. Please try again.', 'error');
    }

    // Restore button
    btn.disabled = false;
    btn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
            <polyline points="17 21 17 13 7 13 7 21"/>
            <polyline points="7 3 7 8 15 8"/>
        </svg>
        Save Settings
    `;
}

// ─── Reset to Defaults ────────────────────────────
function resetToDefaults() {
    if (!confirm('Reset all fields to visible (ON)? This will save the changes.')) return;

    const toggles = document.querySelectorAll('.toggle-input');
    toggles.forEach(toggle => {
        toggle.checked = true;
        const row = document.getElementById(`row-${toggle.dataset.field}`);
        if (row) row.style.opacity = '1';
    });

    updatePreview();
    saveSettings();
}

// ─── Show Save Message ────────────────────────────
function showMsg(text, type) {
    const el  = document.getElementById('save-msg');
    el.textContent = text;
    el.className   = `save-message ${type}`;
    el.style.display = '';

    // Auto-hide after 4 seconds
    setTimeout(() => { el.style.display = 'none'; }, 4000);
}

// ─── Init ─────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Initial preview render based on server-rendered toggle states
    updatePreview();

    // Apply opacity to OFF rows on load
    document.querySelectorAll('.toggle-input').forEach(toggle => {
        if (!toggle.checked) {
            const row = document.getElementById(`row-${toggle.dataset.field}`);
            if (row) row.style.opacity = '0.5';
        }
    });
});
