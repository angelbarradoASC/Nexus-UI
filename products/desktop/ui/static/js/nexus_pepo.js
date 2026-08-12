// nexus_pepo.js — PEPO chat + skills panel

const PEPO_ACTIVE_CONVERSATION_KEY = 'pepo_active_conversation_id';

// Conversacion activa persistida en localStorage — mismo patron que
// nexus_last_run_id en nexus_sales.js. Antes _pepoContextId nunca se
// asignaba, asi que todo PEPO compartia un unico "user_id" fijo sin
// distinguir conversaciones; ahora es el id real de la conversacion activa,
// y se manda como context_id en cada peticion a /api/nexus/chat.
let _pepoContextId = localStorage.getItem(PEPO_ACTIVE_CONVERSATION_KEY) || null;
let _pepoBusy = false;
// Cuando PEPO pide un secreto (contraseña/token) via ask_user_secret, la
// respuesta trae redact_next_reply=true — el turno que el usuario responda
// a continuacion se guarda en el historial como "[secreto omitido]" en vez
// del texto real (que si se manda tal cual a /api/nexus/chat, unico sitio
// que lo necesita para procesarlo).
let _pepoRedactNextUserTurn = false;
let _pepoRunPollTimer = null;
let _pepoRunSeenCount = 0;

const PEPO_RUN_TERMINAL_STATUSES = new Set(['completed', 'failed', 'timeout', 'budget_exceeded', 'not_found']);

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

// Un mensaje de PEPO puede traer un bloque ```...``` (el script que va a
// ejecutar). El usuario final no quiere ver PowerShell en crudo — se separa
// el texto en lenguaje llano del codigo, y el codigo se oculta detras de un
// <details> plegable (mismo patron que "Ver proceso de pensamiento"). Todo
// el contenido dinamico se sigue escapando por separado: solo las etiquetas
// <details>/<summary> son HTML literal nuestro, nunca texto del LLM.
function renderBubbleContent(text) {
    const codeFence = /```[a-zA-Z]*\n?([\s\S]*?)```/;
    const match = text.match(codeFence);
    if (!match) {
        return escHtml(text).replace(/\n/g, '<br>');
    }

    const before = text.slice(0, match.index).trim();
    const after = text.slice(match.index + match[0].length).trim();
    const code = match[1].trim();

    const beforeHtml = before ? `${escHtml(before).replace(/\n/g, '<br>')}` : '';
    const afterHtml = after ? `<div class="pepo-bubble-after">${escHtml(after).replace(/\n/g, '<br>')}</div>` : '';

    return `${beforeHtml}
        <details class="pepo-code-toggle">
            <summary>Ver script</summary>
            <pre><code>${escHtml(code)}</code></pre>
        </details>
        ${afterHtml}`;
}

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
        const bodyHtml = role === 'user'
            ? escHtml(text).replace(/\n/g, '<br>')
            : renderBubbleContent(text);
        wrap.innerHTML = `<p class="pepo-msg-role">${escHtml(roleLabel)}</p>
            <div class="pepo-bubble">${bodyHtml}</div>`;
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
        // Primer mensaje de un chat nuevo: crea la conversacion en BBDD antes
        // de hablar con el LLM, asi el context_id que ve /api/nexus/chat ya
        // es el real (aisla la memoria de esta conversacion de las demas).
        if (!_pepoContextId) {
            try {
                const created = await apiJson('/api/desktop/pepo/conversations', {
                    method: 'POST',
                    body: JSON.stringify({ first_message: message }),
                });
                setActiveConversationId(created.conversation.id);
                loadConversationsList();
            } catch (err) {
                console.warn('No se pudo crear la conversacion — el chat sigue sin persistir', err);
            }
        }

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
        const reply = data.response || '(sin respuesta)';
        appendMsg('pepo', reply);
        if (data.run_id) startRunTrace(data.run_id);

        if (_pepoContextId) {
            try {
                await apiJson(`/api/desktop/pepo/conversations/${encodeURIComponent(_pepoContextId)}/messages`, {
                    method: 'POST',
                    body: JSON.stringify({
                        user_message: _pepoRedactNextUserTurn ? '[secreto omitido]' : message,
                        assistant_message: reply,
                    }),
                });
                loadConversationsList();
            } catch (err) {
                console.warn('No se pudo guardar el turno en el historial', err);
            }
        }
        _pepoRedactNextUserTurn = !!data.redact_next_reply;
    } catch (err) {
        thinkEl?.remove();
        appendMsg('pepo', `Error al conectar: ${err.message}`);
    } finally {
        _pepoBusy = false;
        if (sendBtn) sendBtn.disabled = false;
        if (input) input.focus();
    }
}

// ── Conversaciones (barra izquierda) ────────────────────────────────────────

function setActiveConversationId(id) {
    _pepoContextId = id;
    if (id) {
        localStorage.setItem(PEPO_ACTIVE_CONVERSATION_KEY, id);
    } else {
        localStorage.removeItem(PEPO_ACTIVE_CONVERSATION_KEY);
    }
}

function clearChatLogToGreeting() {
    const log = document.getElementById('pepoChatLog');
    if (!log) return;
    log.innerHTML = `<div class="pepo-msg pepo-msg-pepo" data-pepo-greeting="true">
        <p class="pepo-msg-role">PEPO</p>
        <div class="pepo-bubble">Hola. Soy PEPO, tu agente personal. Puedo ayudarte con operaciones, prospección comercial, incidentes y más. También puedes lanzar skills desde el panel de la derecha. ¿En qué empezamos?</div>
    </div>`;
}

function startNewChat() {
    if (_pepoBusy) return;
    setActiveConversationId(null);
    clearChatLogToGreeting();
    renderConversationsList(_pepoConversationsCache);
    _pepoRedactNextUserTurn = false;
    const input = document.getElementById('pepoInput');
    if (input) input.focus();
}

let _pepoConversationsCache = [];

function renderConversationsList(conversations) {
    _pepoConversationsCache = conversations || [];
    const list = document.getElementById('pepoConversationsList');
    if (!list) return;

    if (!_pepoConversationsCache.length) {
        list.innerHTML = '<div class="pepo-conversations-empty">Sin conversaciones todavía</div>';
        return;
    }

    list.innerHTML = _pepoConversationsCache.map(c => `
        <button type="button" class="pepo-conversation-item ${c.id === _pepoContextId ? 'is-active' : ''}"
            data-conversation-id="${escHtml(c.id)}" title="${escHtml(c.title)}">${escHtml(c.title)}</button>
    `).join('');

    list.querySelectorAll('[data-conversation-id]').forEach(btn => {
        btn.addEventListener('click', () => switchConversation(btn.dataset.conversationId));
    });
}

async function loadConversationsList() {
    try {
        const data = await apiJson('/api/desktop/pepo/conversations');
        renderConversationsList(data.conversations || []);
    } catch (err) {
        console.warn('No se pudo cargar el historial de conversaciones', err);
    }
}

async function switchConversation(conversationId) {
    if (_pepoBusy || conversationId === _pepoContextId) return;
    _pepoRedactNextUserTurn = false;
    await loadConversationMessages(conversationId);
}

async function loadConversationMessages(conversationId) {
    const log = document.getElementById('pepoChatLog');
    try {
        const data = await apiJson(`/api/desktop/pepo/conversations/${encodeURIComponent(conversationId)}/messages`);
        setActiveConversationId(conversationId);
        if (log) {
            log.innerHTML = '';
            (data.messages || []).forEach(m => appendMsg(m.role === 'user' ? 'user' : 'pepo', m.content));
            if (!data.messages || !data.messages.length) clearChatLogToGreeting();
        }
        renderConversationsList(_pepoConversationsCache);
    } catch (err) {
        // Conversacion ya no existe (BBDD reseteada, etc.) — se limpia el
        // puntero guardado y se cae al estado vacio en vez de quedarse
        // apuntando a un id muerto para siempre.
        console.warn('No se pudo cargar la conversacion — se limpia el puntero guardado', err);
        setActiveConversationId(null);
        clearChatLogToGreeting();
    }
}

// ── Traza de ejecución del run (panel derecho) ────────────────────────────────

async function loadSkillSource() {
    const el = document.getElementById('pepoRunCode');
    if (!el) return;
    try {
        const data = await apiJson('/api/nexus/prospecting/skill-source');
        el.textContent = data.source || '(sin código)';
    } catch (err) {
        el.textContent = `No se pudo cargar el código: ${err.message}`;
    }
}

function startRunTrace(runId) {
    if (_pepoRunPollTimer) clearInterval(_pepoRunPollTimer);
    _pepoRunSeenCount = 0;

    const console_ = document.getElementById('pepoRunConsole');
    const statusBadge = document.getElementById('pepoRunStatus');
    if (console_) console_.innerHTML = '';
    if (statusBadge) statusBadge.textContent = runId;

    const poll = async () => {
        try {
            const data = await apiJson(`/api/nexus/prospecting/runs/${runId}/logs`);
            if (statusBadge) statusBadge.textContent = `${runId} — ${data.status || '?'}`;

            const logs = data.logs || [];
            for (let i = _pepoRunSeenCount; i < logs.length; i++) {
                appendRunLine(logs[i]);
            }
            _pepoRunSeenCount = logs.length;

            if (PEPO_RUN_TERMINAL_STATUSES.has(data.status)) {
                clearInterval(_pepoRunPollTimer);
                _pepoRunPollTimer = null;
            }
        } catch (err) {
            appendRunLine({ level: 'error', msg: `Error consultando el run: ${err.message}` });
            clearInterval(_pepoRunPollTimer);
            _pepoRunPollTimer = null;
        }
    };

    poll();
    _pepoRunPollTimer = setInterval(poll, 2000);
}

function appendRunLine(entry) {
    const console_ = document.getElementById('pepoRunConsole');
    if (!console_) return;

    const empty = console_.querySelector('.pepo-run-console-empty');
    if (empty) empty.remove();

    const line = document.createElement('div');
    const level = entry.level || 'info';
    line.className = `pepo-run-console-line level-${level}`;

    const ts = entry.ts ? new Date(entry.ts).toLocaleTimeString() : '';
    const dataStr = entry.data ? ` ${JSON.stringify(entry.data)}` : '';
    line.innerHTML = `${ts ? `<span class="ts">${escHtml(ts)}</span>` : ''}${escHtml(entry.msg || '')}${escHtml(dataStr)}`;

    console_.appendChild(line);
    console_.scrollTop = console_.scrollHeight;
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

    const newChatBtn = document.getElementById('pepoNewChatBtn');
    if (newChatBtn) newChatBtn.addEventListener('click', startNewChat);
}

document.addEventListener('DOMContentLoaded', async () => {
    initPepo();
    loadSkillSource();
    await loadConversationsList();
    // Restaura la conversacion activa (si la habia) para que volver a la
    // pestaña no borre el historial visible — se mantiene hasta "Nuevo chat".
    if (_pepoContextId) {
        await loadConversationMessages(_pepoContextId);
    }
});
