const api = {
    async get(url) {
        const response = await fetch(url);
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || `HTTP ${response.status}`);
        }
        return payload;
    },
    async put(url, body) {
        const response = await fetch(url, {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(body),
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || `HTTP ${response.status}`);
        }
        return payload;
    },
    async post(url, body) {
        const response = await fetch(url, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(body),
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || `HTTP ${response.status}`);
        }
        return payload;
    },
    async del(url) {
        const response = await fetch(url, { method: "DELETE" });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || `HTTP ${response.status}`);
        }
        return payload;
    },
};

function esc(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

const settingsState = {
    prompts: [],
    integrations: [],
    verticals: [],
};

const SUPPORTED_INTEGRATION_KINDS = ["prometheus", "alertmanager", "grafana"];

function switchSection(section) {
    document.querySelectorAll(".settings-nav-btn").forEach((button) => {
        button.classList.toggle("active", button.dataset.section === section);
    });
    document.querySelectorAll(".settings-panel").forEach((panel) => {
        panel.classList.toggle("is-active", panel.dataset.panel === section);
    });
    window.location.hash = section;
}

function setupSectionNav() {
    document.querySelectorAll(".settings-nav-btn").forEach((button) => {
        button.addEventListener("click", () => switchSection(button.dataset.section));
    });
    const section = window.location.hash.replace("#", "");
    if (section && document.querySelector(`.settings-nav-btn[data-section="${section}"]`)) {
        switchSection(section);
    }
}

async function loadGeneralSummary() {
    const payload = await api.get("/api/desktop/settings/summary");
    document.getElementById("generalContextBadge").textContent = payload.context || "desktop";
    document.getElementById("generalPathGrid").innerHTML = [
        ["Startup URL", payload.startup_url],
        ["Raiz local", payload.paths.root],
        ["Config", payload.paths.config_dir],
        ["Logs", payload.paths.logs_dir],
        ["Historial", payload.paths.history_dir],
        ["Proveedor LLM", payload.paths.provider_file],
        ["Monitoring DB", payload.paths.monitoring_db],
        ["Integraciones", `${payload.monitoring.total_integrations} totales`],
    ].map(([label, value]) => `
        <article class="settings-grid-item">
            <strong>${esc(label)}</strong>
            <code>${esc(value || "n/a")}</code>
        </article>
    `).join("");
}

function upsertPrompt(prompt) {
    const index = settingsState.prompts.findIndex((item) => item.key === prompt.key);
    if (index === -1) {
        settingsState.prompts.push(prompt);
    } else {
        settingsState.prompts[index] = prompt;
    }
}

function makePromptPanel(groupFilter, listId, titleId, badgeId, keyId, editorId, defaultId, statusId, saveBtnId, resetBtnId) {
    let selectedKey = null;

    function getPrompts() {
        return settingsState.prompts.filter((p) => p.group === groupFilter);
    }

    function renderList() {
        const container = document.getElementById(listId);
        if (!container) return;
        const prompts = getPrompts();
        if (!prompts.length) {
            container.innerHTML = '<div class="empty-state-sm">No hay prompts cargados.</div>';
            return;
        }
        container.innerHTML = prompts.map((p) => `
            <button class="prompt-nav-item ${p.key === selectedKey ? "active" : ""}" type="button" data-prompt-key="${esc(p.key)}">
                <strong>${esc(p.title)}</strong>
                <span>${esc(p.description)}</span>
            </button>
        `).join("");
        container.querySelectorAll("[data-prompt-key]").forEach((btn) => {
            btn.addEventListener("click", () => selectLocal(btn.dataset.promptKey));
        });
    }

    function selectLocal(key) {
        const prompt = settingsState.prompts.find((p) => p.key === key);
        if (!prompt) return;
        selectedKey = key;
        document.getElementById(titleId).textContent = prompt.title;
        document.getElementById(badgeId).textContent = prompt.is_overridden ? "override" : "default";
        document.getElementById(keyId).textContent = prompt.key;
        document.getElementById(editorId).value = prompt.current_text;
        document.getElementById(defaultId).textContent = prompt.default_text;
        document.getElementById(statusId).textContent = prompt.is_overridden ? "Override activo" : "Sin cambios";
        renderList();
    }

    async function saveLocal() {
        if (!selectedKey) return;
        const status = document.getElementById(statusId);
        status.textContent = "Guardando...";
        const payload = await api.put(`/api/nexus/prompts/${encodeURIComponent(selectedKey)}`, {
            current_text: document.getElementById(editorId).value,
        });
        upsertPrompt(payload.prompt);
        selectLocal(payload.prompt.key);
        status.textContent = "Guardado";
    }

    async function resetLocal() {
        if (!selectedKey) return;
        const status = document.getElementById(statusId);
        status.textContent = "Reseteando...";
        const payload = await api.post(`/api/nexus/prompts/${encodeURIComponent(selectedKey)}/reset`, {});
        upsertPrompt(payload.prompt);
        selectLocal(payload.prompt.key);
        status.textContent = "Reset aplicado";
    }

    function init() {
        document.getElementById(saveBtnId)?.addEventListener("click", () => {
            saveLocal().catch((err) => { document.getElementById(statusId).textContent = err.message; });
        });
        document.getElementById(resetBtnId)?.addEventListener("click", () => {
            resetLocal().catch((err) => { document.getElementById(statusId).textContent = err.message; });
        });
        document.getElementById(editorId)?.addEventListener("input", () => {
            document.getElementById(statusId).textContent = "Cambios sin guardar";
        });
        renderList();
        const prompts = getPrompts();
        if (prompts.length) selectLocal(prompts[0].key);
    }

    return { init, renderList };
}

const shellPanel        = makePromptPanel("agents",     "shellPromptList",    "shellPromptTitle",    "shellPromptBadge",    "shellPromptKey",    "shellPromptEditor",    "shellPromptDefault",    "shellPromptStatus",    "shellSavePromptBtn",    "shellResetPromptBtn");
const salesPromptPanel  = makePromptPanel("sales",      "salesPromptList",    "salesPromptTitle",    "salesPromptBadge",    "salesPromptKey",    "salesPromptEditor",    "salesPromptDefault",    "salesPromptStatus",    "salesSavePromptBtn",    "salesResetPromptBtn");
const campanaPromptPanel= makePromptPanel("mail",       "campanaPromptList",  "campanaPromptTitle",  "campanaPromptBadge",  "campanaPromptKey",  "campanaPromptEditor",  "campanaPromptDefault",  "campanaPromptStatus",  "campanaSavePromptBtn",  "campanaResetPromptBtn");
const operatorPromptPanel=makePromptPanel("operations", "operatorPromptList", "operatorPromptTitle", "operatorPromptBadge", "operatorPromptKey", "operatorPromptEditor", "operatorPromptDefault", "operatorPromptStatus", "operatorSavePromptBtn", "operatorResetPromptBtn");

async function loadPrompts() {
    const payload = await api.get("/api/nexus/prompts");
    settingsState.prompts = payload.prompts || [];
    [shellPanel, salesPromptPanel, campanaPromptPanel, operatorPromptPanel].forEach((p) => p.init());
}

const _LEVEL_NAMES = { 0: "L0", 1: "L1", 2: "L2", 3: "L3" };

function fillRouterForm(router, health) {
    const priority = router.priority || "cost";
    document.getElementById("routerPriority").value = priority;

    [0, 1, 2, 3].forEach((n) => {
        const lv = router[`l${n}`] || {};
        document.getElementById(`l${n}Url`).value = lv.url || "";
        document.getElementById(`l${n}Model`).value = lv.model || "";
        document.getElementById(`l${n}Key`).value = "";
        document.getElementById(`l${n}Enabled`).checked = lv.enabled !== false;

        const healthEl = document.getElementById(`levelHealth${n}`);
        const isHealthy = health && health[String(n)];
        const configured = Boolean(lv.url && lv.model);
        if (!configured) {
            healthEl.textContent = "sin configurar";
            healthEl.className = "level-health level-health-off";
        } else if (isHealthy === true) {
            healthEl.textContent = "activo";
            healthEl.className = "level-health level-health-ok";
        } else if (isHealthy === false) {
            healthEl.textContent = "sin respuesta";
            healthEl.className = "level-health level-health-fail";
        } else {
            healthEl.textContent = "pendiente";
            healthEl.className = "level-health level-health-off";
        }
    });
}

async function loadRouterConfig() {
    const payload = await api.get("/api/desktop/llm-router");
    fillRouterForm(payload.router || {}, payload.health || {});
    const src = payload.source === "saved" ? "configuracion guardada" : "valores del entorno";
    document.getElementById("routerStatus").textContent = src;
    document.getElementById("routerSaveNote").textContent = payload.path || "";
}

async function saveRouterConfig() {
    const status = document.getElementById("routerStatus");
    const note = document.getElementById("routerSaveNote");
    status.textContent = "Guardando...";
    const payload = await api.put("/api/desktop/llm-router", {
        priority: document.getElementById("routerPriority").value,
        l0: {
            url: document.getElementById("l0Url").value.trim(),
            model: document.getElementById("l0Model").value.trim(),
            api_key: document.getElementById("l0Key").value.trim(),
            enabled: document.getElementById("l0Enabled").checked,
        },
        l1: {
            url: document.getElementById("l1Url").value.trim(),
            model: document.getElementById("l1Model").value.trim(),
            api_key: document.getElementById("l1Key").value.trim(),
            enabled: document.getElementById("l1Enabled").checked,
        },
        l2: {
            url: document.getElementById("l2Url").value.trim(),
            model: document.getElementById("l2Model").value.trim(),
            api_key: document.getElementById("l2Key").value.trim(),
            enabled: document.getElementById("l2Enabled").checked,
        },
        l3: {
            url: document.getElementById("l3Url").value.trim(),
            model: document.getElementById("l3Model").value.trim(),
            api_key: document.getElementById("l3Key").value.trim(),
            enabled: document.getElementById("l3Enabled").checked,
        },
    });
    [0, 1, 2, 3].forEach((n) => document.getElementById(`l${n}Key`).value = "");
    status.textContent = "Aplicado";
    note.textContent = payload.path || "";
    await loadGeneralSummary();
}

function resetIntegrationForm() {
    document.getElementById("integrationFormTitle").textContent = "Nueva integracion";
    document.getElementById("integrationId").value = "";
    document.getElementById("integrationKind").value = "prometheus";
    document.getElementById("integrationName").value = "";
    document.getElementById("integrationBaseUrl").value = "";
    document.getElementById("integrationAuthType").value = "none";
    document.getElementById("integrationUsername").value = "";
    document.getElementById("integrationSecretRef").value = "";
    document.getElementById("integrationHeaderName").value = "";
    document.getElementById("integrationTimeout").value = "";
    document.getElementById("integrationEnabled").checked = true;
    document.getElementById("integrationDefault").checked = false;
    document.getElementById("integrationVerifyTls").checked = true;
}

function fillIntegrationForm(item) {
    document.getElementById("integrationFormTitle").textContent = `Editar ${item.name}`;
    document.getElementById("integrationId").value = item.integration_id || "";
    document.getElementById("integrationKind").value = item.kind || "prometheus";
    document.getElementById("integrationName").value = item.name || "";
    document.getElementById("integrationBaseUrl").value = item.base_url || "";
    document.getElementById("integrationAuthType").value = item.auth_type || "none";
    document.getElementById("integrationUsername").value = item.username || "";
    document.getElementById("integrationSecretRef").value = item.secret_ref || "";
    document.getElementById("integrationHeaderName").value = item.header_name || "";
    document.getElementById("integrationTimeout").value = item.timeout_seconds || "";
    document.getElementById("integrationEnabled").checked = Boolean(item.enabled);
    document.getElementById("integrationDefault").checked = Boolean(item.is_default);
    document.getElementById("integrationVerifyTls").checked = item.verify_tls !== false;
}

function integrationPayloadFromForm() {
    const timeoutValue = document.getElementById("integrationTimeout").value.trim();
    return {
        integration_id: document.getElementById("integrationId").value.trim() || null,
        kind: document.getElementById("integrationKind").value,
        name: document.getElementById("integrationName").value.trim(),
        base_url: document.getElementById("integrationBaseUrl").value.trim(),
        auth_type: document.getElementById("integrationAuthType").value,
        username: document.getElementById("integrationUsername").value.trim(),
        secret_ref: document.getElementById("integrationSecretRef").value.trim(),
        header_name: document.getElementById("integrationHeaderName").value.trim(),
        timeout_seconds: timeoutValue ? Number(timeoutValue) : null,
        enabled: document.getElementById("integrationEnabled").checked,
        is_default: document.getElementById("integrationDefault").checked,
        verify_tls: document.getElementById("integrationVerifyTls").checked,
        source: "desktop_settings",
    };
}

function renderIntegrations() {
    const container = document.getElementById("integrationGroups");
    if (!settingsState.integrations.length) {
        container.innerHTML = '<div class="empty-state-sm">No hay integraciones guardadas todavia.</div>';
        return;
    }

    const groups = settingsState.integrations.reduce((acc, item) => {
        if (!acc[item.kind]) {
            acc[item.kind] = [];
        }
        acc[item.kind].push(item);
        return acc;
    }, {});

    const orderedGroups = SUPPORTED_INTEGRATION_KINDS
        .filter((kind) => groups[kind]?.length)
        .map((kind) => [kind, groups[kind]])
        .concat(
            Object.entries(groups).filter(([kind]) => !SUPPORTED_INTEGRATION_KINDS.includes(kind))
        );

    container.innerHTML = orderedGroups.map(([kind, items]) => `
        <section class="integration-group">
            <div class="integration-group-head">
                <div>
                    <p class="eyebrow eyebrow-tight">${esc(kind)}</p>
                    <h4>${esc(kind.charAt(0).toUpperCase() + kind.slice(1))}</h4>
                </div>
                <span class="kind-pill">${esc(items.length)} fuente(s)</span>
            </div>
            ${items.map((item) => `
                <article class="integration-card">
                    <div class="integration-card-head">
                        <div>
                            <div class="integration-title">${esc(item.name)}</div>
                            <div class="integration-meta">${esc(item.base_url)}</div>
                        </div>
                        <div class="integration-card-actions">
                            ${item.is_default ? '<span class="default-pill">default</span>' : ""}
                            ${!item.enabled ? '<span class="disabled-pill">off</span>' : ""}
                            <button type="button" data-edit-integration="${esc(item.integration_id)}">Editar</button>
                            <button type="button" data-delete-integration="${esc(item.integration_id)}">Eliminar</button>
                        </div>
                    </div>
                    <div class="integration-meta">
                        auth=${esc(item.auth_type || "none")} · secret_ref=${esc(item.secret_ref || "n/a")} · tls=${item.verify_tls ? "on" : "off"}
                    </div>
                </article>
            `).join("")}
        </section>
    `).join("");

    container.querySelectorAll("[data-edit-integration]").forEach((button) => {
        button.addEventListener("click", () => {
            const item = settingsState.integrations.find((entry) => entry.integration_id === button.dataset.editIntegration);
            if (item) {
                fillIntegrationForm(item);
            }
        });
    });

    container.querySelectorAll("[data-delete-integration]").forEach((button) => {
        button.addEventListener("click", () => {
            const item = settingsState.integrations.find((entry) => entry.integration_id === button.dataset.deleteIntegration);
            if (item) {
                deleteIntegration(item.integration_id, item.name).catch((error) => {
                    document.getElementById("integrationTestResult").innerHTML = `<p>${esc(error.message)}</p>`;
                });
            }
        });
    });
}

async function loadIntegrations() {
    const payload = await api.get("/api/desktop/operator/integrations");
    settingsState.integrations = (payload.integrations || []).filter((item) =>
        SUPPORTED_INTEGRATION_KINDS.includes(item.kind)
    );
    renderIntegrations();
    document.getElementById("operatorStatus").textContent = `${settingsState.integrations.length} integracion(es) cargadas`;
}

async function saveIntegration(event) {
    event.preventDefault();
    const payload = await api.put("/api/desktop/operator/integrations", integrationPayloadFromForm());
    document.getElementById("integrationTestResult").innerHTML = `<p>Integracion guardada: <strong>${esc(payload.integration.name)}</strong></p>`;
    resetIntegrationForm();
    await Promise.all([loadIntegrations(), loadGeneralSummary()]);
}

async function testIntegration() {
    const payload = await api.post("/api/desktop/operator/integrations/test", integrationPayloadFromForm());
    const result = document.getElementById("integrationTestResult");
    if (payload.status === "ok") {
        result.innerHTML = `<p>Conexion OK contra <strong>${esc(payload.report.endpoint || payload.report.name)}</strong>.</p>`;
    } else {
        result.innerHTML = `<p>Error de conexion: ${esc(payload.report.reason || "sin detalle")}</p>`;
    }
}

async function deleteIntegration(integrationId = null, integrationName = "") {
    const resolvedId = integrationId || document.getElementById("integrationId").value.trim();
    const resolvedName = integrationName || document.getElementById("integrationName").value.trim() || resolvedId;
    if (!resolvedId) {
        document.getElementById("integrationTestResult").innerHTML = "<p>Selecciona una integracion para eliminarla.</p>";
        return;
    }
    if (!window.confirm(`Vas a eliminar la fuente "${resolvedName}".`)) {
        return;
    }
    await api.del(`/api/desktop/operator/integrations/${encodeURIComponent(resolvedId)}`);
    document.getElementById("integrationTestResult").innerHTML = "<p>Integracion eliminada.</p>";
    resetIntegrationForm();
    await Promise.all([loadIntegrations(), loadGeneralSummary()]);
}

function _updateSalesStatus(payload) {
    const active = [
        payload.brave.enabled,
        payload.google_places.enabled,
        payload.assets_crm.enabled,
        payload.odoo.enabled,
    ].filter(Boolean).length;
    const el = document.getElementById("salesStatus");
    if (!el) { return; }
    el.textContent = `${active} fuente(s) activa(s)`;
    el.className = active > 0 ? "info-badge" : "info-badge info-badge-muted";
}

async function loadSalesConfig() {
    const payload = await api.get("/api/desktop/settings/sales");
    document.getElementById("braveEnabled").checked = Boolean(payload.brave.enabled);
    document.getElementById("braveRateLimit").value = payload.brave.rate_limit ?? "";
    document.getElementById("gpEnabled").checked = Boolean(payload.google_places.enabled);
    document.getElementById("gpRateLimit").value = payload.google_places.rate_limit ?? "";
    document.getElementById("gpMaxResults").value = payload.google_places.max_results ?? "";
    document.getElementById("assetsCrmEnabled").checked = Boolean(payload.assets_crm.enabled);
    document.getElementById("assetsCrmUrl").value = payload.assets_crm.base_url || "";
    document.getElementById("assetsCrmUser").value = payload.assets_crm.username || "";
    document.getElementById("odooEnabled").checked = Boolean(payload.odoo.enabled);
    document.getElementById("odooUrl").value = payload.odoo.base_url || "";
    document.getElementById("odooDatabase").value = payload.odoo.database || "";
    document.getElementById("odooUser").value = payload.odoo.username || "";
    document.getElementById("odooTeam").value = payload.odoo.default_team || "";
    document.getElementById("odooStage").value = payload.odoo.default_stage || "";
    _updateSalesStatus(payload);
}

async function saveSalesConfig() {
    const note = document.getElementById("salesSaveNote");
    note.textContent = "Guardando...";
    const payload = await api.put("/api/desktop/settings/sales", {
        brave_enabled: document.getElementById("braveEnabled").checked,
        brave_api_key: document.getElementById("braveApiKey").value.trim(),
        brave_rate_limit: parseFloat(document.getElementById("braveRateLimit").value) || 1.0,
        gp_enabled: document.getElementById("gpEnabled").checked,
        gp_api_key: document.getElementById("gpApiKey").value.trim(),
        gp_rate_limit: parseFloat(document.getElementById("gpRateLimit").value) || 0.5,
        gp_max_results: parseInt(document.getElementById("gpMaxResults").value) || 20,
        assets_crm_enabled: document.getElementById("assetsCrmEnabled").checked,
        assets_crm_base_url: document.getElementById("assetsCrmUrl").value.trim(),
        assets_crm_username: document.getElementById("assetsCrmUser").value.trim(),
        assets_crm_password: document.getElementById("assetsCrmPassword").value,
        odoo_enabled: document.getElementById("odooEnabled").checked,
        odoo_base_url: document.getElementById("odooUrl").value.trim(),
        odoo_database: document.getElementById("odooDatabase").value.trim(),
        odoo_username: document.getElementById("odooUser").value.trim(),
        odoo_password: document.getElementById("odooPassword").value,
        odoo_default_team: document.getElementById("odooTeam").value.trim(),
        odoo_default_stage: document.getElementById("odooStage").value.trim(),
    });
    document.getElementById("braveApiKey").value = "";
    document.getElementById("gpApiKey").value = "";
    document.getElementById("assetsCrmPassword").value = "";
    document.getElementById("odooPassword").value = "";
    note.textContent = "Guardado";
    await loadSalesConfig();
}

// ── Verticales comerciales (CRUD contra sales_verticals) ─────────────────────

function slugifyVerticalName(value) {
    return String(value || "")
        .normalize("NFKD").replace(/[̀-ͯ]/g, "")
        .toLowerCase().trim()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "");
}

function resetVerticalForm() {
    document.getElementById("verticalFormTitle").textContent = "Nueva vertical";
    document.getElementById("verticalOriginalSlug").value = "";
    document.getElementById("verticalNombre").value = "";
    document.getElementById("verticalSlug").value = "";
    document.getElementById("verticalAliases").value = "";
    document.getElementById("verticalCrmSector").value = "otros";
    document.getElementById("verticalCrmTags").value = "";
    document.getElementById("verticalActivo").checked = true;
    document.getElementById("verticalScoringRules").value = "";
    document.getElementById("verticalDiscoveryConfig").value = "";
    document.getElementById("verticalSlug").disabled = false;
    document.getElementById("verticalActivo").disabled = false;
}

function fillVerticalForm(item) {
    document.getElementById("verticalFormTitle").textContent = `Editar ${item.nombre}`;
    document.getElementById("verticalOriginalSlug").value = item.slug;
    document.getElementById("verticalNombre").value = item.nombre || "";
    document.getElementById("verticalSlug").value = item.slug || "";
    document.getElementById("verticalAliases").value = (item.aliases || []).join(", ");
    document.getElementById("verticalCrmSector").value = item.crm_sector || "otros";
    document.getElementById("verticalCrmTags").value = (item.crm_tags || []).join(", ");
    document.getElementById("verticalActivo").checked = Boolean(item.activo);
    document.getElementById("verticalScoringRules").value = Object.keys(item.scoring_rules || {}).length
        ? JSON.stringify(item.scoring_rules, null, 2) : "";
    document.getElementById("verticalDiscoveryConfig").value = Object.keys(item.discovery_config || {}).length
        ? JSON.stringify(item.discovery_config, null, 2) : "";
    // El slug es la clave primaria — no se renombra tras creado (evita romper
    // referencias en runs/leads ya guardados con ese slug). El estado activo/
    // inactivo se cambia con el boton de la lista, no desde este formulario.
    document.getElementById("verticalSlug").disabled = true;
    document.getElementById("verticalActivo").disabled = true;
}

function parseCommaList(value) {
    return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function parseJsonFieldOrEmpty(elementId) {
    const raw = document.getElementById(elementId).value.trim();
    if (!raw) { return {}; }
    return JSON.parse(raw);
}

function renderVerticals() {
    const container = document.getElementById("verticalGroups");
    if (!settingsState.verticals.length) {
        container.innerHTML = '<div class="empty-state-sm">No hay verticales todavia.</div>';
        return;
    }
    container.innerHTML = settingsState.verticals.map((item) => `
        <article class="integration-card">
            <div class="integration-card-head">
                <div>
                    <div class="integration-title">${esc(item.nombre)}</div>
                    <div class="integration-meta">${esc(item.slug)}${item.aliases.length ? " · alias: " + esc(item.aliases.join(", ")) : ""}</div>
                </div>
                <div class="integration-card-actions">
                    ${item.is_fallback ? '<span class="default-pill">fallback</span>' : ""}
                    ${!item.activo ? '<span class="disabled-pill">inactiva</span>' : ""}
                    <button type="button" data-edit-vertical="${esc(item.slug)}">Editar</button>
                    ${item.is_fallback ? "" : `<button type="button" data-toggle-vertical="${esc(item.slug)}">${item.activo ? "Desactivar" : "Activar"}</button>`}
                </div>
            </div>
        </article>
    `).join("");

    container.querySelectorAll("[data-edit-vertical]").forEach((button) => {
        button.addEventListener("click", () => {
            const item = settingsState.verticals.find((entry) => entry.slug === button.dataset.editVertical);
            if (item) { fillVerticalForm(item); }
        });
    });
    container.querySelectorAll("[data-toggle-vertical]").forEach((button) => {
        button.addEventListener("click", () => {
            const item = settingsState.verticals.find((entry) => entry.slug === button.dataset.toggleVertical);
            if (item) {
                toggleVerticalActive(item).catch((error) => {
                    document.getElementById("verticalFormResult").innerHTML = `<p>${esc(error.message)}</p>`;
                });
            }
        });
    });
}

async function loadVerticals() {
    const payload = await api.get("/api/nexus/prospecting/verticals");
    settingsState.verticals = payload.verticals || [];
    renderVerticals();
    const el = document.getElementById("verticalsStatus");
    if (el) {
        const active = settingsState.verticals.filter((item) => item.activo).length;
        el.textContent = `${settingsState.verticals.length} vertical(es) · ${active} activa(s)`;
        el.className = "info-badge";
    }
}

async function saveVertical(event) {
    event.preventDefault();
    const result = document.getElementById("verticalFormResult");
    const originalSlug = document.getElementById("verticalOriginalSlug").value.trim();
    const nombre = document.getElementById("verticalNombre").value.trim();
    if (!nombre) {
        result.innerHTML = "<p>El nombre es obligatorio.</p>";
        return;
    }

    let scoringRules;
    let discoveryConfig;
    try {
        scoringRules = parseJsonFieldOrEmpty("verticalScoringRules");
        discoveryConfig = parseJsonFieldOrEmpty("verticalDiscoveryConfig");
    } catch (error) {
        result.innerHTML = `<p>JSON invalido en señales de scoring o config de discovery: ${esc(error.message)}</p>`;
        return;
    }

    const body = {
        nombre,
        aliases: parseCommaList(document.getElementById("verticalAliases").value),
        crm_sector: document.getElementById("verticalCrmSector").value.trim() || "otros",
        crm_tags: parseCommaList(document.getElementById("verticalCrmTags").value),
        scoring_rules: scoringRules,
        discovery_config: discoveryConfig,
    };

    try {
        if (originalSlug) {
            await api.put(`/api/nexus/prospecting/verticals/${encodeURIComponent(originalSlug)}`, body);
            result.innerHTML = `<p>Vertical <strong>${esc(nombre)}</strong> actualizada.</p>`;
        } else {
            body.slug = document.getElementById("verticalSlug").value.trim() || slugifyVerticalName(nombre);
            body.activo = document.getElementById("verticalActivo").checked;
            await api.post("/api/nexus/prospecting/verticals", body);
            result.innerHTML = `<p>Vertical <strong>${esc(nombre)}</strong> creada — ya disponible sin reiniciar Nexus.</p>`;
        }
    } catch (error) {
        result.innerHTML = `<p>${esc(error.message)}</p>`;
        return;
    }
    resetVerticalForm();
    await loadVerticals();
}

async function toggleVerticalActive(item) {
    await api.put(`/api/nexus/prospecting/verticals/${encodeURIComponent(item.slug)}/activo`, { activo: !item.activo });
    await loadVerticals();
}

async function deleteVertical() {
    const slug = document.getElementById("verticalOriginalSlug").value.trim();
    const result = document.getElementById("verticalFormResult");
    if (!slug) {
        result.innerHTML = "<p>Selecciona una vertical existente para eliminarla.</p>";
        return;
    }
    if (!window.confirm(`Vas a eliminar la vertical "${slug}". Los leads ya prospectados con ese slug no se ven afectados.`)) {
        return;
    }
    try {
        await api.del(`/api/nexus/prospecting/verticals/${encodeURIComponent(slug)}`);
        result.innerHTML = "<p>Vertical eliminada.</p>";
    } catch (error) {
        result.innerHTML = `<p>${esc(error.message)}</p>`;
        return;
    }
    resetVerticalForm();
    await loadVerticals();
}

async function loadCampaignConfig() {
    const payload = await api.get("/api/desktop/settings/campaign");
    document.getElementById("outreachEnabled").checked = Boolean(payload.outreach.enabled);
    document.getElementById("outreachFromAddress").value = payload.outreach.from_address || "";
    document.getElementById("outreachSenderName").value = payload.outreach.sender_name || "";
    document.getElementById("outreachDailyCap").value = payload.outreach.daily_cap ?? "";
    document.getElementById("outreachFollowupDelays").value = payload.outreach.followup_delays || "";
    document.getElementById("smtpHost").value = payload.smtp.host || "";
    document.getElementById("smtpPort").value = payload.smtp.port ?? "";
    document.getElementById("smtpUser").value = payload.smtp.user || "";
    document.getElementById("imapHost").value = payload.imap.host || "";
    document.getElementById("imapPort").value = payload.imap.port ?? "";
    document.getElementById("imapUser").value = payload.imap.user || "";
    const statusEl = document.getElementById("campanaStatus");
    if (statusEl) {
        statusEl.textContent = payload.outreach.enabled ? "habilitado" : "deshabilitado";
        statusEl.className = payload.outreach.enabled ? "info-badge" : "info-badge info-badge-muted";
    }
}

async function saveCampaignConfig() {
    const note = document.getElementById("campanaSaveNote");
    note.textContent = "Guardando...";
    await api.put("/api/desktop/settings/campaign", {
        outreach_enabled: document.getElementById("outreachEnabled").checked,
        outreach_from_address: document.getElementById("outreachFromAddress").value.trim(),
        outreach_sender_name: document.getElementById("outreachSenderName").value.trim(),
        outreach_daily_cap: parseInt(document.getElementById("outreachDailyCap").value) || 20,
        outreach_followup_delays: document.getElementById("outreachFollowupDelays").value.trim(),
        smtp_host: document.getElementById("smtpHost").value.trim(),
        smtp_port: parseInt(document.getElementById("smtpPort").value) || 465,
        smtp_user: document.getElementById("smtpUser").value.trim(),
        smtp_password: document.getElementById("smtpPassword").value,
        imap_host: document.getElementById("imapHost").value.trim(),
        imap_port: parseInt(document.getElementById("imapPort").value) || 993,
        imap_user: document.getElementById("imapUser").value.trim(),
        imap_password: document.getElementById("imapPassword").value,
    });
    document.getElementById("smtpPassword").value = "";
    document.getElementById("imapPassword").value = "";
    note.textContent = "Guardado";
    await loadCampaignConfig();
}

async function loadItsmConfig() {
    const payload = await api.get("/api/desktop/settings/itsm");
    document.getElementById("itsmAssetsEnabled").checked = Boolean(payload.assets.enabled);
    document.getElementById("itsmAssetsUrl").value = payload.assets.base_url || "";
    document.getElementById("itsmAssetsUser").value = payload.assets.username || "";
    document.getElementById("itsmJiraEnabled").checked = Boolean(payload.jira.enabled);
    document.getElementById("itsmJiraUrl").value = payload.jira.url || "";
    document.getElementById("itsmJiraEmail").value = payload.jira.email || "";
    document.getElementById("itsmJiraProject").value = payload.jira.project_key || "NEXUS";
    document.getElementById("itsmSnEnabled").checked = Boolean(payload.servicenow.enabled);
    document.getElementById("itsmSnUrl").value = payload.servicenow.url || "";
    document.getElementById("itsmSnUser").value = payload.servicenow.username || "";
    document.getElementById("itsmSnClientId").value = payload.servicenow.client_id || "";

    const active = [
        payload.assets.enabled,
        payload.jira.enabled,
        payload.servicenow.enabled,
    ].filter(Boolean);
    const el = document.getElementById("itsmStatus");
    if (el) {
        const labels = [];
        if (payload.assets.enabled) { labels.push("Assets"); }
        if (payload.jira.enabled) { labels.push("Jira"); }
        if (payload.servicenow.enabled) { labels.push("ServiceNow"); }
        el.textContent = labels.length ? labels.join(" · ") : "ninguno activo";
        el.className = labels.length ? "info-badge" : "info-badge info-badge-muted";
    }
}

async function saveItsmConfig() {
    const note = document.getElementById("itsmSaveNote");
    note.textContent = "Guardando...";
    await api.put("/api/desktop/settings/itsm", {
        assets_enabled: document.getElementById("itsmAssetsEnabled").checked,
        assets_base_url: document.getElementById("itsmAssetsUrl").value.trim(),
        assets_username: document.getElementById("itsmAssetsUser").value.trim(),
        assets_password: document.getElementById("itsmAssetsPassword").value,
        jira_enabled: document.getElementById("itsmJiraEnabled").checked,
        jira_url: document.getElementById("itsmJiraUrl").value.trim(),
        jira_email: document.getElementById("itsmJiraEmail").value.trim(),
        jira_api_token: document.getElementById("itsmJiraToken").value,
        jira_project_key: document.getElementById("itsmJiraProject").value.trim() || "NEXUS",
        sn_enabled: document.getElementById("itsmSnEnabled").checked,
        sn_url: document.getElementById("itsmSnUrl").value.trim(),
        sn_username: document.getElementById("itsmSnUser").value.trim(),
        sn_password: document.getElementById("itsmSnPassword").value,
        sn_client_id: document.getElementById("itsmSnClientId").value.trim(),
        sn_client_secret: document.getElementById("itsmSnClientSecret").value,
    });
    document.getElementById("itsmAssetsPassword").value = "";
    document.getElementById("itsmJiraToken").value = "";
    document.getElementById("itsmSnPassword").value = "";
    document.getElementById("itsmSnClientSecret").value = "";
    note.textContent = "Guardado";
    await loadItsmConfig();
}

function wireEvents() {
    document.getElementById("saveRouterBtn").addEventListener("click", () => {
        saveRouterConfig().catch((error) => {
            document.getElementById("routerStatus").textContent = error.message;
        });
    });
    document.getElementById("integrationForm").addEventListener("submit", (event) => {
        saveIntegration(event).catch((error) => {
            document.getElementById("integrationTestResult").innerHTML = `<p>${esc(error.message)}</p>`;
        });
    });
    document.getElementById("testIntegrationBtn").addEventListener("click", () => {
        testIntegration().catch((error) => {
            document.getElementById("integrationTestResult").innerHTML = `<p>${esc(error.message)}</p>`;
        });
    });
    document.getElementById("deleteIntegrationBtn").addEventListener("click", () => {
        deleteIntegration().catch((error) => {
            document.getElementById("integrationTestResult").innerHTML = `<p>${esc(error.message)}</p>`;
        });
    });
    document.getElementById("newIntegrationBtn").addEventListener("click", resetIntegrationForm);
    document.getElementById("saveSalesBtn").addEventListener("click", () => {
        saveSalesConfig().catch((error) => {
            document.getElementById("salesSaveNote").textContent = error.message;
        });
    });
    document.getElementById("verticalForm").addEventListener("submit", (event) => {
        saveVertical(event).catch((error) => {
            document.getElementById("verticalFormResult").innerHTML = `<p>${esc(error.message)}</p>`;
        });
    });
    document.getElementById("deleteVerticalBtn").addEventListener("click", () => {
        deleteVertical().catch((error) => {
            document.getElementById("verticalFormResult").innerHTML = `<p>${esc(error.message)}</p>`;
        });
    });
    document.getElementById("newVerticalBtn").addEventListener("click", resetVerticalForm);
    document.getElementById("saveCampanaBtn").addEventListener("click", () => {
        saveCampaignConfig().catch((error) => {
            document.getElementById("campanaSaveNote").textContent = error.message;
        });
    });
    document.getElementById("saveItsmBtn").addEventListener("click", () => {
        saveItsmConfig().catch((error) => {
            document.getElementById("itsmSaveNote").textContent = error.message;
        });
    });
}

async function bootstrap() {
    setupSectionNav();
    wireEvents();
    resetIntegrationForm();
    resetVerticalForm();
    await Promise.all([
        loadGeneralSummary(),
        loadPrompts(),
        loadRouterConfig(),
        loadIntegrations(),
        loadSalesConfig().catch(() => {
            const el = document.getElementById("salesStatus");
            if (el) { el.textContent = "no disponible"; }
        }),
        loadVerticals().catch(() => {
            const el = document.getElementById("verticalsStatus");
            if (el) { el.textContent = "no disponible"; }
        }),
        loadCampaignConfig().catch(() => {
            const el = document.getElementById("campanaStatus");
            if (el) { el.textContent = "no disponible"; }
        }),
        loadItsmConfig().catch(() => {
            const el = document.getElementById("itsmStatus");
            if (el) { el.textContent = "no disponible"; }
        }),
    ]);
}

bootstrap().catch((error) => {
    console.error(error);
});
