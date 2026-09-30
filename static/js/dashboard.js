/*
General Ledger v0.1.0
File: static/js/dashboard.js
Description: Shared dashboard helpers - API envelope, status messages, formatting, modals,
             tabs, wizards, collapsibles. Page-specific code stays inline in each template.
*/

// ---------- API ----------
// Every endpoint returns { success: true, ... } or { success: false, error }.
// Throws on success:false, on non-2xx, and on a non-JSON body (e.g. a proxy's HTML 502).
async function api(url, options = {}) {
    const opts = { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } };
    if (opts.body !== undefined && typeof opts.body !== 'string') {
        opts.body = JSON.stringify(opts.body);
    }
    const resp = await fetch(url, opts);
    const text = await resp.text();
    let data;
    try {
        data = JSON.parse(text);
    } catch (e) {
        throw new Error(`HTTP ${resp.status}: ${text.slice(0, 200)}`);
    }
    if (!resp.ok || !data.success) {
        throw new Error(data.error || `HTTP ${resp.status}`);
    }
    return data;
}

// ---------- Status messages (under the header) ----------
const STATUS_DURATIONS = { success: 3000, error: 5000, warning: 4000, info: 4000 };
let statusTimer = null;

function showStatus(message, type = 'info') {
    const el = document.getElementById('statusMessages');
    el.innerHTML = `<div class="alert alert-${type}">${escapeHtml(message)}</div>`;
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => { el.innerHTML = ''; }, STATUS_DURATIONS[type]);
}
const showSuccess = (m) => showStatus(m, 'success');
const showError = (m) => showStatus(m, 'error');
const showWarning = (m) => showStatus(m, 'warning');
const showInfo = (m) => showStatus(m, 'info');

// ---------- Busy buttons ----------
// Usage: const done = setBusy(btn, 'Refreshing...'); try { ... } finally { done(); }
function setBusy(button, busyLabel) {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = busyLabel;
    return () => { button.disabled = false; button.textContent = original; };
}

// ---------- Formatting (formats values; never invents them) ----------
function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// null = the server deliberately has no value -> em dash.
// undefined = the field is missing -> "$NaN", visibly broken (no-fallbacks rule).
function formatMoney(value, decimals = 2) {
    if (value === null) return '—';
    const n = Number(value);
    const abs = Math.abs(n).toLocaleString(undefined, {
        minimumFractionDigits: decimals, maximumFractionDigits: decimals,
    });
    return (n < 0 ? '-$' : '$') + abs;
}

function formatSignedMoney(value, decimals = 2) {
    if (value === null) return '—';
    return (Number(value) > 0 ? '+' : '') + formatMoney(value, decimals);
}

function formatPercent(value, decimals = 1) {
    if (value === null) return '—';
    return Number(value).toFixed(decimals) + '%';
}

function signClass(value) {
    if (value === null) return 'neutral';
    const n = Number(value);
    return n > 0 ? 'positive' : (n < 0 ? 'negative' : 'neutral');
}

// YYYY-MM-DD from LOCAL date parts. toISOString() is UTC and rolls the day over
// for anyone west of UTC in the evening.
function localDateISO(date = new Date()) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

// Standard "state row" for a table body: Loading... / empty / error.
function tableMessage(tbody, colspan, message, isError = false) {
    tbody.innerHTML = `<tr><td colspan="${colspan}" class="empty${isError ? ' error-text' : ''}">${escapeHtml(message)}</td></tr>`;
}

// ---------- Modals ----------
function openModal(id) { document.getElementById(id).classList.add('active'); }
function closeModal(id) { document.getElementById(id).classList.remove('active'); }

document.addEventListener('click', (e) => {
    if (e.target.classList && e.target.classList.contains('modal-overlay')) {
        e.target.classList.remove('active');
    }
});
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.active').forEach((m) => m.classList.remove('active'));
    }
});

// ---------- Tabs ----------
// Markup: <div class="tabs"><button class="tab" data-tab="a">..</button></div>
//         <div class="tab-panel" data-tab="a">..</div>
function switchTab(name) {
    document.querySelectorAll('.tab[data-tab]').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
    document.querySelectorAll('.tab-panel[data-tab]').forEach((p) => { p.hidden = p.dataset.tab !== name; });
}

// ---------- Wizard (within one modal/container) ----------
function wizardGo(step, root = document) {
    root.querySelectorAll('.wizard-content').forEach((c) => c.classList.toggle('active', Number(c.dataset.step) === step));
    root.querySelectorAll('.wizard-step').forEach((s) => {
        const n = Number(s.dataset.step);
        s.classList.toggle('active', n === step);
        s.classList.toggle('completed', n < step);
    });
}

// ---------- Collapsible ----------
// Markup: <h2 class="collapsible-header" onclick="toggleCollapsible(this)">..</h2>
//         <div class="collapsible-content">..</div>
function toggleCollapsible(header) {
    const content = header.nextElementSibling;
    const collapsing = !content.classList.contains('collapsed');
    header.classList.toggle('collapsed', collapsing);
    // Start from a real height so max-height has something to animate from/to
    content.style.maxHeight = content.scrollHeight + 'px';
    requestAnimationFrame(() => {
        content.classList.toggle('collapsed', collapsing);
        if (!collapsing) {
            // Once open, drop the fixed height so later content changes are not clipped
            content.addEventListener('transitionend', () => { content.style.maxHeight = ''; }, { once: true });
        }
    });
}

// EOF - dashboard.js
