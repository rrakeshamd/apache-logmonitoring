'use strict';

// ── State ────────────────────────────────────────────────────────────────────
let eventSource    = null;
let currentLog     = 'access';
let currentServer  = '__local__';  // '__local__' = local logs; otherwise remote server name
let llmEnabled     = false;
let totalLines     = 0;
let visibleLines   = 0;
let llmBuffer      = [];   // rolling window of raw strings for LLM analysis
let serverPollTimer = null;
let streamMode         = 'single';   // 'single' | 'all'
let domainColorMap     = {};         // domain -> CSS color string
let activeDomainFilter = null;       // null = show all; string = filter to that domain

const MAX_LINES      = 2000;
const LLM_BUFFER_MAX = 100;
const DOMAIN_COLORS  = ['#61afef', '#98c379', '#e5c07b', '#c678dd', '#56b6c2', '#e06c75', '#d19a66', '#abb2bf'];

const filters = {
    levels:      new Set(['info', 'warn', 'error']),
    statusGroup: 'all',
    keyword:     '',
};

// ── DOM refs ─────────────────────────────────────────────────────────────────
const logOutput    = () => document.getElementById('log-output');
const statusEl     = () => document.getElementById('connection-status');
const statsEl      = () => document.getElementById('stats-bar');
const keywordInput = () => document.getElementById('keyword-input');
const analyzeBtn   = () => document.getElementById('btn-analyze');

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    setupControls();

    // Fetch server config and log info in parallel
    try {
        const [cfgResp, logsResp] = await Promise.all([
            fetch('/api/config'),
            fetch('/api/logs'),
        ]);
        const cfg  = await cfgResp.json();
        const logs = await logsResp.json();
        llmEnabled = cfg.llm_enabled;
        buildDomainColorMap(logs);
        populateLogSelector(cfg.log_names);
        connectSSE(currentLog);
    } catch (e) {
        console.error('Failed to fetch /api/config', e);
    }

    // Poll for newly-connected remote agents every 10s
    await refreshServers();
    serverPollTimer = setInterval(refreshServers, 10000);
});

// ── Server selector ──────────────────────────────────────────────────────────
async function refreshServers() {
    try {
        const resp    = await fetch('/api/servers');
        const data    = await resp.json();
        populateServerSelector(data.servers || []);
    } catch (e) {
        console.error('Failed to fetch /api/servers', e);
    }
}

function populateServerSelector(serverNames) {
    const sel  = document.getElementById('server-selector');
    const prev = sel.value;

    // Preserve "Local" option; add/update remote servers
    const existing = new Set(
        Array.from(sel.options).map(o => o.value)
    );

    serverNames.forEach(name => {
        if (!existing.has(name)) {
            const opt = document.createElement('option');
            opt.value = name;
            opt.text  = name;
            sel.appendChild(opt);
        }
    });

    // Restore previous selection if still present
    if (prev && Array.from(sel.options).some(o => o.value === prev)) {
        sel.value = prev;
    }
}

// ── Log selector ─────────────────────────────────────────────────────────────
function populateLogSelector(names) {
    const sel = document.getElementById('log-selector');
    const prev = sel.value;  // preserve current selection if possible
    sel.innerHTML = '';

    if (!names || names.length === 0) {
        const opt = document.createElement('option');
        opt.disabled = true;
        opt.text = 'No log files found';
        sel.appendChild(opt);
        return;
    }

    names.forEach(name => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.text  = name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) + ' log';
        sel.appendChild(opt);
    });

    // Restore previous selection, or default to first available
    if (names.includes(prev)) {
        sel.value  = prev;
        currentLog = prev;
    } else {
        sel.value  = names[0];
        currentLog = names[0];
    }
}

function setupLogSelectorChange() {
    const sel = document.getElementById('log-selector');
    sel.addEventListener('change', () => {
        currentLog = sel.value;
        clearOutput();
        connectSSE(currentLog);
    });
}

// ── Refresh log directory ─────────────────────────────────────────────────────
async function refreshLogs() {
    const btn = document.getElementById('btn-refresh');
    btn.disabled = true;
    try {
        const resp = await fetch('/api/refresh', { method: 'POST' });
        const data = await resp.json();
        populateLogSelector(data.log_names);
    } catch (e) {
        console.error('Refresh failed', e);
    } finally {
        btn.disabled = false;
    }
}

// ── Domain color map ──────────────────────────────────────────────────────────
function buildDomainColorMap(logInfoList) {
    const domains = [...new Set(logInfoList.map(l => l.domain).filter(Boolean))].sort();
    domainColorMap = {};
    domains.forEach((d, i) => { domainColorMap[d] = DOMAIN_COLORS[i % DOMAIN_COLORS.length]; });
}

// ── Domain filter bar ─────────────────────────────────────────────────────────
function updateDomainFilterButtons() {
    const bar = document.getElementById('domain-filter-bar');
    bar.innerHTML = '';

    const allBtn = makeFilterPill('All Domains', null, '#abb2bf');
    bar.appendChild(allBtn);

    Object.entries(domainColorMap).sort().forEach(([domain, color]) => {
        bar.appendChild(makeFilterPill(domain, domain, color));
    });
}

function makeFilterPill(label, domain, color) {
    const btn = document.createElement('button');
    btn.className = 'domain-pill';
    btn.textContent = label;
    btn.style.borderColor = color;
    btn.style.color = color;
    if (activeDomainFilter === domain) btn.classList.add('active');
    btn.addEventListener('click', () => {
        activeDomainFilter = domain;
        document.querySelectorAll('.domain-pill').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        applyAllFilters();
    });
    return btn;
}

// ── SSE connection ────────────────────────────────────────────────────────────
function connectSSE(logName) {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
    setStatus('connecting');

    let url;
    if (streamMode === 'all') {
        url = '/api/stream/all';
    } else if (currentServer === '__local__') {
        url = `/api/stream/${logName}`;
    } else {
        url = `/api/stream/${encodeURIComponent(currentServer)}/${logName}`;
    }

    eventSource = new EventSource(url);

    eventSource.onopen = () => setStatus('connected');

    eventSource.onerror = () => {
        setStatus('error');
        // EventSource reconnects automatically; update status when it does
    };

    eventSource.onmessage = (evt) => {
        let entry;
        try { entry = JSON.parse(evt.data); } catch { return; }

        // Maintain rolling LLM buffer
        llmBuffer.push(entry.raw);
        if (llmBuffer.length > LLM_BUFFER_MAX) llmBuffer.shift();

        appendLine(entry);
        enforceMaxLines();

        if (document.getElementById('auto-scroll').checked) {
            const out = logOutput();
            out.scrollTop = out.scrollHeight;
        }
    };
}

// ── Append a log line to the DOM ──────────────────────────────────────────────
function appendLine(entry) {
    const div = document.createElement('div');
    div.className      = `log-line log-${entry.level}`;
    div.dataset.level  = entry.level;
    div.dataset.status = entry.status != null ? String(entry.status) : '';
    div.dataset.raw    = entry.raw.toLowerCase();
    div.dataset.domain = entry.domain || '';

    if (streamMode === 'all' && entry.domain) {
        const color = domainColorMap[entry.domain] || '#abb2bf';
        const badge = document.createElement('span');
        badge.className = 'domain-badge';
        badge.style.color = color;
        badge.style.borderColor = color;
        badge.textContent = entry.domain;
        const text = document.createElement('span');
        if (filters.keyword) {
            text.innerHTML = highlightKeyword(escapeHtml(entry.raw), filters.keyword);
        } else {
            text.textContent = entry.raw;
        }
        div.appendChild(badge);
        div.appendChild(text);
    } else if (filters.keyword) {
        div.innerHTML = highlightKeyword(escapeHtml(entry.raw), filters.keyword);
    } else {
        div.textContent = entry.raw;
    }

    logOutput().appendChild(div);
    totalLines++;

    // Apply current filters immediately
    applyFilterToEl(div);
    updateStats();
}

// ── Keyword highlight ─────────────────────────────────────────────────────────
function escapeHtml(text) {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function highlightKeyword(html, kw) {
    if (!kw) return html;
    const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(`(${escaped})`, 'gi');
    return html.replace(re, '<mark>$1</mark>');
}

// ── Filter application ────────────────────────────────────────────────────────
function applyFilterToEl(el) {
    const levelOk  = filters.levels.has(el.dataset.level);
    const statusOk = matchesStatusFilter(el.dataset.status);
    const keyOk    = !filters.keyword || el.dataset.raw.includes(filters.keyword);
    const domainOk = !activeDomainFilter || el.dataset.domain === activeDomainFilter;
    el.style.display = (levelOk && statusOk && keyOk && domainOk) ? '' : 'none';
}

function applyAllFilters() {
    visibleLines = 0;
    document.querySelectorAll('#log-output .log-line').forEach(el => {
        applyFilterToEl(el);
        if (el.style.display !== 'none') visibleLines++;
    });

    // Re-render keyword highlights in all visible lines
    if (filters.keyword) {
        document.querySelectorAll('#log-output .log-line').forEach(el => {
            el.innerHTML = highlightKeyword(escapeHtml(el.dataset.raw || el.textContent), filters.keyword);
        });
    } else {
        document.querySelectorAll('#log-output .log-line').forEach(el => {
            if (el.querySelector('mark')) {
                el.textContent = el.dataset.raw || el.textContent;
            }
        });
    }

    updateStats();
}

function matchesStatusFilter(status) {
    if (filters.statusGroup === 'all') return true;
    if (!status) return false;
    const s = parseInt(status, 10);
    if (filters.statusGroup === '4xx') return s >= 400 && s < 500;
    if (filters.statusGroup === '5xx') return s >= 500;
    return true;
}

// ── DOM cap ───────────────────────────────────────────────────────────────────
function enforceMaxLines() {
    const out = logOutput();
    while (out.children.length > MAX_LINES) {
        out.removeChild(out.firstChild);
        totalLines = Math.max(0, totalLines - 1);
    }
}

// ── Controls setup ────────────────────────────────────────────────────────────
function setupControls() {
    // Server selector change
    document.getElementById('server-selector').addEventListener('change', async (e) => {
        currentServer = e.target.value;
        clearOutput();

        if (currentServer === '__local__') {
            // Restore local log names from /api/config
            try {
                const resp = await fetch('/api/config');
                const cfg  = await resp.json();
                populateLogSelector(cfg.log_names);
            } catch {}
        } else {
            // Fetch log names available on the remote server
            try {
                const resp = await fetch(`/api/servers/${encodeURIComponent(currentServer)}/logs`);
                const data = await resp.json();
                const names = data.log_names && data.log_names.length
                    ? data.log_names
                    : ['access', 'error'];   // fallback defaults
                populateLogSelector(names);
            } catch {
                populateLogSelector(['access', 'error']);
            }
        }
        connectSSE(currentLog);
    });

    // Log selector change
    setupLogSelectorChange();

    // Refresh button
    document.getElementById('btn-refresh').addEventListener('click', refreshLogs);

    // Level checkboxes
    document.querySelectorAll('.level-check').forEach(cb => {
        cb.addEventListener('change', () => {
            if (cb.checked) filters.levels.add(cb.value);
            else            filters.levels.delete(cb.value);
            applyAllFilters();
        });
    });

    // Status group radios
    document.querySelectorAll('.status-radio').forEach(r => {
        r.addEventListener('change', () => {
            if (r.checked) {
                filters.statusGroup = r.value;
                applyAllFilters();
            }
        });
    });

    // Keyword search (debounced)
    let debounceTimer = null;
    keywordInput().addEventListener('input', (e) => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            filters.keyword = e.target.value.toLowerCase().trim();
            applyAllFilters();
        }, 300);
    });

    // Clear button
    document.getElementById('btn-clear').addEventListener('click', clearOutput);

    // Stream All toggle
    document.getElementById('btn-stream-all').addEventListener('click', () => {
        streamMode = streamMode === 'all' ? 'single' : 'all';
        const btn = document.getElementById('btn-stream-all');
        btn.classList.toggle('active', streamMode === 'all');
        btn.textContent = streamMode === 'all' ? 'Viewing All Domains' : 'Stream All Domains';
        clearOutput();
        activeDomainFilter = null;
        if (streamMode === 'all') {
            updateDomainFilterButtons();
        } else {
            document.getElementById('domain-filter-bar').innerHTML = '';
        }
        connectSSE(currentLog);
    });

    // Analyze button — wired but disabled when LLM is off
    const btn = analyzeBtn();
    if (!llmEnabled) {
        btn.disabled = true;
        btn.title    = 'LLM integration is disabled. Set LLM_ENABLED=true in .env to enable.';
        btn.classList.add('btn-analyze-disabled');
    } else {
        btn.addEventListener('click', analyzeLogs);
    }
}

// ── Clear output ──────────────────────────────────────────────────────────────
function clearOutput() {
    logOutput().innerHTML = '';
    totalLines   = 0;
    visibleLines = 0;
    llmBuffer    = [];
    updateStats();
}

// ── Status display ────────────────────────────────────────────────────────────
function setStatus(state) {
    const el = statusEl();
    el.className = `status-${state}`;
    const labels = { connected: 'Connected', connecting: 'Connecting…', error: 'Disconnected' };
    el.innerHTML = `<span class="status-badge"></span>${labels[state] || state}`;
}

// ── Stats bar ─────────────────────────────────────────────────────────────────
function updateStats() {
    const vis = document.querySelectorAll('#log-output .log-line:not([style*="display: none"])').length;
    const tot = logOutput().children.length;
    statsEl().textContent = `Showing ${vis} of ${tot} lines (capped at ${MAX_LINES})`;
}

// ── LLM analysis ─────────────────────────────────────────────────────────────
async function analyzeLogs() {
    const btn = analyzeBtn();
    btn.disabled     = true;
    btn.textContent  = 'Analyzing…';

    try {
        const resp = await fetch('/api/analyze', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ lines: llmBuffer.slice(-20), log_type: currentLog }),
        });
        const data = await resp.json();
        const resultEl = document.getElementById('analysis-result');
        resultEl.textContent = resp.ok ? data.analysis : `Error: ${data.error}`;
        new bootstrap.Modal(document.getElementById('analysisModal')).show();
    } catch (e) {
        alert('Failed to reach /api/analyze: ' + e.message);
    } finally {
        btn.disabled    = false;
        btn.textContent = 'Analyze with AI';
    }
}
