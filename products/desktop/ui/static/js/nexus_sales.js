function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

let latestOutreachCampaignId = null;
let latestProspectingRunId = localStorage.getItem("nexus_last_run_id") || null;
let latestProspectingOrchestration = null;
let latestCrmPreview = null;
let latestDiscardedResults = [];

function _saveRunId(id) {
    latestProspectingRunId = id;
    if (id) localStorage.setItem("nexus_last_run_id", id);
}
let latestProspectingResults = [];

function humanizeVertical(value) {
    const raw = String(value ?? '').trim();
    const labels = {
        asesoria: 'Asesorias',
        salud: 'Salud / Clinicas',
        inmobiliaria: 'Inmobiliarias',
        public_administration: 'Adm. publica',
        restaurants: 'Restaurantes',
        custom: 'Custom',
    };
    if (labels[raw]) return labels[raw];
    return raw
        .replaceAll('_', ' ')
        .replaceAll('-', ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/\b\w/g, (char) => char.toUpperCase()) || 'Custom';
}

function ensureSelectOption(selectId, value, label = null) {
    const el = document.getElementById(selectId);
    if (!el || !value) return;
    let option = [...el.options].find((item) => item.value === value);
    if (!option) {
        option = document.createElement('option');
        option.value = value;
        option.textContent = label || humanizeVertical(value);
        el.appendChild(option);
    }
    el.value = value;
}

// ── Sugerencias de chips por vertical ────────────────────────────────────────

const MUST_HAVE_SUGGESTIONS = {
    asesoria:             ["Email directo", "Web propia", "Telefono", "CIF visible", "LinkedIn"],
    salud:                ["Email directo", "Web propia", "Telefono", "Direccion fisica", "Horario publicado"],
    inmobiliaria:         ["Email directo", "Web propia", "Portal propio", "Direccion fisica", "Horario publicado"],
    restaurants:          ["Web propia", "Carta online", "Reservas online", "Telefono", "Google Maps"],
    public_administration:["Email institucional", "Web .gob/.es", "Nombre responsable", "Telefono", "Direccion"],
    custom:               ["Email directo", "Web propia", "Telefono", "Direccion", "Redes sociales"],
};

const NICE_TO_HAVE_SUGGESTIONS = {
    asesoria:             ["Mas de 5 empleados", "Redes sociales activas", "Blog / noticias", "Software propio", "Clientes publicados"],
    salud:                ["Resenas positivas", "Google Maps activo", "Especialidades visibles", "Equipo visible", "Horario publicado"],
    inmobiliaria:         ["Gestion vacacional", "CRM visible", "App movil", "Virtual tours", "Buenas resenas Google"],
    restaurants:          ["Grupos / eventos", "Terraza exterior", "Delivery propio", "Menu del dia online", "Buenas resenas"],
    public_administration:["Convocatorias TIC recientes", "Plan digital visible", "Contacto IT directo", "Sede electronica", "Presupuesto digital"],
    custom:               ["Redes sociales activas", "Blog / noticias", "App movil", "Resenas positivas", "Equipo visible"],
};

const CRM_TAG_OPTIONS = ["nexus-lead", "premium", "cold", "seguimiento", "automato", "assets", "q3-2026", "toledo", "madrid"];

// ── Chip utilities ────────────────────────────────────────────────────────────

function renderChips(containerId, options, preSelected = []) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = options.map((label) => {
        const selected = preSelected.includes(label) ? " is-selected" : "";
        return `<label class="chip-option${selected}"><input type="checkbox"${selected ? " checked" : ""}><span>${escapeHtml(label)}</span></label>`;
    }).join("");
    container.querySelectorAll(".chip-option").forEach((chip) => {
        chip.addEventListener("click", (e) => {
            e.preventDefault();
            chip.classList.toggle("is-selected");
            const cb = chip.querySelector("input[type=checkbox]");
            if (cb) cb.checked = chip.classList.contains("is-selected");
        });
    });
}

function getSelectedChips(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return [];
    return [...container.querySelectorAll(".chip-option.is-selected span")].map((el) => el.textContent.trim());
}

function initChips(vertical = "asesoria") {
    renderChips("mustHaveChips", MUST_HAVE_SUGGESTIONS[vertical] || MUST_HAVE_SUGGESTIONS.custom);
    renderChips("niceToHaveChips", NICE_TO_HAVE_SUGGESTIONS[vertical] || NICE_TO_HAVE_SUGGESTIONS.custom);
    renderChips("crmTagsChips", CRM_TAG_OPTIONS);
}

// ── Resumen de busqueda ───────────────────────────────────────────────────────

function showSearchSummary(brief) {
    const summary = document.getElementById("searchSummary");
    if (!summary) return;
    const verticalLabels = {
        asesoria: "Asesorias", salud: "Salud / Clinicas", inmobiliaria: "Inmobiliarias",
        public_administration: "Admon. publica", restaurants: "Restaurantes", custom: "Custom",
    };
    const parts = [
        humanizeVertical(brief.vertical),
        [brief.city, brief.province].filter(Boolean).join(", "),
        brief.desired_count ? `${brief.desired_count} leads` : "",
        brief.represented_by === "automato" ? "Automato" : "Assets",
    ].filter(Boolean);
    summary.innerHTML = `
        <span class="search-summary-text">${parts.map(escapeHtml).join(" · ")}</span>
        <button class="search-summary-edit" type="button" id="summaryEditBtn">editar parametros</button>
    `;
    summary.classList.remove("hidden-btn");
    document.getElementById("summaryEditBtn")?.addEventListener("click", expandParams);
}

function expandParams() {
    document.getElementById("prospectingParamsBlock")?.classList.remove("hidden-btn");
    document.getElementById("searchSummary")?.classList.add("hidden-btn");
}

// ── Panel de interpretación IA ────────────────────────────────────────────────

function renderInterpretation(brief, orchestration = null) {
    const output = document.getElementById("aiInterpretationOutput");
    if (!output) return;
    const verticalLabels = {
        asesoria: "Asesorías / Gestorías", salud: "Clínicas / Salud", inmobiliaria: "Inmobiliarias",
        public_administration: "Adm. pública", restaurants: "Restaurantes", custom: "Custom",
    };
    const brandLabels = { assets: "Assets Consultores", automato: "Automato", other: "Otra" };
    const joinOrDash = (value) => {
        if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
        if (typeof value === "string") return value.trim() || "—";
        return value ? String(value) : "—";
    };
    const rows = [
        ["Vertical",   humanizeVertical(brief.vertical) || "—"],
        ["Ciudad",     brief.city || "⚠ NO DETECTADA"],
        ["Provincia",  brief.province || "—"],
        ["Región",     brief.region || "—"],
        ["Objetivo",   brief.target_description || "—"],
        ["Must have",  joinOrDash(brief.must_have)],
        ["Nice to have", joinOrDash(brief.nice_to_have)],
        ["Excluir",    joinOrDash(brief.exclude)],
        ["CRM tags",   joinOrDash(brief.crm_tags)],
        ["Resultados", String(brief.desired_count ?? 20)],
        ["Score mín.", String(brief.minimum_score ?? 40)],
        ["Marca",      brandLabels[brief.represented_by] || brief.represented_by || "—"],
        ["Modo",       brief.dry_run !== false ? "Solo validación" : "Lanzamiento real"],
    ];
    if (brief.vertical_created) rows.push(["Vertical creada", "Sí, se ha registrado como nueva opción"]);
    const sourceSummary = orchestration?.source_plan?.summary;
    if (sourceSummary) rows.push(["Fuentes", sourceSummary]);
    if (brief._fallback) rows.push(["Aviso", "Interpretado por reglas (LLM no disponible)"]);
    output.className = "ai-interp-output";
    output.innerHTML = rows.map(([label, value]) => {
        const warn = value.startsWith("⚠") ? " ai-interp-warn" : "";
        return `<div class="ai-interp-row${warn}"><span class="ai-interp-label">${escapeHtml(label)}</span><span class="ai-interp-value">${escapeHtml(value)}</span></div>`;
    }).join("");
}

// ── HTTP helper ───────────────────────────────────────────────────────────────

async function requestJson(url, options = {}) {
    const response = await fetch(url, {
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        ...options,
    });
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || `HTTP ${response.status}`);
    }
    return data;
}

function renderFeed(targetId, items, mapper, emptyMessage) {
    const node = document.getElementById(targetId);
    if (!node) return;
    if (!items.length) {
        node.innerHTML = `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
        return;
    }
    node.innerHTML = items.map(mapper).join("");
}

function statusClass(value) {
    if (value === "up" || value === "accepted" || value === "completed") return "up";
    if (value === "degraded" || value === "running" || value === "searching" || value === "extracting" || value === "validating" || value === "scoring" || value === "pending" || value === "planned" || value === "partial") return "degraded";
    return "down";
}

function summarizeEventType(eventType) {
    const lookup = {
        email_preview: "Preview de email",
        email_sent: "Email enviado",
        launch_outreach: "Campana lanzada",
        sync_campaign_to_crm: "Sync CRM",
        ingest_mail_into_crm: "Correo al CRM",
    };
    return lookup[eventType] || eventType || "evento";
}

function renderOutreachStatus(payload) {
    const account = payload.account || {};
    const smtp = account.smtp || {};
    const imap = account.imap || {};
    const modeBadge = document.getElementById("outreachModeBadge");
    const accountLabel = document.getElementById("outreachAccountLabel");
    const sentToday = document.getElementById("outreachSentToday");
    const campaigns = document.getElementById("outreachCampaignCount");
    const capInput = document.getElementById("outreachDailyCap");

    if (modeBadge) {
        const liveReady = payload.enabled && smtp.configured && imap.configured;
        modeBadge.textContent = liveReady ? "listo" : "dry-run";
        modeBadge.classList.remove("up", "down", "degraded");
        modeBadge.classList.add(liveReady ? "up" : "degraded");
    }
    if (accountLabel) accountLabel.textContent = account.email || "sin cuenta";
    if (sentToday) sentToday.textContent = String(payload.sent_today ?? 0);
    if (campaigns) campaigns.textContent = String(payload.campaigns_total ?? 0);
    if (capInput && !capInput.dataset.userTouched) {
        capInput.value = String(payload.daily_cap_default ?? 20);
    }
}

function scoreClass(score) {
    const n = Number(score ?? 0);
    if (n >= 70) return "score-high";
    if (n >= 45) return "score-mid";
    return "score-low";
}

// ── Resultados de prospección ─────────────────────────────────────────────────

function renderProspectingResults(items) {
    const tbody = document.getElementById("prospectingResultsBody");
    if (!tbody) return;

    if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-table">Run completado · 0 resultados con este score minimo.</td></tr>';
    } else {
        tbody.innerHTML = items.map((item) => {
            const meta = [item.city || item.province, item.vertical].filter(Boolean).join(" · ");
            const contactLines = [
                item.email ? `<a href="mailto:${escapeHtml(item.email)}" class="contact-link">${escapeHtml(item.email)}</a>` : "",
                item.phone ? `<span class="contact-phone">${escapeHtml(item.phone)}</span>` : "",
            ].filter(Boolean).join("");
            const nameCell = item.website
                ? `<a href="${escapeHtml(item.website)}" target="_blank" rel="noreferrer" class="prospect-name-link">${escapeHtml(item.name || "")}</a>`
                : escapeHtml(item.name || "");
            const reviewState = item.crm_duplicate
                ? '<span class="pill pill-dup">duplicado</span>'
                : item.crm_ready
                    ? '<span class="review-ready">listo para CRM</span>'
                    : '<span class="review-needs">requiere revision</span>';
            return `<tr data-result-id="${escapeHtml(item.result_id)}">
                <td class="prospect-name-cell">
                    <div class="prospect-name">${nameCell}</div>
                    ${meta ? `<div class="prospect-meta">${escapeHtml(meta)}</div>` : ""}
                    <div class="prospect-meta">${escapeHtml(item.source || "web")} · ${escapeHtml(item.reason || "")}</div>
                </td>
                <td class="prospect-score-cell">
                    <span class="pill ${scoreClass(item.score)}">${escapeHtml(String(item.score ?? 0))}</span>
                    <div class="prospect-priority">${escapeHtml(item.priority || "")}</div>
                </td>
                <td class="prospect-contact-cell">${contactLines || '<span class="muted-text">sin contacto</span>'}</td>
                <td>${reviewState}</td>
                <td class="prospecting-actions-cell">
                    <button class="btn btn-small btn-secondary" type="button" data-action="evidence" data-result-id="${escapeHtml(item.result_id)}">Info</button>
                    <button class="btn btn-small" type="button" data-action="preview-crm" data-result-id="${escapeHtml(item.result_id)}">Preview CRM</button>
                </td>
            </tr>`;
        }).join("");
    }

    // Scroll al inicio de la tabla en el panel derecho
    requestAnimationFrame(() => {
        const tableWrap = document.querySelector(".prospecting-table-wrap");
        const scrollPanel = document.querySelector(".results-panel");
        if (!tableWrap || !scrollPanel) return;
        const panelRect = scrollPanel.getBoundingClientRect();
        const tableRect = tableWrap.getBoundingClientRect();
        scrollPanel.scrollTop = Math.max(0, scrollPanel.scrollTop + (tableRect.top - panelRect.top) - 16);
    });
}

function renderDiscardedResults(items) {
    latestDiscardedResults = items || [];
    const node = document.getElementById("discardedResultsList");
    if (!node) return;
    if (!latestDiscardedResults.length) {
        node.innerHTML = '<div class="empty-state">No hay descartados relevantes en este run.</div>';
        return;
    }
    node.innerHTML = latestDiscardedResults.map((item) => {
        const reason = item.discard_reason_label || item.discard_reason || "Descartado";
        const meta = [item.city, item.province, item.source || "fuente", item.priority].filter(Boolean).join(" · ");
        const source = item.website || item.source_url || "";
        return `
            <article class="discarded-item">
                <div class="discarded-item-head">
                    <strong>${escapeHtml(item.name || source || "Lead descartado")}</strong>
                    <span class="pill pill-discarded">${escapeHtml(reason)}</span>
                </div>
                ${meta ? `<div class="discarded-item-meta">${escapeHtml(meta)}</div>` : ""}
                ${source ? `<div class="discarded-item-source">${escapeHtml(source)}</div>` : ""}
            </article>
        `;
    }).join("");
}

function renderProspectingSummary(run) {
    const badge = document.getElementById("prospectingRunBadge");
    const latestRun = document.getElementById("prospectingLatestRun");
    const resultCount = document.getElementById("prospectingResultCount");
    const discardedCount = document.getElementById("prospectingDiscardedCount");
    const message = document.getElementById("prospectingResultMessage");
    if (badge) {
        badge.textContent = run.status || "idle";
        badge.classList.remove("up", "down", "degraded");
        badge.classList.add(statusClass(run.status));
    }
    if (latestRun) latestRun.textContent = run.run_id || "sin ejecutar";
    if (resultCount) resultCount.textContent = String((run.results || []).length);
    if (discardedCount) discardedCount.textContent = String((run.discarded || []).length);
    if (message) {
        const summary = run.summary || {};
        const queries = (run.queries || []).slice(0, 2).join(" | ");
        message.textContent = `Run ${run.run_id || ""}: ${summary.usable_results ?? 0} revisables - ${summary.crm_ready ?? 0} listos para CRM - ${summary.discarded ?? 0} descartados - ${summary.duplicates ?? 0} duplicados.${queries ? ` Queries: ${queries}` : ""}`;
    }
}

function renderCrmPreview(preview, title = "Preview CRM") {
    latestCrmPreview = preview || null;
    const panel = document.getElementById("crmPreviewPanel");
    const confirmBtn = document.getElementById("confirmCrmPushBtn");
    if (!panel) return;

    if (!preview || !Array.isArray(preview.results) || !preview.results.length) {
        panel.innerHTML = "";
        panel.classList.add("hidden-btn");
        if (confirmBtn) confirmBtn.disabled = true;
        return;
    }

    const accepted = preview.results.filter((item) => item.status === "accepted");
    const blocked = preview.results.filter((item) => item.status !== "accepted");
    const compactItems = preview.results.slice(0, 3);
    panel.innerHTML = `
        <div class="crm-preview-head">
            <div>
                <p class="eyebrow eyebrow-tight">Revision CRM</p>
                <h3>${escapeHtml(title)}</h3>
            </div>
            <div class="crm-preview-meta">
                <span class="pill">${escapeHtml(`${accepted.length} listos`)}</span>
                <span class="pill">${escapeHtml(`${blocked.length} bloqueados`)}</span>
                <span class="pill">${escapeHtml(`${preview.results.length} total`)}</span>
            </div>
        </div>
        <div class="crm-preview-list">
            ${compactItems.map((item) => `
                <article class="crm-preview-item">
                    <strong>${escapeHtml(item.company_name || item.company_payload?.name || item.result_id || "Lead")}</strong>
                    <span>${escapeHtml((item.status === "accepted" ? "Listo" : "Revision") + (item.company_payload?.domain || item.pipeline_payload?.contact_email ? " · " + (item.company_payload?.domain || item.pipeline_payload?.contact_email) : ""))}</span>
                </article>
            `).join("")}
            ${preview.results.length > compactItems.length ? `<div class="empty-state crm-preview-more">+${preview.results.length - compactItems.length} más</div>` : ""}
        </div>
    `;
    panel.classList.remove("hidden-btn");
    if (confirmBtn) confirmBtn.disabled = accepted.length === 0;
}

// ── Carga de datos ────────────────────────────────────────────────────────────

async function loadOutreach() {
    try {
        const [status, events] = await Promise.all([
            requestJson("/api/nexus/outreach/status"),
            requestJson("/api/nexus/outreach/events"),
        ]);
        renderOutreachStatus(status);
        const campaigns = status.recent_campaigns || [];
        latestOutreachCampaignId = campaigns.length ? campaigns[0].campaign_id : latestOutreachCampaignId;
        renderFeed(
            "outreachFeed",
            events.events || [],
            (entry) => `
                <article class="feed-card">
                    <h3>${escapeHtml(summarizeEventType(entry.event_type))}</h3>
                    <p>${escapeHtml((entry.company || entry.recipient_email || "destinatario") + " - " + (entry.subject || "sin asunto"))}</p>
                    <div class="feed-meta">
                        <span class="pill">${escapeHtml(entry.dry_run ? "dry-run" : "live")}</span>
                        <span class="pill">${escapeHtml(entry.delivery_status || "pending")}</span>
                        <span class="pill">${escapeHtml(`paso ${Number(entry.step_index || 0) + 1}`)}</span>
                    </div>
                </article>
            `,
            "Todavia no hay actividad de outreach."
        );
    } catch (error) {
        renderFeed("outreachFeed", [], () => "", `No se pudo cargar outreach: ${error.message}`);
    }
}

async function loadCRMStatus() {
    const badge = document.getElementById("crmStatusBadge");
    const source = document.getElementById("crmSourceLabel");
    const pending = document.getElementById("crmPendingProspects");
    const campaigns = document.getElementById("crmCampaignCount");
    try {
        const status = await requestJson("/api/nexus/crm/status");
        const connector = status.connector || {};
        if (badge) {
            badge.textContent = connector.status || "pendiente";
            badge.classList.remove("up", "down", "degraded");
            badge.classList.add(statusClass(connector.status));
        }
        if (source) source.textContent = status.provider || "assets-web-api";
        if (pending) pending.textContent = String(status.pending_prospects ?? 0);
        if (campaigns) campaigns.textContent = String(status.campaigns_total ?? 0);
    } catch (error) {
        if (badge) {
            badge.textContent = "error";
            badge.classList.remove("up", "degraded");
            badge.classList.add("down");
        }
        if (source) source.textContent = error.message;
    }
}

async function loadAuditActivity() {
    try {
        const data = await requestJson("/api/nexus/audit");
        const entries = (data.entries || []).filter((entry) =>
            ["launch_outreach", "sync_campaign_to_crm", "ingest_mail_into_crm"].includes(entry.action)
        );
        renderFeed(
            "activityFeed",
            entries,
            (entry) => `
                <article class="feed-card">
                    <h3>${escapeHtml(entry.action)}</h3>
                    <p>${escapeHtml((entry.details || {}).message_preview || (entry.details || {}).campaign_id || "Actividad comercial registrada")}</p>
                    <div class="feed-meta">
                        <span class="pill">${escapeHtml(entry.status || "accepted")}</span>
                        <span class="pill">${escapeHtml(entry.actor || "nexus")}</span>
                    </div>
                </article>
            `,
            "Todavia no hay actividad comercial registrada."
        );
    } catch (error) {
        renderFeed("activityFeed", [], () => "", `No se pudo cargar la actividad comercial: ${error.message}`);
    }
}

async function loadProspecting(runId = latestProspectingRunId) {
    try {
        if (!runId) {
        latestProspectingOrchestration = null;
        renderFeed("prospectingFeed", [], () => "", "Todavia no hay runs de prospeccion.");
        renderProspectingResults([]);
        renderDiscardedResults([]);
        renderCrmPreview(null);
            return;
        }
        const run = await requestJson(`/api/nexus/prospecting/runs/${encodeURIComponent(runId)}`);
        _saveRunId(run.run_id);
        latestProspectingOrchestration = run.orchestration || null;
        latestProspectingResults = run.results || [];
        renderProspectingSummary(run);
        renderProspectingResults(latestProspectingResults);
        renderDiscardedResults(run.discarded || []);
        loadRunLogs();
        renderFeed(
            "prospectingFeed",
            latestProspectingResults,
            (entry) => `
                <article class="feed-card">
                    <h3>${escapeHtml(entry.name || "Prospecto")}</h3>
                    <p>${escapeHtml((entry.email || entry.phone || "sin canal usable") + " - " + (entry.website || "sin web"))}</p>
                    <div class="feed-meta">
                        <span class="pill">${escapeHtml(`score ${entry.score ?? 0}`)}</span>
                        <span class="pill">${escapeHtml(entry.priority || "pendiente")}</span>
                        <span class="pill">${escapeHtml(entry.crm_duplicate ? "duplicado" : (entry.crm_state || "pendiente"))}</span>
                    </div>
                </article>
            `,
            "Todavia no hay resultados utiles."
        );
    } catch (error) {
        const message = document.getElementById("prospectingResultMessage");
        if (message) message.textContent = `No se pudo cargar la prospeccion: ${error.message}`;
    }
}

// ── Llenar formulario desde brief ─────────────────────────────────────────────

function fillFormFromBrief(brief) {
    const set = (id, value) => { const el = document.getElementById(id); if (el && value !== undefined && value !== null) el.value = String(value); };
    ensureSelectOption("prospectingVertical", brief.vertical);
    ensureSelectOption("prospectingRepresentedBy", brief.represented_by);
    set("prospectingTargetDescription", brief.target_description);
    set("prospectingCity", brief.city);
    set("prospectingProvince", brief.province);
    set("prospectingRegion", brief.region);
    set("prospectingDesiredCount", brief.desired_count);
    set("prospectingMinimumScore", brief.minimum_score);
    const dryRunEl = document.getElementById("prospectingDryRun");
    if (dryRunEl) dryRunEl.checked = brief.dry_run !== false;

    document.getElementById("prospectingParamsBlock")?.classList.add("hidden-btn");

    const vertical = brief.vertical || "asesoria";
    renderChips("mustHaveChips", MUST_HAVE_SUGGESTIONS[vertical] || MUST_HAVE_SUGGESTIONS.custom, brief.must_have || []);
    renderChips("niceToHaveChips", NICE_TO_HAVE_SUGGESTIONS[vertical] || NICE_TO_HAVE_SUGGESTIONS.custom, brief.nice_to_have || []);
    renderChips("crmTagsChips", CRM_TAG_OPTIONS, brief.crm_tags || []);
}

// ── Motor conversacional ──────────────────────────────────────────────────────

let _chatHistory = [];
let _chatActive = false;

function _renderChatLog() {
    const output = document.getElementById("aiInterpretationOutput");
    if (!output) return;
    if (!_chatHistory.length) {
        output.className = "ai-interp-output empty-state";
        output.innerHTML = "Interpreta una busqueda para ver el desglose.";
        return;
    }
    output.className = "ai-interp-output chat-log-mode";
    output.innerHTML = _chatHistory.map((msg) => {
        const cls = msg.role === "user" ? "chat-bubble chat-bubble-user" : "chat-bubble chat-bubble-ai";
        return `<div class="${cls}"><p>${escapeHtml(msg.content)}</p></div>`;
    }).join("");
    output.scrollTop = output.scrollHeight;
}

function resetChat() {
    _chatHistory = [];
    _chatActive = false;
    const btn = document.getElementById("interpretBriefBtn");
    if (btn) { btn.textContent = "Interpretar con IA"; btn.classList.remove("btn-secondary"); }
    const textarea = document.getElementById("aiBriefText");
    if (textarea) { textarea.placeholder = "Ej: busca asesorias fiscales en Toledo, unas 20, para Automato"; }
    const statusEl = document.getElementById("interpretStatus");
    if (statusEl) { statusEl.textContent = ""; statusEl.className = "interpret-status"; }
    const resetLink = document.getElementById("chatResetBtn");
    if (resetLink) resetLink.classList.add("hidden-btn");
    _renderChatLog();
}

async function sendChatMessage() {
    const textarea = document.getElementById("aiBriefText");
    const text = textarea?.value.trim();
    const statusEl = document.getElementById("interpretStatus");
    const btn = document.getElementById("interpretBriefBtn");

    if (!text) {
        if (statusEl) { statusEl.textContent = "Escribe algo primero."; statusEl.className = "interpret-status error"; }
        return;
    }

    if (btn) btn.disabled = true;
    if (statusEl) { statusEl.textContent = "Pensando..."; statusEl.className = "interpret-status loading"; }
    if (textarea) textarea.value = "";

    const historyToSend = [..._chatHistory];
    _chatHistory.push({ role: "user", content: text });
    _renderChatLog();

    try {
        const response = await requestJson("/api/nexus/prospecting/chat", {
            method: "POST",
            body: JSON.stringify({ message: text, history: historyToSend }),
        });

        const reply = response.reply || "";
        const status = response.status || "clarifying";
        const brief = response.brief;

        _chatHistory.push({ role: "assistant", content: reply });
        _renderChatLog();

        if (status === "ready" && brief) {
            _chatActive = false;
            latestProspectingOrchestration = null;
            fillFormFromBrief(brief);
            showSearchSummary(brief);
            renderInterpretation(brief);
            if (btn) { btn.textContent = "Interpretar con IA"; btn.classList.remove("btn-secondary"); }
            if (textarea) textarea.placeholder = "Ej: busca asesorias fiscales en Toledo, unas 20, para Automato";
            if (statusEl) { statusEl.textContent = "Listo — revisa y lanza"; statusEl.className = "interpret-status ok"; }
        } else {
            _chatActive = true;
            if (btn) { btn.textContent = "Responder"; btn.classList.add("btn-secondary"); }
            if (textarea) textarea.placeholder = "Escribe tu respuesta...";
            document.getElementById("chatResetBtn")?.classList.remove("hidden-btn");
            if (statusEl) { statusEl.textContent = ""; statusEl.className = "interpret-status"; }
        }
    } catch (error) {
        _chatHistory.pop(); // deshace el push del mensaje del usuario
        _renderChatLog();
        if (statusEl) { statusEl.textContent = `Error: ${error.message}`; statusEl.className = "interpret-status error"; }
    } finally {
        if (btn) btn.disabled = false;
    }
}

// ── Interpretar con IA (legado — sin historial, un solo turno) ────────────────

async function interpretBrief() {
    const text = document.getElementById("aiBriefText")?.value.trim();
    const statusEl = document.getElementById("interpretStatus");
    const btn = document.getElementById("interpretBriefBtn");

    if (!text) {
        if (statusEl) { statusEl.textContent = "Escribe algo primero."; statusEl.className = "interpret-status error"; }
        return;
    }

    if (btn) btn.disabled = true;
    if (statusEl) { statusEl.textContent = "Interpretando..."; statusEl.className = "interpret-status loading"; }

    try {
        const response = await requestJson("/api/nexus/prospecting/interpret", {
            method: "POST",
            body: JSON.stringify({ text }),
        });
        const brief = response.brief || {};
        latestProspectingOrchestration = response.orchestration || null;

        fillFormFromBrief(brief);
        showSearchSummary(brief);
        renderInterpretation(brief, latestProspectingOrchestration);

        const noCityWarn = !brief.city && !brief.province && !brief.region;
        if (statusEl) {
            statusEl.textContent = noCityWarn ? "⚠ Sin ciudad detectada — revisa el panel derecho" : "Listo";
            statusEl.className = noCityWarn ? "interpret-status error" : "interpret-status ok";
        }
    } catch (error) {
        if (statusEl) { statusEl.textContent = `Error: ${error.message}`; statusEl.className = "interpret-status error"; }
    } finally {
        if (btn) btn.disabled = false;
    }
}

// ── Lanzar prospección ────────────────────────────────────────────────────────

function splitCsvList(value) {
    return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function _setBadge(text, cls) {
    const badge = document.getElementById("prospectingRunBadge");
    if (!badge) return;
    badge.textContent = text;
    badge.classList.remove("up", "down", "degraded");
    badge.classList.add(cls);
}

function _showError(message, text) {
    if (!message) return;
    message.textContent = text;
    message.classList.add("run-error");
    message.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setTimeout(() => message.classList.remove("run-error"), 3000);
}

async function runProspecting(event) {
    event?.preventDefault();
    const payload = {
        vertical:            document.getElementById("prospectingVertical")?.value || "asesoria",
        target_description:  document.getElementById("prospectingTargetDescription")?.value.trim() || "",
        city:                document.getElementById("prospectingCity")?.value.trim() || "",
        province:            document.getElementById("prospectingProvince")?.value.trim() || "",
        region:              document.getElementById("prospectingRegion")?.value.trim() || "",
        desired_count:       Number(document.getElementById("prospectingDesiredCount")?.value || 20),
        minimum_score:       Number(document.getElementById("prospectingMinimumScore")?.value || 40),
        must_have:           getSelectedChips("mustHaveChips"),
        nice_to_have:        getSelectedChips("niceToHaveChips"),
        exclude:             splitCsvList(document.getElementById("prospectingExclude")?.value || ""),
        crm_tags:            getSelectedChips("crmTagsChips"),
        dry_run:             document.getElementById("prospectingDryRun")?.checked !== false,
        async_mode:          false,
        represented_by:      document.getElementById("prospectingRepresentedBy")?.value || "assets",
    };
    const message = document.getElementById("prospectingResultMessage");
    const btn = document.getElementById("runProspectingBtn");

    if (!payload.city && !payload.province && !payload.region) {
        _setBadge("error", "down");
        // Error inline junto al botón
        const launchErr = document.getElementById("launchErrorMsg");
        if (launchErr) {
            launchErr.classList.remove("hidden-btn");
            setTimeout(() => launchErr.classList.add("hidden-btn"), 6000);
        }
        // Expandir params para que el usuario rellene ciudad
        document.getElementById("prospectingParamsBlock")?.classList.remove("hidden-btn");
        document.getElementById("searchSummary")?.classList.add("hidden-btn");
        setTimeout(() => document.getElementById("prospectingCity")?.focus(), 80);
        // Actualizar también el mensaje del panel derecho
        if (message) {
            message.textContent = "Sin ubicacion — rellena Ciudad en los parametros de abajo.";
            message.classList.remove("empty-state");
        }
        return;
    }

    _setBadge("prospecting", "degraded");
    if (btn) { btn.disabled = true; btn.textContent = "Prospectando..."; }
    if (message) { message.textContent = "Buscando empresas..."; message.classList.remove("run-error"); }

    // Contador de tiempo visible mientras el run corre (el endpoint es síncrono)
    let elapsed = 0;
    const ticker = setInterval(() => {
        elapsed++;
        if (message) message.textContent = `Buscando empresas... ${elapsed}s`;
    }, 1000);

    try {
        const response = await requestJson("/api/nexus/prospecting/run", {
            method: "POST",
            body: JSON.stringify(payload),
        });
        clearInterval(ticker);
        _saveRunId(response.run_id);
        await loadProspecting(response.run_id);
        await checkApiBudget();
    } catch (error) {
        clearInterval(ticker);
        _setBadge("error", "down");
        _showError(message, `Error al prospectar: ${error.message}`);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = "Lanzar prospeccion"; }
    }
}

async function resumeProspecting() {
    const message = document.getElementById("prospectingResultMessage");
    if (!latestProspectingRunId) {
        if (message) message.textContent = "Todavia no hay ningun run para reanudar.";
        return;
    }
    try {
        const response = await requestJson(`/api/nexus/prospecting/runs/${encodeURIComponent(latestProspectingRunId)}/resume`, {
            method: "POST",
        });
        _saveRunId(response.run_id);
        await loadProspecting(response.run_id);
    } catch (error) {
        if (message) message.textContent = `No se pudo reanudar el run: ${error.message}`;
    }
}

function _setCrmFeedback(text, isError = false) {
    const fb = document.getElementById("crmPushFeedback");
    if (!fb) return;
    fb.textContent = text;
    fb.className = isError ? "crm-push-feedback crm-push-error" : "crm-push-feedback crm-push-ok";
    if (text) setTimeout(() => { fb.textContent = ""; fb.className = "crm-push-feedback"; }, 5000);
}

async function pushValidResults() {
    const btn = document.getElementById("pushValidProspectsBtn");
    if (!latestProspectingRunId) {
        _setCrmFeedback("Sin run activo — lanza una prospeccion primero.", true);
        return;
    }
    if (btn) { btn.disabled = true; btn.textContent = "Preparando preview..."; }
    _setCrmFeedback("Generando preview CRM...");
    try {
        const response = await requestJson("/api/nexus/prospecting/push-valid-to-crm", {
            method: "POST",
            body: JSON.stringify({ run_id: latestProspectingRunId, dry_run: true }),
        });
        renderCrmPreview(response, "Preview lote CRM");
        const accepted = (response.results || []).filter((item) => item.status === "accepted").length;
        _setCrmFeedback(accepted > 0 ? `${accepted} leads listos para revisar antes de CRM.` : "No hay leads listos para CRM en este run.", accepted === 0);
    } catch (error) {
        _setCrmFeedback(`Error: ${error.message}`, true);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = "Previsualizar lote CRM"; }
    }
}

async function confirmPushValidResults() {
    const btn = document.getElementById("confirmCrmPushBtn");
    if (!latestProspectingRunId) {
        _setCrmFeedback("Sin run activo â€” lanza una prospeccion primero.", true);
        return;
    }
    if (!latestCrmPreview || !(latestCrmPreview.results || []).some((item) => item.status === "accepted")) {
        _setCrmFeedback("Primero genera una preview CRM valida.", true);
        return;
    }
    if (btn) { btn.disabled = true; btn.textContent = "Confirmando..."; }
    _setCrmFeedback("Enviando lote al CRM...");
    try {
        const response = await requestJson("/api/nexus/prospecting/push-valid-to-crm", {
            method: "POST",
            body: JSON.stringify({ run_id: latestProspectingRunId, dry_run: false }),
        });
        const n = response.pushed_count ?? 0;
        renderCrmPreview(null);
        _setCrmFeedback(n > 0 ? `${n} leads enviados al CRM.` : "0 leads enviados al CRM.", n === 0);
        await loadProspecting(latestProspectingRunId);
    } catch (error) {
        _setCrmFeedback(`Error: ${error.message}`, true);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = "Confirmar envio CRM"; }
    }
}

async function pushSingleResult(resultId) {
    const message = document.getElementById("prospectingResultMessage");
    if (message) message.textContent = "Preparando preview CRM...";
    try {
        const response = await requestJson(`/api/nexus/prospecting/results/${encodeURIComponent(resultId)}/push-to-crm`, {
            method: "POST",
            body: JSON.stringify({ dry_run: true }),
        });
        renderCrmPreview({ results: [response] }, "Preview individual CRM");
        if (message) {
            message.textContent = response.message || "Preview CRM generada.";
        }
    } catch (error) {
        if (message) message.textContent = `No se pudo preparar el resultado: ${error.message}`;
    }
}

async function loadDiscarded() {
    const message = document.getElementById("prospectingResultMessage");
    if (!latestProspectingRunId) {
        if (message) message.textContent = "Todavia no hay descartados que mostrar.";
        return;
    }
    try {
        const payload = await requestJson(`/api/nexus/prospecting/discarded?run_id=${encodeURIComponent(latestProspectingRunId)}`);
        const discarded = payload.discarded || [];
        renderDiscardedResults(discarded);
        if (message) {
            message.textContent = discarded.length
                ? `${discarded.length} descartados cargados para revision.`
                : "No hay descartados en este run.";
        }
    } catch (error) {
        if (message) message.textContent = `No se pudieron cargar los descartados: ${error.message}`;
    }
}

async function checkApiBudget() {
    const banner = document.getElementById("apiBudgetBanner");
    if (!banner) return;
    try {
        const data = await requestJson("/api/nexus/prospecting/api-budget");
        const { calls, hard_limit, remaining, status } = data;

        if (status === "ok") {
            banner.className = "api-budget-banner hidden-btn";
            banner.innerHTML = "";
            return;
        }

        const pct = Math.min(100, Math.round((calls / hard_limit) * 100));
        const isBlocked = status === "blocked";
        const icon = isBlocked ? "🚫" : "⚠️";
        const title = isBlocked
            ? `PROSPECCIÓN BLOQUEADA — Límite mensual alcanzado (${calls}/${hard_limit} llamadas)`
            : `AVISO: ${calls} de ${hard_limit} llamadas a Google Places este mes`;
        const subtitle = isBlocked
            ? `Se han consumido todas las llamadas gratuitas. La prospección está desactivada hasta el mes siguiente.`
            : `Quedan ${remaining} llamadas. Límite de corte en ${hard_limit}.`;

        banner.innerHTML = `
            <span class="budget-banner-icon">${icon}</span>
            <span class="budget-banner-text">
                <strong>${title}</strong>
                ${subtitle}
            </span>
            <span class="budget-banner-bar">
                <span class="budget-banner-fill" style="width:${pct}%"></span>
            </span>
        `;
        banner.className = `api-budget-banner budget-${status}`;
    } catch (_) { /* silencioso */ }
}

async function loadRunLogs() {
    if (!latestProspectingRunId) return;
    const list = document.getElementById("prospectingLogsList");
    const count = document.getElementById("prospectingLogsCount");
    if (!list) return;
    try {
        const data = await requestJson(`/api/nexus/prospecting/runs/${encodeURIComponent(latestProspectingRunId)}/logs`);
        const logs = data.logs || [];
        if (count) count.textContent = String(logs.length);
        if (!logs.length) {
            list.innerHTML = '<div class="empty-state">Sin eventos registrados.</div>';
            return;
        }
        list.innerHTML = logs.map((entry) => {
            const ts = entry.ts ? new Date(entry.ts).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
            const dataStr = entry.data ? ` <span class="log-data">${escapeHtml(JSON.stringify(entry.data))}</span>` : "";
            return `<div class="log-entry log-${escapeHtml(entry.level || "info")}"><span class="log-ts">${escapeHtml(ts)}</span><span class="log-msg">${escapeHtml(entry.msg || "")}${dataStr}</span></div>`;
        }).join("");
        list.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        document.getElementById("prospectingLogsPanel")?.setAttribute("open", "");
    } catch (error) {
        if (list) list.innerHTML = `<div class="empty-state">Error cargando logs: ${escapeHtml(error.message)}</div>`;
    }
}

function showEvidence(resultId) {
    const result = latestProspectingResults.find((item) => item.result_id === resultId);
    const message = document.getElementById("prospectingResultMessage");
    if (!result || !message) return;

    const breakdown = result.score_breakdown || [];
    const earned = breakdown.filter(c => c.earned);
    const missed = breakdown.filter(c => !c.earned && c.points > 0);
    const penalties = breakdown.filter(c => c.points < 0 && c.earned);

    const breakdownHtml = breakdown.length ? `
        <div class="score-breakdown">
            <p class="breakdown-title"><strong>${escapeHtml(result.name || "")}</strong> — Score: ${escapeHtml(result.score ?? 0)} / 100 &nbsp; Prioridad: ${escapeHtml(result.priority || "")}</p>
            ${earned.length ? `<p class="breakdown-section-label">Criterios cumplidos</p>
            <ul class="breakdown-list">
                ${earned.map(c => `<li class="breakdown-ok"><span class="breakdown-pts">+${c.actual}</span> ${escapeHtml(c.label)}</li>`).join("")}
            </ul>` : ""}
            ${missed.length ? `<p class="breakdown-section-label">No cumplidos</p>
            <ul class="breakdown-list">
                ${missed.map(c => `<li class="breakdown-miss"><span class="breakdown-pts">+${c.points}</span> ${escapeHtml(c.label)}</li>`).join("")}
            </ul>` : ""}
            ${penalties.length ? `<p class="breakdown-section-label">Penalizaciones</p>
            <ul class="breakdown-list">
                ${penalties.map(c => `<li class="breakdown-penalty"><span class="breakdown-pts">${c.actual}</span> ${escapeHtml(c.label)}</li>`).join("")}
            </ul>` : ""}
        </div>` : "";

    const evidence = [result.source_url, ...(result.evidence_urls || [])].filter(Boolean);
    const evidenceHtml = evidence.length
        ? `<p class="breakdown-section-label">Fuentes</p>` + evidence.map(url => `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(url)}</a>`).join("<br>")
        : "";

    message.innerHTML = breakdownHtml + evidenceHtml || "No hay información adicional.";
    message.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ── Automatizaciones N8N ──────────────────────────────────────────────────────

async function loadAutomations() {
    const list = document.getElementById("automationsList");
    if (!list) return;
    try {
        const data = await requestJson("/api/nexus/automations");
        const items = data.automations || [];
        if (!items.length) {
            list.innerHTML = '<div class="empty-state">No hay automatizaciones configuradas.</div>';
            return;
        }
        list.innerHTML = items.map((item) => `
            <div class="automation-item" id="automation-${escapeHtml(item.id)}">
                <div class="automation-item-info">
                    <div class="automation-item-name">${escapeHtml(item.name)}</div>
                    <div class="automation-item-meta">${escapeHtml(item.description || "")}${item.last_run ? ` · Ultimo: ${escapeHtml(item.last_run)}` : ""}</div>
                </div>
                <button class="btn btn-small automation-trigger-btn" type="button"
                    data-automation-id="${escapeHtml(item.id)}">Disparar</button>
            </div>
        `).join("");
    } catch (_) {
        list.innerHTML = '<div class="empty-state">N8N no disponible.</div>';
    }
}

async function triggerAutomation(id) {
    const item = document.getElementById(`automation-${id}`);
    const btn = item?.querySelector(".automation-trigger-btn");
    if (btn) { btn.textContent = "Disparando..."; btn.classList.add("running"); }
    try {
        await requestJson(`/api/nexus/automations/${encodeURIComponent(id)}/trigger`, { method: "POST" });
        if (btn) { btn.textContent = "Enviado"; setTimeout(() => { btn.textContent = "Disparar"; btn.classList.remove("running"); }, 3000); }
    } catch (error) {
        if (btn) { btn.textContent = "Error"; btn.classList.remove("running"); setTimeout(() => { btn.textContent = "Disparar"; }, 2000); }
    }
}

async function launchOutreach(event) {
    event.preventDefault();
    const payload = {
        campaign_name: document.getElementById("outreachCampaignName")?.value.trim(),
        proposition: document.getElementById("outreachProposition")?.value.trim(),
        cta: document.getElementById("outreachCta")?.value.trim(),
        audience_hint: document.getElementById("outreachAudience")?.value.trim(),
        max_daily_send: Number(document.getElementById("outreachDailyCap")?.value || 20),
        dry_run: document.getElementById("outreachDryRun")?.checked !== false,
        csv_text: document.getElementById("outreachCsv")?.value.trim(),
    };
    const resultNode = document.getElementById("outreachLaunchResult");
    if (!payload.campaign_name || !payload.proposition || !payload.csv_text) {
        if (resultNode) resultNode.textContent = "Faltan datos: campana, propuesta y CSV.";
        return;
    }
    if (resultNode) resultNode.textContent = "Lanzando campana...";
    try {
        const response = await requestJson("/api/nexus/outreach/launch", {
            method: "POST",
            body: JSON.stringify(payload),
        });
        if (resultNode) {
            resultNode.innerHTML = `<strong>${escapeHtml(response.campaign_id)}</strong><br>${escapeHtml(`${response.executed_count} correos preparados de ${response.total_prospects} prospectos`)}`;
        }
        latestOutreachCampaignId = response.campaign_id;
        await loadOutreach();
        await loadCRMStatus();
        await loadAuditActivity();
    } catch (error) {
        if (resultNode) resultNode.textContent = `Error al lanzar outreach: ${error.message}`;
    }
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
    // Init chips con vertical por defecto
    initChips("asesoria");

    // Cambio de vertical recarga los chips
    document.getElementById("prospectingVertical")?.addEventListener("change", (e) => {
        const vertical = e.target.value;
        renderChips("mustHaveChips", MUST_HAVE_SUGGESTIONS[vertical] || MUST_HAVE_SUGGESTIONS.custom);
        renderChips("niceToHaveChips", NICE_TO_HAVE_SUGGESTIONS[vertical] || NICE_TO_HAVE_SUGGESTIONS.custom);
    });

    document.getElementById("interpretBriefBtn")?.addEventListener("click", sendChatMessage);
    document.getElementById("chatResetBtn")?.addEventListener("click", resetChat);
    document.getElementById("aiBriefText")?.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) sendChatMessage();
    });
    document.getElementById("runProspectingBtn")?.addEventListener("click", runProspecting);
    document.getElementById("refreshProspectingBtn")?.addEventListener("click", () => loadProspecting());
    document.getElementById("pushValidProspectsBtn")?.addEventListener("click", pushValidResults);
    document.getElementById("confirmCrmPushBtn")?.addEventListener("click", confirmPushValidResults);
    document.getElementById("loadDiscardedBtn")?.addEventListener("click", loadDiscarded);
    document.getElementById("resumeProspectingBtn")?.addEventListener("click", resumeProspecting);
    document.getElementById("refreshAutomationsBtn")?.addEventListener("click", loadAutomations);
    document.getElementById("automationsList")?.addEventListener("click", (e) => {
        const btn = e.target.closest(".automation-trigger-btn");
        if (btn) triggerAutomation(btn.dataset.automationId);
    });
    document.getElementById("outreachForm")?.addEventListener("submit", launchOutreach);
    document.getElementById("outreachDailyCap")?.addEventListener("input", (event) => {
        if (event.target instanceof HTMLInputElement) event.target.dataset.userTouched = "true";
    });
    document.getElementById("prospectingResultsBody")?.addEventListener("click", async (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        const action = target.dataset.action;
        const resultId = target.dataset.resultId;
        if (!action || !resultId) return;
        if (action === "preview-crm") await pushSingleResult(resultId);
        else if (action === "evidence") showEvidence(resultId);
    });

    await Promise.all([
        loadOutreach(),
        loadCRMStatus(),
        loadAuditActivity(),
        loadProspecting(),
        checkApiBudget(),
        loadAutomations(),
    ]);
});
