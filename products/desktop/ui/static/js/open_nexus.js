function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;');
}

async function requestJson(url, options = {}) {
    const response = await fetch(url, {
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
}

// ── Monitoring: estado de servicios ─────────────────────────────────────────

async function loadServiceStatus() {
    const list = document.getElementById('serviceStatusList');
    if (!list) return;
    try {
        const data = await requestJson('/api/nexus/monitoring/collectors');
        const collectors = data.collectors || [];
        if (!collectors.length) {
            list.innerHTML = '<div class="status-skeleton">Sin recolectores configurados</div>';
            return;
        }
        list.innerHTML = collectors.map((c) => `
            <div class="service-row">
                <span class="service-name">${escapeHtml(c.name)}</span>
                <span class="svc-badge svc-${escapeHtml(c.status || 'down')}">${escapeHtml(c.status || 'down')}</span>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = `<div class="status-skeleton">Error cargando estado</div>`;
    }
}

// ── Monitoring: ultimas alarmas ──────────────────────────────────────────────

async function loadAlarms() {
    const list = document.getElementById('alarmsList');
    if (!list) return;
    try {
        const data = await requestJson('/api/nexus/incidents');
        const incidents = (data.incidents || []).slice(0, 5);
        if (!incidents.length) {
            list.innerHTML = '<div class="empty-state-sm">Sin alarmas recientes</div>';
            return;
        }
        list.innerHTML = incidents.map((inc) => {
            const sev = (inc.severity || 'info').toLowerCase();
            const title = inc.title || inc.incident_id || 'Alarma';
            const source = inc.source || '';
            const status = inc.status || '';
            const meta = [source, status].filter(Boolean).join(' · ');
            return `
                <div class="alarm-card alarm-${escapeHtml(sev)}">
                    <div class="alarm-title">${escapeHtml(title)}</div>
                    ${meta ? `<div class="alarm-meta">${escapeHtml(meta)}</div>` : ''}
                </div>
            `;
        }).join('');
    } catch (e) {
        list.innerHTML = '<div class="empty-state-sm">Sin datos de alarmas</div>';
    }
}

// ── Mini chat ─────────────────────────────────────────────────────────────────

function appendMessage(role, text) {
    const history = document.getElementById('miniChatHistory');
    if (!history) return;
    const cls = role === 'user' ? 'chat-msg-user'
              : role === 'thinking' ? 'chat-msg-thinking'
              : 'chat-msg-assistant';
    const div = document.createElement('div');
    div.className = `chat-msg ${cls}`;
    div.textContent = text;
    history.appendChild(div);
    history.scrollTop = history.scrollHeight;
    return div;
}

async function sendChat(event) {
    event.preventDefault();
    const input = document.getElementById('miniChatInput');
    const badge = document.getElementById('chatStatusBadge');
    const message = input?.value.trim();
    if (!message) return;

    input.value = '';
    appendMessage('user', message);

    if (badge) { badge.textContent = 'procesando'; badge.className = 'chat-badge thinking'; }
    const thinkingEl = appendMessage('thinking', 'Nexus procesando...');

    try {
        const data = await requestJson('/api/nexus/chat', {
            method: 'POST',
            body: JSON.stringify({ message, user_id: 'shell-user', mode: 'general' }),
        });
        thinkingEl?.remove();
        appendMessage('assistant', data.response || 'Sin respuesta');
    } catch (e) {
        thinkingEl?.remove();
        appendMessage('assistant', `Error: ${e.message}`);
    } finally {
        if (badge) { badge.textContent = 'listo'; badge.className = 'chat-badge'; }
    }
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('miniChatForm');
    if (form) form.addEventListener('submit', sendChat);

    // Ctrl+Enter para enviar
    const input = document.getElementById('miniChatInput');
    if (input) {
        input.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === 'Enter') {
                e.preventDefault();
                form?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
            }
        });
    }

    loadServiceStatus();
    loadAlarms();
});
