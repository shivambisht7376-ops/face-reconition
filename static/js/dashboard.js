/**
 * dashboard.js
 * Fetches live stats from the /api/stats endpoint
 * and populates the three stat cards on the dashboard.
 */

// Animate a number from 0 up to the target value
function animateCount(el, target) {
    const duration = 700;
    const start    = performance.now();
    const from     = 0;

    function step(now) {
        const elapsed  = now - start;
        const progress = Math.min(elapsed / duration, 1);
        // Ease-out quad
        const eased = 1 - (1 - progress) * (1 - progress);
        el.textContent = Math.round(from + (target - from) * eased);
        if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}

// Fetch stats from Flask and update the DOM
async function loadStats() {
    try {
        const res  = await fetch('/api/stats');
        const data = await res.json();

        const totalEl      = document.getElementById('stat-total');
        const recognizedEl = document.getElementById('stat-recognized');
        const unknownEl    = document.getElementById('stat-unknown');

        animateCount(totalEl,      data.total_people      || 0);
        animateCount(recognizedEl, data.recognized_today  || 0);
        animateCount(unknownEl,    data.unknown_today      || 0);
    } catch (err) {
        console.error('Failed to load stats:', err);
        ['stat-total', 'stat-recognized', 'stat-unknown'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = '—';
        });
    }
}

// Load immediately on page ready
document.addEventListener('DOMContentLoaded', loadStats);
