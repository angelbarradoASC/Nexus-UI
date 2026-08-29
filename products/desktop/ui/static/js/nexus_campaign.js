/* nexus_campaign.js */

const API = '/api/nexus/campaign';

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

// ── Arranque ──────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadConfig();
    loadResults();
    loadPending();
});

// ── Descomposición y verificación de ida y vuelta ────────────────────────

async function decomposeAndVerify() {
    const input = document.getElementById('decomposeInput');
    const text = input.value.trim();
    if (!text) {
        toast('Escribe algo primero', true);
        return;
    }

    const btn = document.getElementById('decomposeBtn');
    const statusEl = document.getElementById('decomposeStatus');
    const badge = document.getElementById('decomposeBadge');
    btn.disabled = true;
    statusEl.textContent = 'descomponiendo y verificando… (el LLM local puede tardar)';
    badge.textContent = '…';
    badge.className = 'camp-badge camp-badge--unknown';

    try {
        const res = await fetch(`${API}/decompose-verify`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
        });
        const data = await res.json();
        renderDecomposeResult(data);
    } catch (err) {
        toast('Error al descomponer', true);
        badge.textContent = 'error';
        badge.className = 'camp-badge camp-badge--stopped';
    } finally {
        btn.disabled = false;
        statusEl.textContent = '';
    }
}

function renderDecomposeResult(data) {
    const el = document.getElementById('decomposeResult');
    const badge = document.getElementById('decomposeBadge');

    if (data.status !== 'ok') {
        el.className = 'camp-decompose-result';
        el.innerHTML = `<span>Error: ${escapeHtml(data.error || 'desconocido')}</span>`;
        badge.textContent = 'error';
        badge.className = 'camp-badge camp-badge--stopped';
        return;
    }

    const q = data.query || {};
    const jsonBlock = JSON.stringify(
        { vertical: q.vertical, business_type: q.business_type, city: q.city, radius_km: q.radius_km },
        null, 2,
    );

    let similarityHtml = '<span class="camp-similarity-pill camp-similarity-pill--unknown">sin verificar</span>';
    if (typeof data.similarity === 'number') {
        const pct = Math.round(data.similarity * 100);
        const cls = data.consistent ? 'camp-similarity-pill--pass' : 'camp-similarity-pill--fail';
        similarityHtml = `<span class="camp-similarity-pill ${cls}">${pct}%</span>`;
    }

    if (data.consistent === true) {
        badge.textContent = 'consistente';
        badge.className = 'camp-badge camp-badge--running';
    } else if (data.consistent === false) {
        badge.textContent = 'desviado';
        badge.className = 'camp-badge camp-badge--stopped';
    } else {
        badge.textContent = 'sin verificar';
        badge.className = 'camp-badge camp-badge--disabled';
    }

    el.className = 'camp-decompose-result';
    el.innerHTML = `
        <div class="camp-decompose-json">${escapeHtml(jsonBlock)}</div>
        <div class="camp-decompose-row">
            <span class="camp-meta-label">Versión limpia</span>
            <span>${escapeHtml(q.clean_intent || '—')}</span>
        </div>
        <div class="camp-decompose-row">
            <span class="camp-meta-label">Reconstrucción LLM</span>
            <span>${escapeHtml(data.reconstructed || '—')}</span>
        </div>
        <div class="camp-decompose-row">
            <span class="camp-meta-label">Similitud</span>
            ${similarityHtml}
        </div>
        <div class="camp-decompose-row">
            <span class="camp-meta-label">Nota</span>
            <span>${escapeHtml(data.note || '')}</span>
        </div>
    `;
}

// ── Estado del scheduler ──────────────────────────────────────────────────

async function loadStatus() {
    try {
        const res = await fetch(`${API}/status`);
        const data = await res.json();
        renderStatus(data);
    } catch (err) {
        setEl('nextRunAt', 'error');
    }
}

function renderStatus(data) {
    const sched = data.scheduler || {};
    const badge = document.getElementById('schedulerBadge');

    if (sched.running) {
        badge.textContent = 'activo';
        badge.className = 'camp-badge camp-badge--running';
    } else {
        badge.textContent = 'detenido';
        badge.className = 'camp-badge camp-badge--stopped';
    }

    setEl('nextRunAt', formatDt(sched.next_run_at) || '—');
    setEl('lastRunAt', formatDt(sched.last_run_at) || '—');
    renderReport(sched.last_run_report);
}

function renderReport(report) {
    const el = document.getElementById('lastRunReport');
    if (!report) {
        el.textContent = 'Sin ejecuciones previas en esta sesión';
        el.className = 'camp-report camp-report--empty';
        return;
    }

    const lines = [];
    const status = report.status || '?';
    lines.push(`Estado:          ${status}`);

    if (report.started_at)   lines.push(`Inicio:          ${formatDt(report.started_at)}`);
    if (report.completed_at) lines.push(`Fin:             ${formatDt(report.completed_at)}`);

    const fu = report.followups || {};
    if (fu.campaigns_checked !== undefined)
        lines.push(`Follow-ups:      ${fu.executed_count ?? 0} enviados en ${fu.campaigns_checked} campañas activas`);

    const nc = report.new_campaign || {};
    if (nc.status) {
        lines.push(`Nueva campaña:   ${nc.status}`);
        if (nc.campaign_id)  lines.push(`  campaign_id:   ${nc.campaign_id}`);
        if (nc.sent_count !== undefined) lines.push(`  emails enviados: ${nc.sent_count}`);
        if (nc.prospects !== undefined)  lines.push(`  prospectos:    ${nc.prospects}`);
    }

    if (report.errors && report.errors.length) {
        lines.push('');
        lines.push('Errores:');
        report.errors.forEach(e => lines.push(`  • ${e}`));
    }

    el.textContent = lines.join('\n');
    el.className = 'camp-report ' + (
        status === 'ok' ? 'camp-report--ok' :
        status === 'error' ? 'camp-report--error' : ''
    );
}

// ── Trigger manual ────────────────────────────────────────────────────────

async function triggerCampaign() {
    const btn = document.getElementById('triggerBtn');
    const statusEl = document.getElementById('triggerStatus');

    btn.disabled = true;
    statusEl.textContent = 'ejecutando…';

    try {
        const res = await fetch(`${API}/trigger`, { method: 'POST' });
        const data = await res.json();
        renderReport(data.report || data);
        setEl('lastRunAt', formatDt(data.report?.completed_at || new Date().toISOString()));
        statusEl.textContent = 'completado';
        toast('Ciclo completado');
        loadResults();
        loadPending();
    } catch (err) {
        statusEl.textContent = 'error';
        toast('Error al ejecutar el ciclo', true);
    } finally {
        btn.disabled = false;
        setTimeout(() => { statusEl.textContent = ''; }, 4000);
    }
}

// ── Configuración ─────────────────────────────────────────────────────────

async function loadConfig() {
    try {
        const res = await fetch(`${API}/config`);
        const data = await res.json();
        applyConfig(data.config || {});
    } catch (err) {
        toast('No se pudo cargar la configuración', true);
    }
}

function applyConfig(cfg) {
    setInput('cfgVertical',     cfg.vertical      || '');
    setInput('cfgTargetDesc',   cfg.target_description || '');
    setInput('cfgGeography',    cfg.geography     || '');
    setInput('cfgDesiredCount', cfg.desired_count ?? 30);
    setInput('cfgDailyCap',     cfg.daily_send_cap ?? 2);
    setInput('cfgOpportunityThreshold', cfg.opportunity_threshold ?? 55);
    setInput('cfgFollowups',    (cfg.followup_delays_days || [14, 14]).join(', '));
    setInput('cfgProposition',  cfg.proposition   || '');
    setInput('cfgCta',          cfg.cta           || '');

    const toggle = document.getElementById('enabledToggle');
    const label  = document.getElementById('enabledLabel');
    const enabled = cfg.enabled !== false;
    toggle.checked  = enabled;
    label.textContent = enabled ? 'activa' : 'pausada';
}

async function toggleEnabled(checkbox) {
    const label   = document.getElementById('enabledLabel');
    const enabled = checkbox.checked;
    label.textContent = enabled ? 'activa' : 'pausada';

    try {
        const res = await fetch(`${API}/config`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled }),
        });
        await res.json();
        toast(enabled ? 'Campaña activada' : 'Campaña pausada');
    } catch {
        toast('Error al actualizar', true);
    }
}

async function saveConfig(event) {
    event.preventDefault();
    const statusEl = document.getElementById('saveStatus');
    statusEl.textContent = 'guardando…';

    const followupsRaw = document.getElementById('cfgFollowups').value;
    const followups = followupsRaw.split(',').map(v => parseInt(v.trim(), 10)).filter(n => !isNaN(n));

    const payload = {
        vertical:             document.getElementById('cfgVertical').value.trim(),
        target_description:   document.getElementById('cfgTargetDesc').value.trim(),
        geography:            document.getElementById('cfgGeography').value.trim(),
        desired_count:        parseInt(document.getElementById('cfgDesiredCount').value, 10) || 30,
        daily_send_cap:       parseInt(document.getElementById('cfgDailyCap').value, 10) || 2,
        opportunity_threshold: parseInt(document.getElementById('cfgOpportunityThreshold').value, 10) || 55,
        followup_delays_days: followups.length ? followups : [14, 14],
        proposition:          document.getElementById('cfgProposition').value.trim(),
        cta:                  document.getElementById('cfgCta').value.trim(),
    };

    try {
        const res = await fetch(`${API}/config`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        await res.json();
        statusEl.textContent = 'guardado ✓';
        toast('Configuración guardada');
    } catch {
        statusEl.textContent = 'error';
        toast('Error al guardar', true);
    } finally {
        setTimeout(() => { statusEl.textContent = ''; }, 3000);
    }
}

// ── Cola de revisión — nadie se contacta sin pasar por aquí ────────────────

async function loadPending() {
    try {
        const res = await fetch(`${API}/pending`);
        const data = await res.json();
        renderPending(data.pending || []);
    } catch (err) {
        renderPending([]);
    }
}

function renderPending(items) {
    const list = document.getElementById('pendingList');
    const countBadge = document.getElementById('pendingCount');
    if (!list) return;

    if (countBadge) countBadge.textContent = String(items.length);

    if (!items.length) {
        list.innerHTML = '<div class="camp-report camp-report--empty">Sin leads pendientes de revisión</div>';
        return;
    }

    list.innerHTML = items.map(item => {
        const resultId = escapeHtml(item.result_id || '');
        const meta = [item.city || item.province].filter(Boolean).join(' · ');
        const nameCell = item.website
            ? `<a href="${escapeHtml(item.website)}" target="_blank" rel="noreferrer">${escapeHtml(item.name || '')}</a>`
            : escapeHtml(item.name || '');
        const oppScore = item.opportunity_score;
        const oppCell = oppScore !== undefined && oppScore !== null
            ? `<span class="camp-score-pill ${opportunityClass(item.opportunity_confidence)}">${escapeHtml(String(oppScore))}</span>`
            : '';

        const findings = (item.technical_audit && item.technical_audit.findings) || [];
        const proposalItems = (item.proposal && item.proposal.items) || [];
        const lines = [
            ...findings.map(f => `• ${f}`),
            ...proposalItems.map(p => `→ ${p.observation}\n  Propuesta: ${p.recommendation}`),
        ];

        return `<div class="camp-pending-card" data-result-id="${resultId}">
            <div class="camp-pending-card-head">
                <div>
                    <div class="camp-company-name">${nameCell}</div>
                    ${meta ? `<div class="camp-company-meta">${escapeHtml(meta)}</div>` : ''}
                </div>
                ${oppCell}
            </div>
            ${lines.length ? `<div class="camp-pending-findings">${escapeHtml(lines.join('\n'))}</div>` : ''}
            <div class="camp-pending-actions">
                <button class="camp-btn camp-btn--danger" type="button" onclick="discardPending('${resultId}')">Descartar</button>
                <button class="camp-btn camp-btn--primary" type="button" onclick="sendPending('${resultId}')" ${item.email ? '' : 'disabled title="Sin email de contacto"'}>Enviar</button>
            </div>
        </div>`;
    }).join('');
}

async function sendPending(resultId) {
    const card = document.querySelector(`.camp-pending-card[data-result-id="${CSS.escape(resultId)}"]`);
    const buttons = card ? card.querySelectorAll('button') : [];
    buttons.forEach(b => b.disabled = true);

    try {
        const res = await fetch(`${API}/pending/${encodeURIComponent(resultId)}/send`, { method: 'POST' });
        const data = await res.json();
        if (data.status === 'sent') {
            toast('Email enviado');
        } else if (data.status === 'failed') {
            toast(data.error ? `No se pudo enviar: ${data.error}` : 'No se pudo enviar — revisa el SMTP', true);
        } else {
            toast('No encontrado', true);
        }
    } catch {
        toast('Error al enviar', true);
    } finally {
        loadPending();
        loadResults();
    }
}

async function discardPending(resultId) {
    const card = document.querySelector(`.camp-pending-card[data-result-id="${CSS.escape(resultId)}"]`);
    const buttons = card ? card.querySelectorAll('button') : [];
    buttons.forEach(b => b.disabled = true);

    try {
        await fetch(`${API}/pending/${encodeURIComponent(resultId)}/discard`, { method: 'POST' });
        toast('Lead descartado');
    } catch {
        toast('Error al descartar', true);
    } finally {
        loadPending();
    }
}

// ── Resultados de la última ejecución ────────────────────────────────────

async function loadResults() {
    try {
        const res = await fetch(`${API}/results`);
        const data = await res.json();
        renderCampaignResults(data.results || []);
    } catch (err) {
        renderCampaignResults([]);
    }
}

function opportunityClass(confidence) {
    if (confidence === 'alta') return 'camp-score-alta';
    if (confidence === 'media') return 'camp-score-media';
    return 'camp-score-baja';
}

function renderCampaignResults(items) {
    const tbody = document.getElementById('campaignResultsBody');
    const countBadge = document.getElementById('resultsCount');
    if (!tbody) return;

    if (countBadge) countBadge.textContent = String(items.length);

    if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-table">Sin ejecuciones todavía</td></tr>';
        return;
    }

    tbody.innerHTML = items.map((item, index) => {
        const meta = [item.city || item.province, item.vertical].filter(Boolean).join(' · ');
        const nameCell = item.website
            ? `<a href="${escapeHtml(item.website)}" target="_blank" rel="noreferrer">${escapeHtml(item.name || '')}</a>`
            : escapeHtml(item.name || '');
        const oppScore = item.opportunity_score;
        const oppCell = oppScore !== undefined && oppScore !== null
            ? `<span class="camp-score-pill ${opportunityClass(item.opportunity_confidence)}">${escapeHtml(String(oppScore))}</span>`
            : '<span class="muted-text">—</span>';
        const stage = item.lead_stage || 'DISCOVERED';
        const stageCell = `<span class="camp-stage-badge camp-stage-${escapeHtml(stage)}">${escapeHtml(stage.replace(/_/g, ' ').toLowerCase())}</span>`;
        const contactLines = [
            item.email ? `<a href="mailto:${escapeHtml(item.email)}" class="contact-link">${escapeHtml(item.email)}</a>` : '',
            item.phone ? `<span class="contact-phone">${escapeHtml(item.phone)}</span>` : '',
        ].filter(Boolean).join('<br>');

        const findings = (item.technical_audit && item.technical_audit.findings) || [];
        const proposalItems = (item.proposal && item.proposal.items) || [];
        const hasDetail = findings.length || proposalItems.length;
        const detailId = `campFindings${index}`;

        const rows = [`<tr data-result-id="${escapeHtml(item.result_id || '')}">
            <td>
                <div class="camp-company-name">${nameCell}</div>
                ${meta ? `<div class="camp-company-meta">${escapeHtml(meta)}</div>` : ''}
            </td>
            <td>${oppCell}</td>
            <td>${stageCell}</td>
            <td>${contactLines || '<span class="muted-text">sin contacto</span>'}</td>
            <td>${hasDetail ? `<button class="camp-findings-toggle" type="button" onclick="toggleFindings('${detailId}')">ver auditoría</button>` : ''}</td>
        </tr>`];

        if (hasDetail) {
            const lines = [
                ...findings.map(f => `• ${f}`),
                ...proposalItems.map(p => `→ ${p.observation}\n  Propuesta: ${p.recommendation}`),
            ];
            rows.push(`<tr id="${detailId}" class="camp-findings-row" style="display:none;">
                <td colspan="5">${escapeHtml(lines.join('\n'))}</td>
            </tr>`);
        }
        return rows.join('');
    }).join('');
}

function toggleFindings(id) {
    const row = document.getElementById(id);
    if (!row) return;
    row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
}

// ── Helpers ───────────────────────────────────────────────────────────────

function setEl(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function setInput(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value;
}

function formatDt(iso) {
    if (!iso) return null;
    try {
        return new Date(iso).toLocaleString('es-ES', {
            day:    '2-digit',
            month:  '2-digit',
            year:   'numeric',
            hour:   '2-digit',
            minute: '2-digit',
        });
    } catch { return iso; }
}

let _toastTimer = null;

function toast(msg, isError = false) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.style.borderColor = isError ? 'rgba(248,113,113,0.4)' : 'rgba(255,255,255,0.12)';
    el.classList.add('camp-toast--visible');
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => el.classList.remove('camp-toast--visible'), 3500);
}
