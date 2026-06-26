function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

let autoRefreshTimer = null;

async function requestJson(url, options = {}) {
    const response = await fetch(url, {
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options,
    });
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || `HTTP ${response.status}`);
    }
    return data;
}

function statusClass(value) {
    if (value === 'up') return 'up';
    if (value === 'degraded') return 'degraded';
    return 'down';
}

function renderFeed(targetId, items, mapper, emptyMessage) {
    const node = document.getElementById(targetId);
    if (!node) return;
    if (!items.length) {
        node.innerHTML = `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
        return;
    }
    node.innerHTML = items.map(mapper).join('');
}

function renderCollectorStatus(payload) {
    const node = document.getElementById('collectorStatusList');
    const healthBadge = document.getElementById('healthBadge');
    const collectorOverall = document.getElementById('collectorOverall');
    if (!node) return;

    const collectors = payload.collectors || [];
    if (!collectors.length) {
        node.innerHTML = '<div class="status-bullet loading">Sin recolectores configurados</div>';
    } else {
        node.innerHTML = collectors.map((collector) => `
            <div class="status-bullet ${statusClass(collector.status)}">
                ${escapeHtml(collector.name)} · ${escapeHtml(collector.status)}
            </div>
        `).join('');
    }

    if (healthBadge) {
        healthBadge.textContent = payload.overall === 'up' ? 'Recolectores arriba' : 'Recolectores degradados';
    }

    if (collectorOverall) {
        collectorOverall.textContent = payload.overall === 'up' ? 'ok' : 'degradado';
        collectorOverall.classList.remove('up', 'down', 'degraded');
        collectorOverall.classList.add(payload.overall === 'up' ? 'up' : 'degraded');
    }
}

function renderChatMessage(role, body) {
    const node = document.getElementById('chatTimeline');
    if (!node) return;
    const roleClass = role === 'Usuario' ? 'message-user' : role === 'Nexus' ? 'message-assistant' : 'message-system';
    node.insertAdjacentHTML('beforeend', `
        <article class="message-card ${roleClass}">
            <p class="message-role">${escapeHtml(role)}</p>
            <p class="message-body">${escapeHtml(body)}</p>
        </article>
    `);
    node.scrollTop = node.scrollHeight;
}

function formatAuditDescription(entry, fallback) {
    const details = entry.details || {};
    return details.message_preview
        || details.title
        || details.incident_id
        || details.alert_name
        || fallback;
}

async function loadCollectors() {
    try {
        const data = await requestJson('/api/nexus/monitoring/collectors');
        renderCollectorStatus(data);
    } catch (error) {
        renderCollectorStatus({
            overall: 'degraded',
            collectors: [{ name: 'Recolectores', status: 'down', reason: error.message }],
        });
    }
}

function updateLastSync() {
    const label = document.getElementById('lastSyncLabel');
    if (!label) return;
    label.textContent = new Date().toLocaleTimeString('es-ES', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
}

function splitAudit(entries) {
    const history = [];
    const activity = [];

    for (const entry of entries) {
        const actor = entry.actor || '';
        const isUserAction = entry.flow === 'chat'
            || actor.startsWith('demo')
            || actor.startsWith('operator')
            || entry.action === 'update_incident'
            || entry.action === 'execute_incident_action';

        if (isUserAction) {
            history.push(entry);
        } else {
            activity.push(entry);
        }
    }

    return { history, activity };
}

async function loadAuditFeeds() {
    try {
        const data = await requestJson('/api/nexus/audit');
        const { history, activity } = splitAudit(data.entries || []);

        renderFeed(
            'historyFeed',
            history,
            (entry) => `
                <article class="feed-card">
                    <h3>${escapeHtml(entry.action)}</h3>
                    <p>${escapeHtml(formatAuditDescription(entry, 'Accion operativa registrada por el usuario'))}</p>
                    <div class="feed-meta">
                        <span class="pill">${escapeHtml(entry.actor || 'usuario')}</span>
                        <span class="pill">${escapeHtml(entry.status || 'accepted')}</span>
                    </div>
                </article>
            `,
            'Todavia no hay conversaciones ni acciones manuales registradas.'
        );

        renderFeed(
            'activityFeed',
            activity,
            (entry) => `
                <article class="feed-card">
                    <h3>${escapeHtml(entry.action)}</h3>
                    <p>${escapeHtml(formatAuditDescription(entry, 'Evento automatico procesado por Nexus'))}</p>
                    <div class="feed-meta">
                        <span class="pill">${escapeHtml(entry.flow || 'monitoring')}</span>
                        <span class="pill">${escapeHtml(entry.status || 'accepted')}</span>
                        <span class="pill">${escapeHtml(entry.actor || 'nexus')}</span>
                    </div>
                </article>
            `,
            'Todavia no hay alarmas procesadas ni acciones automaticas.'
        );
    } catch (error) {
        renderFeed('historyFeed', [], () => '', `No se pudo cargar el historial: ${error.message}`);
        renderFeed('activityFeed', [], () => '', `No se pudo cargar la actividad: ${error.message}`);
    }
}

async function loadIncidentActivity() {
    try {
        const data = await requestJson('/api/nexus/incidents');
        const incidents = (data.incidents || []).filter((incident) => {
            const source = incident.source || '';
            return source.includes('alertmanager') || source.includes('monitoring');
        });

        const node = document.getElementById('activityFeed');
        if (!node || !incidents.length) return;

        const existing = node.innerHTML;
        const incidentCards = incidents.map((incident) => `
            <article class="feed-card">
                <h3>${escapeHtml(incident.title || incident.incident_id)}</h3>
                <p>${escapeHtml(incident.runbook?.summary || 'Incidente generado desde una alarma procesada')}</p>
                <div class="feed-meta">
                    <span class="pill">${escapeHtml(incident.severity || 'warning')}</span>
                    <span class="pill">${escapeHtml(incident.status || 'open')}</span>
                    <span class="pill">${escapeHtml(incident.source || 'monitoring')}</span>
                </div>
            </article>
        `).join('');

        if (existing.includes('empty-state')) {
            node.innerHTML = incidentCards;
        } else {
            node.innerHTML = incidentCards + existing;
        }
    } catch (error) {
        console.error('No se pudo enriquecer la actividad con incidentes', error);
    }
}

async function sendChat(event) {
    event.preventDefault();
    const messageInput = document.getElementById('chatMessage');
    const modeInput = document.getElementById('chatMode');
    const message = messageInput?.value.trim();
    if (!message) return;

    renderChatMessage('Usuario', message);
    messageInput.value = '';

    try {
        const response = await requestJson('/api/nexus/chat', {
            method: 'POST',
            body: JSON.stringify({
                message,
                user_id: 'demo-user',
                mode: modeInput?.value || 'general',
            }),
        });
        renderChatMessage('Nexus', response.response || 'Solicitud aceptada');
        await loadAuditFeeds();
    } catch (error) {
        renderChatMessage('Sistema', `Error: ${error.message}`);
    }
}

async function refreshAllData() {
    await loadCollectors();
    await loadAuditFeeds();
    await loadIncidentActivity();
    updateLastSync();
}

document.addEventListener('DOMContentLoaded', async () => {
    document.getElementById('chatForm')?.addEventListener('submit', sendChat);
    document.getElementById('manualRefreshBtn')?.addEventListener('click', refreshAllData);
    document.querySelectorAll('.tab-chip').forEach((button) => {
        button.addEventListener('click', () => {
            document.querySelectorAll('.tab-chip').forEach((chip) => chip.classList.remove('active'));
            button.classList.add('active');
            const target = button.dataset.feedTab;
            const activityFeed = document.getElementById('activityFeed');
            const historyFeed = document.getElementById('historyFeed');
            if (!activityFeed || !historyFeed) return;
            activityFeed.classList.toggle('hidden-feed', target !== 'activity');
            historyFeed.classList.toggle('hidden-feed', target !== 'history');
        });
    });
    document.getElementById('autoRefreshSelect')?.addEventListener('change', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLSelectElement)) return;
        if (autoRefreshTimer) {
            window.clearInterval(autoRefreshTimer);
            autoRefreshTimer = null;
        }
        if (target.value !== 'off') {
            autoRefreshTimer = window.setInterval(refreshAllData, Number(target.value));
        }
    });
    document.querySelectorAll('.prompt-chip').forEach((button) => {
        button.addEventListener('click', () => {
            const textarea = document.getElementById('chatMessage');
            if (!textarea) return;
            textarea.value = button.dataset.prompt || '';
            textarea.focus();
        });
    });

    await refreshAllData();
    autoRefreshTimer = window.setInterval(refreshAllData, 60000);
});
