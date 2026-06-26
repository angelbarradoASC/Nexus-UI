/* nexus_campaign.js */

const API = '/api/nexus/campaign';

// ── Arranque ──────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadConfig();
});

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
    setInput('cfgDailyCap',     cfg.daily_send_cap ?? 20);
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
        daily_send_cap:       parseInt(document.getElementById('cfgDailyCap').value, 10) || 20,
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
