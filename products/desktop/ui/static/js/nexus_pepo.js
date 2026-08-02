// nexus_pepo.js — PEPO chat + skills panel

let _pepoContextId = null;
let _pepoBusy = false;

function escHtml(v) {
    return String(v ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

async function apiJson(url, opts = {}) {
    const r = await fetch(url, {
        headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
        ...opts,
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
    return d;
}

// ── Chat ──────────────────────────────────────────────────────────────────────

function appendMsg(role, text, isThinking = false) {
    const log = document.getElementById('pepoChatLog');
    if (!log) return null;

    const wrap = document.createElement('div');
    wrap.className = `pepo-msg pepo-msg-${role}`;

    const roleLabel = role === 'user' ? 'Tú' : 'PEPO';

    if (isThinking) {
        wrap.innerHTML = `<p class="pepo-msg-role">${escHtml(roleLabel)}</p>
            <div class="pepo-thinking">
                <div class="pepo-thinking-dot"></div>
                <div class="pepo-thinking-dot"></div>
                <div class="pepo-thinking-dot"></div>
            </div>`;
    } else {
        wrap.innerHTML = `<p class="pepo-msg-role">${escHtml(roleLabel)}</p>
            <div class="pepo-bubble">${escHtml(text).replace(/\n/g, '<br>')}</div>`;
    }

    log.appendChild(wrap);
    log.scrollTop = log.scrollHeight;
    return wrap;
}

async function sendToChat(message) {
    if (_pepoBusy || !message.trim()) return;
    _pepoBusy = true;

    const sendBtn = document.getElementById('pepoChatSendBtn');
    if (sendBtn) sendBtn.disabled = true;

    const input = document.getElementById('pepoInput');

    appendMsg('user', message);
    const thinkEl = appendMsg('pepo', '', true);

    try {
        const data = await apiJson('/api/nexus/chat', {
            method: 'POST',
            body: JSON.stringify({
                message,
                user_id: 'pepo_user',
                mode: 'general',
                context_id: _pepoContextId || undefined,
            }),
        });
        thinkEl?.remove();
        appendMsg('pepo', data.response || '(sin respuesta)');
    } catch (err) {
        thinkEl?.remove();
        appendMsg('pepo', `Error al conectar: ${err.message}`);
    } finally {
        _pepoBusy = false;
        if (sendBtn) sendBtn.disabled = false;
        if (input) input.focus();
    }
}

// ── Skill result helpers ──────────────────────────────────────────────────────

function showSkillResult(resultId, text, ok, injectText = null) {
    const el = document.getElementById(resultId);
    if (!el) return;
    el.textContent = text;
    el.className = `skill-result is-visible ${ok ? 'skill-result-ok' : 'skill-result-err'}`;

    const inject = injectText || text;
    const btn = document.createElement('button');
    btn.className = 'send-to-pepo';
    btn.textContent = '→ Enviar a PEPO';
    btn.onclick = () => {
        const input = document.getElementById('pepoInput');
        if (!input) return;
        input.value = `PEPO, acabo de ejecutar una skill. Resultado:\n${inject}\n¿Qué me recomiendas?`;
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 140) + 'px';
        input.focus();
    };
    el.appendChild(document.createElement('br'));
    el.appendChild(btn);
}

function setBtnState(btnId, text, disabled) {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.textContent = text;
    btn.disabled = disabled;
}

// ── Skill: Prospecting ────────────────────────────────────────────────────────

async function runSkillProspecting() {
    const textarea = document.getElementById('skillProspectText');
    const text = (textarea?.value || '').trim();
    if (!text) { textarea?.focus(); return; }

    setBtnState('skillProspectBtn', 'Interpretando…', true);
    showSkillResult('skillProspectResult', 'Enviando a la IA…', true);

    try {
        const interp = await apiJson('/api/nexus/prospecting/interpret', {
            method: 'POST',
            body: JSON.stringify({ text }),
        });

        const brief = interp.brief || {};
        setBtnState('skillProspectBtn', 'Lanzando…', true);

        const runPayload = {
            ...brief,
            async_mode: true,
            dry_run: false,
        };

        const run = await apiJson('/api/nexus/prospecting/run', {
            method: 'POST',
            body: JSON.stringify(runPayload),
        });

        const runId = run.run_id || '—';
        const vertical = brief.vertical || '?';
        const city = brief.city || brief.province || '?';
        const count = brief.desired_count || '?';

        const summary = `Lanzado ✓\nVertical: ${vertical} | Ciudad: ${city} | Objetivo: ${count} leads\nRun ID: ${runId}`;
        showSkillResult('skillProspectResult', summary, true);
    } catch (err) {
        showSkillResult('skillProspectResult', `Error: ${err.message}`, false);
    } finally {
        setBtnState('skillProspectBtn', 'Ejecutar', false);
    }
}

// ── Skill: Push to CRM ────────────────────────────────────────────────────────

async function runSkillPushCrm() {
    setBtnState('skillPushCrmBtn', 'Enviando…', true);
    showSkillResult('skillPushCrmResult', 'Procesando push…', true);

    try {
        const data = await apiJson('/api/nexus/prospecting/push-valid-to-crm', { method: 'POST' });
        const pushed = data.pushed ?? data.count ?? data.total ?? '?';
        const skipped = data.skipped ?? '';
        let msg = `Push completado ✓\n${pushed} registros enviados al CRM.`;
        if (skipped) msg += `\n${skipped} omitidos (duplicados / score bajo).`;
        showSkillResult('skillPushCrmResult', msg, true);
    } catch (err) {
        showSkillResult('skillPushCrmResult', `Error: ${err.message}`, false);
    } finally {
        setBtnState('skillPushCrmBtn', 'Push a CRM', false);
    }
}

// ── Skill: Alertas ────────────────────────────────────────────────────────────

async function runSkillAlerts() {
    setBtnState('skillAlertsBtn', 'Consultando…', true);
    showSkillResult('skillAlertsResult', 'Cargando alertas…', true);

    try {
        const data = await apiJson('/api/nexus/monitoring/alerts');
        const alerts = data.alerts || [];
        if (!alerts.length) {
            showSkillResult('skillAlertsResult', 'Sin alertas activas ✓', true);
        } else {
            const lines = alerts.slice(0, 6)
                .map(a => `• [${a.severity || a.status || '?'}] ${a.name || a.alertname || a.title || '?'}`)
                .join('\n');
            const summary = `${alerts.length} alerta(s) activa(s):\n${lines}`;
            showSkillResult('skillAlertsResult', summary, alerts.length < 3);
        }
    } catch (err) {
        showSkillResult('skillAlertsResult', `Error: ${err.message}`, false);
    } finally {
        setBtnState('skillAlertsBtn', 'Ver alertas', false);
    }
}

// ── Skill: Incidentes ─────────────────────────────────────────────────────────

async function runSkillIncidents() {
    setBtnState('skillIncidentsBtn', 'Consultando…', true);
    showSkillResult('skillIncidentsResult', 'Cargando incidentes…', true);

    try {
        const data = await apiJson('/api/nexus/incidents?limit=10');
        const incidents = data.incidents || [];
        if (!incidents.length) {
            showSkillResult('skillIncidentsResult', 'Sin incidentes registrados ✓', true);
        } else {
            const open = incidents.filter(i => (i.status || '').toLowerCase() !== 'resolved');
            const lines = (open.length ? open : incidents).slice(0, 5)
                .map(i => `• [${i.severity || '?'}] ${i.title || i.name || '?'}`)
                .join('\n');
            const label = open.length ? `${open.length} abierto(s)` : `${incidents.length} total`;
            showSkillResult('skillIncidentsResult', `${label}:\n${lines}`, open.length === 0);
        }
    } catch (err) {
        showSkillResult('skillIncidentsResult', `Error: ${err.message}`, false);
    } finally {
        setBtnState('skillIncidentsBtn', 'Ver incidentes', false);
    }
}

// ── Skill: Tickets Assets ─────────────────────────────────────────────────────

async function runSkillTickets() {
    setBtnState('skillTicketsBtn', 'Consultando…', true);
    showSkillResult('skillTicketsResult', 'Cargando tickets…', true);

    try {
        const data = await apiJson('/api/nexus/assets-ops/tickets');
        const items = data.tasks || data.tickets || data.items || [];
        if (!items.length) {
            showSkillResult('skillTicketsResult', 'Sin tickets activos ✓', true);
        } else {
            const lines = items.slice(0, 5)
                .map(t => `• [${t.priority || t.status || '?'}] ${t.title || t.summary || '?'}`)
                .join('\n');
            showSkillResult('skillTicketsResult', `${items.length} ticket(s):\n${lines}`, true);
        }
    } catch (err) {
        showSkillResult('skillTicketsResult', `Error: ${err.message}`, false);
    } finally {
        setBtnState('skillTicketsBtn', 'Ver tickets', false);
    }
}

// ── Skill: Resultados de prospección ─────────────────────────────────────────

async function runSkillProspectResults() {
    setBtnState('skillResultsBtn', 'Consultando…', true);
    showSkillResult('skillResultsResult', 'Cargando resultados…', true);

    try {
        const data = await apiJson('/api/nexus/prospecting/results?limit=10');
        const results = data.results || data.items || [];
        if (!results.length) {
            showSkillResult('skillResultsResult', 'Sin resultados aún. Lanza una prospección primero.', true);
        } else {
            const lines = results.slice(0, 6)
                .map(r => `• [${r.score ?? '?'}] ${r.name || r.company_name || '?'} — ${r.city || ''}`)
                .join('\n');
            showSkillResult('skillResultsResult', `${results.length} resultado(s):\n${lines}`, true);
        }
    } catch (err) {
        showSkillResult('skillResultsResult', `Error: ${err.message}`, false);
    } finally {
        setBtnState('skillResultsBtn', 'Ver resultados', false);
    }
}

// ── Init ──────────────────────────────────────────────────────────────────────

function initPepo() {
    const form = document.getElementById('pepoChatForm');
    const input = document.getElementById('pepoInput');

    if (form && input) {
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const msg = input.value.trim();
            if (!msg || _pepoBusy) return;
            input.value = '';
            input.style.height = 'auto';
            sendToChat(msg);
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                form.dispatchEvent(new Event('submit'));
            }
        });

        input.addEventListener('input', () => {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 140) + 'px';
        });
    }

    document.querySelectorAll('[data-pepo-prompt]').forEach(btn => {
        btn.addEventListener('click', () => sendToChat(btn.dataset.pepoPrompt));
    });
}

document.addEventListener('DOMContentLoaded', initPepo);
