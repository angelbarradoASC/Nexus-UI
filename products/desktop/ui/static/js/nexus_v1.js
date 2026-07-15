function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

let autoRefreshTimer = null;
let assetsOpsBootstrapCache = null;
let assetsOpsAllTasks = [];
let _ticketSearchTimer = null;

const COLLECTOR_LINK_KINDS = ['prometheus', 'alertmanager', 'grafana'];

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

function collectorKindFromName(name) {
    const normalized = String(name || '').trim().toLowerCase();
    if (normalized.includes('prometheus')) return 'prometheus';
    if (normalized.includes('alertmanager')) return 'alertmanager';
    if (normalized.includes('grafana')) return 'grafana';
    return null;
}

async function loadCollectorLinks() {
    const payload = await requestJson('/api/desktop/operator/integrations');
    const integrations = Array.isArray(payload.integrations) ? payload.integrations : [];
    const links = {};

    for (const kind of COLLECTOR_LINK_KINDS) {
        const candidates = integrations.filter((item) =>
            item
            && item.kind === kind
            && item.enabled !== false
            && item.base_url
        );
        const preferred = candidates.find((item) => item.is_default) || candidates[0];
        if (preferred) {
            links[kind] = preferred.base_url;
        }
    }

    return links;
}

function renderCollectorBullet(collector, collectorLinks = {}) {
    const kind = collectorKindFromName(collector.name);
    const href = kind ? collectorLinks[kind] : '';
    const className = `status-bullet ${statusClass(collector.status)}`;
    const label = `${escapeHtml(collector.name)} - ${escapeHtml(collector.status)}`;

    if (!href) {
        return `<div class="${className}">${label}</div>`;
    }

    return `
        <a class="${className} status-bullet-link" href="${escapeHtml(href)}" target="_blank" rel="noreferrer noopener">
            ${label}
        </a>
    `;
}

function renderCollectorStatus(payload, collectorLinks = {}) {
    const node = document.getElementById('collectorStatusList');
    const healthBadge = document.getElementById('healthBadge');
    const collectorOverall = document.getElementById('collectorOverall');
    if (!node) return;

    const collectors = payload.collectors || [];
    if (!collectors.length) {
        node.innerHTML = '<div class="status-bullet loading">Sin recolectores configurados</div>';
    } else {
        node.innerHTML = collectors.map((collector) => renderCollectorBullet(collector, collectorLinks)).join('');
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

function wait(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isValidIpv4Address(value) {
    const candidate = String(value || '').trim();
    if (!candidate) return false;
    const octets = candidate.split('.');
    if (octets.length !== 4) return false;
    return octets.every((octet) => /^\d+$/.test(octet) && Number(octet) >= 0 && Number(octet) <= 255);
}

function syncOperatorAccessState() {
    const hostInput = document.getElementById('operatorHostInput');
    const rdpButton = document.getElementById('operatorRdpBtn');
    if (!hostInput || !rdpButton) return;

    const isValid = isValidIpv4Address(hostInput.value);
    hostInput.setAttribute('aria-invalid', (!isValid && hostInput.value.trim()) ? 'true' : 'false');
    rdpButton.disabled = !isValid;
}

async function launchRdpSession() {
    const hostInput = document.getElementById('operatorHostInput');
    const rdpButton = document.getElementById('operatorRdpBtn');
    if (!hostInput || !rdpButton) return;

    const host = hostInput.value.trim();
    if (!isValidIpv4Address(host)) {
        hostInput.focus();
        hostInput.setAttribute('aria-invalid', 'true');
        renderChatMessage('Sistema', 'La IP del acceso remoto no es valida.');
        return;
    }

    const previousLabel = rdpButton.textContent;
    rdpButton.disabled = true;
    rdpButton.textContent = 'Abriendo...';

    try {
        const response = await requestJson('/api/desktop/operator/rdp', {
            method: 'POST',
            body: JSON.stringify({ host }),
        });
        renderChatMessage('Sistema', `Sesion RDP abierta contra ${response.host}.`);
    } catch (error) {
        renderChatMessage('Sistema', `No se pudo abrir RDP: ${error.message}`);
    } finally {
        rdpButton.textContent = previousLabel;
        syncOperatorAccessState();
    }
}

function renderSelectOptions(selectId, items, { valueKey = 'id', labelKey = 'name', emptyLabel = 'Sin datos', includeBlank = true } = {}) {
    const select = document.getElementById(selectId);
    if (!select) return;

    const options = [];
    if (includeBlank) {
        options.push(`<option value="">${escapeHtml(emptyLabel)}</option>`);
    }
    for (const item of items || []) {
        const value = item?.[valueKey];
        const label = item?.[labelKey] ?? item?.title ?? `#${value}`;
        options.push(`<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`);
    }
    select.innerHTML = options.join('');
}

function setAssetsOpsStatus(text, tone = 'muted') {
    const badge = document.getElementById('assetsOpsStatusBadge');
    if (!badge) return;
    badge.textContent = text;
    badge.classList.remove('badge-muted', 'badge-ok', 'badge-warn', 'badge-danger');
    if (tone === 'ok') {
        badge.classList.add('badge-ok');
    } else if (tone === 'warn') {
        badge.classList.add('badge-warn');
    } else if (tone === 'danger') {
        badge.classList.add('badge-danger');
    } else {
        badge.classList.add('badge-muted');
    }
}

function renderAssetsOpsMeta(payload) {
    const baseNode = document.getElementById('assetsOpsBaseUrl');
    const userNode = document.getElementById('assetsOpsUsername');
    const noteNode = document.getElementById('assetsOpsFormNote');
    const assigneeSelect = document.getElementById('assetsTicketAssignee');

    const connector = payload?.connector || {};
    if (baseNode) {
        baseNode.textContent = connector.base_url || 'sin base';
    }
    if (userNode) {
        userNode.textContent = connector.username || 'sin usuario';
    }

    if (assigneeSelect) {
        const users = Array.isArray(payload?.users) ? payload.users : [];
        renderSelectOptions('assetsTicketAssignee', users, {
            emptyLabel: payload?.can_assign ? 'Sin asignar' : 'No disponible',
            includeBlank: true,
        });
        assigneeSelect.disabled = !payload?.can_assign;
    }

    if (noteNode) {
        noteNode.textContent = payload?.users_error
            ? payload.users_error
            : 'El operador puede crear tickets manuales; la IA podra usar este mismo endpoint.';
    }
}

function _buildTicketCard(task) {
    const taskId = Number(task.id || 0);
    const status = String(task.status || 'pending');
    const priority = String(task.priority || 'medium');
    const ticketType = String(task.ticket_type || 'task');
    const source = String(task.source || 'manual');
    const metaParts = [
        task.company_name || task.company?.name || '',
        task.project_name || task.project?.name || '',
        source,
    ].filter(Boolean);
    return `
        <article class="assets-ticket-card${status === 'done' ? ' assets-ticket-done' : ''}" data-task-id="${taskId}" data-status="${escapeHtml(status)}">
            <div class="assets-ticket-card-head">
                <div>
                    <h4>${escapeHtml(task.title || `Ticket ${taskId}`)}</h4>
                    <p>${escapeHtml(metaParts.join(' · ') || `#${taskId}`)}</p>
                </div>
                <div class="assets-ticket-badges">
                    <span class="pill">${escapeHtml(ticketType)}</span>
                    <span class="pill">${escapeHtml(priority)}</span>
                </div>
            </div>
            <p class="assets-ticket-description">${escapeHtml(task.description || 'Sin descripcion adicional.')}</p>
            <div class="assets-ticket-footer">
                <label class="field compact-field">
                    <span>Estado</span>
                    <select class="assets-ticket-status" data-task-id="${taskId}">
                        <option value="pending" ${status === 'pending' ? 'selected' : ''}>pending</option>
                        <option value="in_progress" ${status === 'in_progress' ? 'selected' : ''}>in_progress</option>
                        <option value="done" ${status === 'done' ? 'selected' : ''}>done</option>
                    </select>
                </label>
                <button class="btn btn-secondary assets-ticket-save" type="button" data-task-id="${taskId}">Guardar estado</button>
            </div>
        </article>
    `;
}

function _renderFilteredTickets() {
    const listNode = document.getElementById('assetsOpsTicketList');
    if (!listNode) return;

    const showDone = document.getElementById('assetsOpsShowDone')?.checked ?? false;
    const rawQuery = (document.getElementById('assetsTicketSearch')?.value ?? '').trim().toLowerCase();
    const numQuery = rawQuery.replace(/^#/, '');
    const isNumSearch = numQuery !== '' && /^\d+$/.test(numQuery);

    const filtered = assetsOpsAllTasks.filter((task) => {
        if (!showDone && String(task.status || '') === 'done') return false;
        if (!rawQuery) return true;
        if (isNumSearch) return String(task.id || '') === numQuery;
        const haystack = [
            task.title || '',
            task.description || '',
            task.company_name || task.company?.name || '',
            task.project_name || task.project?.name || '',
        ].join(' ').toLowerCase();
        return haystack.includes(rawQuery);
    });

    if (!filtered.length) {
        const hasDone = assetsOpsAllTasks.some((t) => String(t.status || '') === 'done');
        const msg = rawQuery
            ? `Sin resultados para <em>${escapeHtml(rawQuery)}</em>.`
            : (hasDone && !showDone)
                ? 'No hay tickets activos. Activa <strong>Completados</strong> para verlos.'
                : 'No hay tickets recientes en Assets.';
        listNode.innerHTML = `<div class="empty-state">${msg}</div>`;
        return;
    }

    listNode.innerHTML = filtered.map(_buildTicketCard).join('');
}

function renderAssetsOpsTickets(payload) {
    const countNode = document.getElementById('assetsOpsTicketCount');
    assetsOpsAllTasks = Array.isArray(payload?.tasks) ? payload.tasks : [];
    if (countNode) {
        countNode.textContent = String(payload?.total ?? assetsOpsAllTasks.length ?? 0);
    }
    _renderFilteredTickets();
}

async function loadAssetsOpsBootstrap(force = false) {
    if (assetsOpsBootstrapCache && !force) {
        return assetsOpsBootstrapCache;
    }

    const payload = await requestJson('/api/nexus/assets-ops/bootstrap');
    assetsOpsBootstrapCache = payload;

    renderSelectOptions('assetsTicketCompany', payload.companies || [], {
        emptyLabel: 'Sin empresa',
        includeBlank: true,
    });
    renderSelectOptions('assetsTicketProject', payload.projects || [], {
        emptyLabel: 'Sin proyecto',
        includeBlank: true,
    });
    renderAssetsOpsMeta(payload);

    if (payload.status === 'up') {
        setAssetsOpsStatus('Conectado', payload.can_assign ? 'ok' : 'warn');
    } else {
        setAssetsOpsStatus('Sin conectar', 'danger');
    }
    return payload;
}

async function loadAssetsOpsTickets() {
    const payload = await requestJson('/api/nexus/assets-ops/tickets?limit=50');
    renderAssetsOpsTickets(payload);
    return payload;
}

async function refreshAssetsOpsPanel(forceBootstrap = false) {
    const listNode = document.getElementById('assetsOpsTicketList');
    if (!listNode) return;

    try {
        await loadAssetsOpsBootstrap(forceBootstrap);
        await loadAssetsOpsTickets();
    } catch (error) {
        setAssetsOpsStatus('Error', 'danger');
        listNode.innerHTML = `<div class="empty-state">No se pudo cargar Assets: ${escapeHtml(error.message)}</div>`;
    }
}

async function submitAssetsTicket(event) {
    event.preventDefault();
    const submitButton = document.getElementById('assetsTicketSubmitBtn');
    const titleNode = document.getElementById('assetsTicketTitle');
    if (!titleNode) return;

    const title = titleNode.value.trim();
    if (!title) {
        titleNode.focus();
        return;
    }

    const previousLabel = submitButton?.textContent || 'Crear ticket';
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = 'Creando...';
    }

    try {
        await requestJson('/api/nexus/assets-ops/tickets', {
            method: 'POST',
            body: JSON.stringify({
                title,
                ticket_type: document.getElementById('assetsTicketType')?.value || 'task',
                priority: document.getElementById('assetsTicketPriority')?.value || 'medium',
                source: document.getElementById('assetsTicketSource')?.value || 'manual',
                company_id: document.getElementById('assetsTicketCompany')?.value || null,
                project_id: document.getElementById('assetsTicketProject')?.value || null,
                assigned_to_id: document.getElementById('assetsTicketAssignee')?.value || null,
                description: document.getElementById('assetsTicketDescription')?.value || '',
                status: 'pending',
            }),
        });
        document.getElementById('assetsOpsTicketForm')?.reset();
        setAssetsOpsStatus('Ticket creado', 'ok');
        renderChatMessage('Sistema', `Ticket creado en Assets: ${title}`);
        await refreshAssetsOpsPanel();
    } catch (error) {
        setAssetsOpsStatus('Error al crear', 'danger');
        renderChatMessage('Sistema', `No se pudo crear el ticket en Assets: ${error.message}`);
    } finally {
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.textContent = previousLabel;
        }
    }
}

async function createAssetsTicketFromChat() {
    const messageNode = document.getElementById('chatMessage');
    const button = document.getElementById('assetsTicketFromChatBtn');
    if (!(messageNode instanceof HTMLTextAreaElement) || !(button instanceof HTMLButtonElement)) return;

    const message = messageNode.value.trim();
    if (!message) {
        messageNode.focus();
        renderChatMessage('Sistema', 'Escribe primero en el chat lo que quieres escalar a ticket.');
        return;
    }

    const previousLabel = button.textContent;
    button.disabled = true;
    button.textContent = 'Procesando...';

    try {
        const result = await requestJson('/api/nexus/assets-ops/tickets/from-message', {
            method: 'POST',
            body: JSON.stringify({
                message,
                source: 'codex',
                actor: 'operator',
                trigger_kind: 'operator',
                context: {
                    mode: document.getElementById('chatMode')?.value || 'general',
                },
            }),
        });
        const ticketId = result.task_id || result.result?.task?.id;
        const ticketTitle = result.task_title || result.result?.task?.title || 'sin titulo';
        setAssetsOpsStatus('Ticket IA creado', 'ok');
        renderChatMessage('Sistema', `Ticket creado desde el chat: #${ticketId} · ${ticketTitle}`);
        await refreshAssetsOpsPanel();
    } catch (error) {
        setAssetsOpsStatus('Error IA', 'danger');
        renderChatMessage('Sistema', `No se pudo crear el ticket desde el chat: ${error.message}`);
    } finally {
        button.disabled = false;
        button.textContent = previousLabel;
    }
}

async function saveAssetsTicketStatus(taskId) {
    const select = document.querySelector(`.assets-ticket-status[data-task-id="${taskId}"]`);
    const button = document.querySelector(`.assets-ticket-save[data-task-id="${taskId}"]`);
    if (!(select instanceof HTMLSelectElement) || !(button instanceof HTMLButtonElement)) return;

    const previousLabel = button.textContent;
    button.disabled = true;
    button.textContent = 'Guardando...';

    try {
        await requestJson(`/api/nexus/assets-ops/tickets/${taskId}`, {
            method: 'PUT',
            body: JSON.stringify({ status: select.value }),
        });
        setAssetsOpsStatus('Estado guardado', 'ok');
        await refreshAssetsOpsPanel();
    } catch (error) {
        setAssetsOpsStatus('Error al guardar', 'danger');
        renderChatMessage('Sistema', `No se pudo actualizar el ticket ${taskId}: ${error.message}`);
    } finally {
        button.disabled = false;
        button.textContent = previousLabel;
    }
}

let busFlowToken = 0;

function resolveBusTargets(mode, agentRun) {
    const resolvedAgent = agentRun?.agent_id;
    const normalizedMode = String(mode || 'general').toLowerCase();

    if (resolvedAgent === 'operator' || normalizedMode === 'monitoring' || normalizedMode === 'incident' || normalizedMode === 'operator') {
        return ['operator', 'housekeeper'];
    }
    if (resolvedAgent === 'shell' || normalizedMode === 'shell' || normalizedMode === 'execution' || normalizedMode === 'investigation') {
        return ['shell', 'housekeeper'];
    }
    if (resolvedAgent === 'sales' || normalizedMode === 'sales' || normalizedMode === 'prospecting' || normalizedMode === 'crm' || normalizedMode === 'outreach') {
        return ['sales', 'housekeeper'];
    }
    return ['operator', 'shell', 'sales', 'housekeeper'];
}

function relayLabelFor(agentId) {
    const labels = {
        supervisor: 'Supervisor',
        operator: 'Operator',
        shell: 'Shell',
        sales: 'Sales',
        memory: 'Memory',
        guard: 'Guard',
        housekeeper: 'Housekeeper',
        spare: 'Expansion',
    };
    return labels[agentId] || agentId || 'Nexus';
}

function formatAgentSummary(targets) {
    if (!targets.length) return 'Supervisor listo';
    if (targets.length === 1) return `${relayLabelFor(targets[0])} activo`;
    return `Supervisor coordina ${targets.length} agentes`;
}

function setBusBadge(text) {
    const badge = document.getElementById('activeAgentBadge');
    if (!badge) return;
    badge.textContent = text;
}

function renderBusState({
    label,
    pipelineLive = false,
    pipelineState = 'Escuchando',
    phase = 'idle',
    supervisorBusy = false,
    activeAgents = [],
    completedAgents = [],
    busyAgents = [],
}) {
    const labelNode = document.getElementById('agentBusLabel');
    const pipelineNode = document.getElementById('entryPipeline');
    const pipelineStateNode = document.getElementById('entryPipelineState');
    const boardNode = document.getElementById('agentBusBoard');

    if (labelNode) {
        labelNode.textContent = label;
    }
    if (pipelineNode) {
        pipelineNode.classList.toggle('is-live', pipelineLive);
    }
    if (pipelineStateNode) {
        pipelineStateNode.textContent = pipelineState;
    }
    if (boardNode) {
        boardNode.dataset.phase = phase;
    }

    document.querySelectorAll('.agent-bus-node').forEach((node) => {
        const agentId = node.dataset.agent;
        const isSupervisor = agentId === 'supervisor';
        node.classList.toggle('is-active', activeAgents.includes(agentId) || (isSupervisor && supervisorBusy));
        node.classList.toggle('is-busy', busyAgents.includes(agentId) || (isSupervisor && supervisorBusy));
        node.classList.toggle('is-complete', completedAgents.includes(agentId));
    });
}

function resetBus() {
    renderBusState({
        label: 'Supervisor en espera',
        pipelineLive: false,
        pipelineState: 'Escuchando',
        phase: 'idle',
        supervisorBusy: false,
        activeAgents: ['supervisor'],
        completedAgents: [],
        busyAgents: [],
    });
    setBusBadge('Supervisor listo');
}

async function playBusFlow(mode, agentRun) {
    const flowToken = ++busFlowToken;
    const targets = resolveBusTargets(mode, agentRun);
    const dispatchTargets = targets.filter((agentId) => agentId !== 'housekeeper');

    renderBusState({
        label: 'Entrada al supervisor',
        pipelineLive: true,
        pipelineState: 'Solicitud entrando',
        phase: 'dispatch',
        supervisorBusy: true,
        activeAgents: ['supervisor'],
        busyAgents: ['supervisor'],
        completedAgents: [],
    });
    setBusBadge('Supervisor analizando');
    await wait(560);
    if (flowToken !== busFlowToken) return;

    renderBusState({
        label: dispatchTargets.length > 1
            ? 'Supervisor despacha en paralelo'
            : `Supervisor activa ${relayLabelFor(dispatchTargets[0] || 'housekeeper')}`,
        pipelineLive: false,
        pipelineState: 'Supervisor coordinando',
        phase: dispatchTargets.length > 1 ? 'parallel' : 'dispatch',
        supervisorBusy: true,
        activeAgents: ['supervisor', ...targets],
        busyAgents: ['supervisor', ...dispatchTargets],
        completedAgents: [],
    });
    setBusBadge(formatAgentSummary(targets));
    await wait(1600);
    if (flowToken !== busFlowToken) return;

    renderBusState({
        label: 'Supervisor recibe y consolida',
        pipelineLive: false,
        pipelineState: 'Respuestas en curso',
        phase: 'return',
        supervisorBusy: true,
        activeAgents: ['supervisor', ...targets],
        busyAgents: ['supervisor', 'housekeeper'],
        completedAgents: dispatchTargets,
    });
    setBusBadge('Housekeeper ordenando contexto');
    await wait(1100);
    if (flowToken !== busFlowToken) return;

    renderBusState({
        label: 'Contexto ordenado',
        pipelineLive: false,
        pipelineState: 'Listo para el siguiente turno',
        phase: 'idle',
        supervisorBusy: false,
        activeAgents: ['supervisor'],
        busyAgents: [],
        completedAgents: targets,
    });
    setBusBadge('Supervisor listo');
    await wait(700);
    if (flowToken !== busFlowToken) return;

    resetBus();
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
        let collectorLinks = {};
        try {
            collectorLinks = await loadCollectorLinks();
        } catch (error) {
            console.warn('No se pudieron resolver los enlaces de integraciones:', error);
        }
        renderCollectorStatus(data, collectorLinks);
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
        const mode = modeInput?.value || 'general';
        let agentRun = null;
        try {
            agentRun = await requestJson('/api/nexus/agents/runs', {
                method: 'POST',
                body: JSON.stringify({
                    message,
                    user_id: 'demo-user',
                    source_surface: 'desktop',
                    mode,
                }),
            });
        } catch (agentError) {
            console.warn('No se pudo crear el run agentico, sigo con el fallback visual', agentError);
        }

        void playBusFlow(mode, agentRun);
        const response = await requestJson('/api/nexus/chat', {
            method: 'POST',
            body: JSON.stringify({
                message,
                user_id: 'demo-user',
                mode,
            }),
        });
        renderChatMessage('Nexus', response.response || 'Solicitud aceptada');
        await refreshAssetsOpsPanel();
        await loadAuditFeeds();
    } catch (error) {
        renderChatMessage('Sistema', `Error: ${error.message}`);
        resetBus();
    }
}

async function refreshAllData() {
    await loadCollectors();
    await refreshAssetsOpsPanel();
    await loadAuditFeeds();
    await loadIncidentActivity();
    updateLastSync();
}

document.addEventListener('DOMContentLoaded', async () => {
    document.getElementById('chatForm')?.addEventListener('submit', sendChat);
    document.getElementById('manualRefreshBtn')?.addEventListener('click', refreshAllData);
    document.getElementById('assetsOpsRefreshBtn')?.addEventListener('click', () => refreshAssetsOpsPanel(true));
    document.getElementById('assetsOpsTicketForm')?.addEventListener('submit', submitAssetsTicket);
    document.getElementById('assetsTicketFromChatBtn')?.addEventListener('click', createAssetsTicketFromChat);
    document.getElementById('assetsOpsShowDone')?.addEventListener('change', _renderFilteredTickets);
    document.getElementById('assetsTicketSearch')?.addEventListener('input', () => {
        window.clearTimeout(_ticketSearchTimer);
        _ticketSearchTimer = window.setTimeout(_renderFilteredTickets, 200);
    });
    document.getElementById('operatorHostInput')?.addEventListener('input', syncOperatorAccessState);
    document.getElementById('operatorRdpBtn')?.addEventListener('click', launchRdpSession);
    document.getElementById('assetsOpsTicketList')?.addEventListener('click', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        const button = target.closest('.assets-ticket-save');
        if (!(button instanceof HTMLButtonElement)) return;
        const taskId = Number(button.dataset.taskId || 0);
        if (!taskId) return;
        void saveAssetsTicketStatus(taskId);
    });
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

    resetBus();
    syncOperatorAccessState();
    await refreshAllData();
    autoRefreshTimer = window.setInterval(refreshAllData, 60000);
});
