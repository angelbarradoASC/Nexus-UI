/* nexus_agents.js — gestor de agentes */

const API = '/api/nexus';

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

document.addEventListener('DOMContentLoaded', () => {
    loadCatalog();
    loadPending();
    loadActivity();
    setInterval(loadPending, 15000);
});

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

// ── Catálogo de agentes ──────────────────────────────────────────────────
// Exactamente 5 columnas de agentes reales — PEPO, Campaña, Sales, Operator,
// Shell — ni una mas (Supervisor es enrutamiento interno, no una columna;
// sus skills siguen visibles en la sub-pestaña "Skills"). Cuando exista el
// agente de coding se añade aqui y aparece solo — el grid ya es auto-fill.
const ALLOWED_AGENT_IDS = ['pepo', 'campaign', 'sales', 'operator', 'shell'];

const PERMISSION_LABELS = { 0: 'OBSERVE', 1: 'ASSIST', 2: 'OPERATE', 3: 'ADMIN' };

let _catalogAgents = [];
let _catalogOverrides = {};
let _catalogView = 'agents';

async function loadCatalog() {
    try {
        const [catalog, settings] = await Promise.all([
            requestJson(`${API}/agents/catalog?surface=desktop`),
            requestJson(`${API}/agents/settings`).catch(() => ({ settings: {} })),
        ]);
        _catalogAgents = catalog.agents || [];
        _catalogOverrides = settings.settings || {};
        renderAgentsView();
        renderSkillsView();
    } catch (err) {
        document.getElementById('agentCatalog').innerHTML = `<div class="ag-empty">Error cargando el catálogo: ${escapeHtml(err.message)}</div>`;
    }
}

function switchCatalogView(view) {
    _catalogView = view;
    document.querySelectorAll('.ag-tab').forEach(btn => btn.classList.toggle('is-active', btn.dataset.view === view));
    document.getElementById('agentCatalog').style.display = view === 'agents' ? '' : 'none';
    document.getElementById('skillsCatalog').style.display = view === 'skills' ? '' : 'none';
}

function renderAgentsView() {
    const grid = document.getElementById('agentCatalog');
    const countBadge = document.getElementById('catalogCount');

    const agents = ALLOWED_AGENT_IDS
        .map(id => _catalogAgents.find(a => a.agent_id === id))
        .filter(Boolean);

    if (countBadge) countBadge.textContent = String(agents.length);

    if (!agents.length) {
        grid.innerHTML = '<div class="ag-empty">Sin agentes registrados</div>';
        return;
    }

    grid.innerHTML = agents.map(agent => {
        const capabilities = (agent.capabilities || []).map(c =>
            `<span class="ag-pill" title="${escapeHtml(c.description || '')}">${escapeHtml(c.name)}</span>`
        ).join('') || '<div class="ag-empty" style="padding:0.4rem 0;">Sin capacidades declaradas</div>';

        return `
            <article class="ag-card">
                <div class="ag-card-head">
                    <div>
                        <div class="ag-card-name">${escapeHtml(agent.name)}</div>
                        <div class="ag-card-role">${escapeHtml(agent.role)} · ${escapeHtml(agent.agent_id)}</div>
                    </div>
                </div>
                <div class="ag-card-desc">${escapeHtml(agent.description || '')}</div>
                <div class="ag-card-scroll">
                    <div class="ag-pill-row">${capabilities}</div>
                </div>
            </article>`;
    }).join('');
}

function renderSkillsView() {
    const list = document.getElementById('skillsCatalog');
    const overrides = _catalogOverrides;

    const rows = _catalogAgents.flatMap(agent =>
        (agent.skill_ids || []).map(skillId => ({ skillId, agent }))
    );

    if (!rows.length) {
        list.innerHTML = '<div class="ag-empty">Sin skills registrados</div>';
        return;
    }

    list.innerHTML = rows.map(({ skillId, agent }) => {
        const override = overrides[skillId] || {};
        const enabled = override.enabled !== false;
        const permission = override.permission_level ?? '';
        const options = Object.entries(PERMISSION_LABELS).map(([value, label]) =>
            `<option value="${value}" ${String(permission) === value ? 'selected' : ''}>${label}</option>`
        ).join('');
        return `
            <div class="ag-skill-row" data-skill-id="${escapeHtml(skillId)}">
                <div>
                    <span class="ag-skill-id">${escapeHtml(skillId)}</span>
                    <div class="ag-pending-meta">${escapeHtml(agent.name)}</div>
                </div>
                <div class="ag-skill-controls">
                    <select title="Permiso" onchange="changeSkillPermission('${escapeHtml(skillId)}', this.value)">
                        <option value="">default</option>
                        ${options}
                    </select>
                    <label class="ag-toggle" title="Activar/desactivar este skill">
                        <input type="checkbox" ${enabled ? 'checked' : ''} onchange="toggleSkillEnabled('${escapeHtml(skillId)}', this.checked)">
                        <span class="ag-toggle-track"></span>
                    </label>
                </div>
            </div>`;
    }).join('');
}

async function toggleSkillEnabled(skillId, enabled) {
    try {
        await requestJson(`${API}/agents/settings/${encodeURIComponent(skillId)}`, {
            method: 'PUT',
            body: JSON.stringify({ enabled }),
        });
        toast(enabled ? `${skillId} activado` : `${skillId} desactivado`);
    } catch (err) {
        toast(`Error: ${err.message}`, true);
    }
}

async function changeSkillPermission(skillId, value) {
    if (value === '') return;
    try {
        await requestJson(`${API}/agents/settings/${encodeURIComponent(skillId)}`, {
            method: 'PUT',
            body: JSON.stringify({ permission_level: parseInt(value, 10) }),
        });
        toast(`Permiso de ${skillId} actualizado a ${PERMISSION_LABELS[value]}`);
    } catch (err) {
        toast(`Error: ${err.message}`, true);
    }
}

// ── Acciones pendientes ──────────────────────────────────────────────────

async function loadPending() {
    try {
        const data = await requestJson(`${API}/agents/pending`);
        renderPending(data.pending || []);
    } catch (err) {
        // silencioso — el polling no debe llenar de toasts
    }
}

function renderPending(items) {
    const list = document.getElementById('pendingList');
    const countBadge = document.getElementById('pendingCount');
    if (countBadge) countBadge.textContent = String(items.length);

    if (!items.length) {
        list.innerHTML = '<div class="ag-empty">Sin acciones pendientes de confirmar</div>';
        return;
    }

    list.innerHTML = items.map(item => `
        <div class="ag-pending-item">
            <div>
                <div class="ag-pending-summary">${escapeHtml(item.summary)}</div>
                <div class="ag-pending-meta">${escapeHtml(item.agent_id)} · ${escapeHtml(item.kind)}</div>
            </div>
            <div class="ag-pending-actions">
                <button class="ag-btn ag-btn--primary" type="button" onclick="confirmPending('${escapeHtml(item.context_id)}')">Confirmar</button>
                <button class="ag-btn ag-btn--danger" type="button" onclick="cancelPending('${escapeHtml(item.context_id)}')">Cancelar</button>
            </div>
        </div>`).join('');
}

async function confirmPending(contextId) {
    try {
        const result = await requestJson(`${API}/agents/pending/${encodeURIComponent(contextId)}/confirm`, { method: 'POST', body: '{}' });
        toast('Acción confirmada');
        loadPending();
        loadActivity();
        console.log('Resultado:', result);
    } catch (err) {
        toast(`Error: ${err.message}`, true);
    }
}

async function cancelPending(contextId) {
    try {
        await requestJson(`${API}/agents/pending/${encodeURIComponent(contextId)}/cancel`, { method: 'POST' });
        toast('Acción cancelada');
        loadPending();
    } catch (err) {
        toast(`Error: ${err.message}`, true);
    }
}

// ── Actividad reciente ───────────────────────────────────────────────────

async function loadActivity() {
    try {
        const data = await requestJson(`${API}/audit`);
        renderActivity(data.entries || []);
    } catch (err) {
        document.getElementById('activityList').innerHTML = `<div class="ag-empty">Error: ${escapeHtml(err.message)}</div>`;
    }
}

function renderActivity(entries) {
    const list = document.getElementById('activityList');
    if (!entries.length) {
        list.innerHTML = '<div class="ag-empty">Sin actividad todavía</div>';
        return;
    }
    const sorted = [...entries].reverse();
    list.innerHTML = sorted.slice(0, 40).map(entry => {
        const time = entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString('es-ES') : '';
        const skillId = entry.details && entry.details.skill_id ? ` [${entry.details.skill_id}]` : '';
        const statusClass = `ag-activity-status-${entry.status === 'accepted' ? 'accepted' : entry.status === 'degraded' ? 'degraded' : 'error'}`;
        return `<div class="ag-activity-item">
            <span class="ag-activity-time">${escapeHtml(time)}</span>
            <span class="${statusClass}">${escapeHtml(entry.action)}${escapeHtml(skillId)}</span>
        </div>`;
    }).join('');
}

// ── Toast ─────────────────────────────────────────────────────────────────

let _toastTimer = null;
function toast(msg, isError = false) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.style.borderColor = isError ? 'rgba(178,75,59,0.4)' : 'rgba(18,60,55,0.15)';
    el.classList.add('ag-toast--visible');
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => el.classList.remove('ag-toast--visible'), 3500);
}
