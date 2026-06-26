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
    selectedPromptKey: null,
    integrations: [],
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

function renderPromptList() {
    const container = document.getElementById("promptGroupList");
    if (!settingsState.prompts.length) {
        container.innerHTML = '<div class="empty-state-sm">No hay prompts cargados.</div>';
        return;
    }
    const groups = settingsState.prompts.reduce((acc, prompt) => {
        if (!acc[prompt.group]) {
            acc[prompt.group] = [];
        }
        acc[prompt.group].push(prompt);
        return acc;
    }, {});

    container.innerHTML = Object.entries(groups).map(([group, prompts]) => `
        <section class="prompt-group">
            <p class="prompt-group-title">${esc(group)}</p>
            ${prompts.map((prompt) => `
                <button class="prompt-nav-item ${prompt.key === settingsState.selectedPromptKey ? "active" : ""}" type="button" data-prompt-key="${esc(prompt.key)}">
                    <strong>${esc(prompt.title)}</strong>
                    <span>${esc(prompt.description)}</span>
                </button>
            `).join("")}
        </section>
    `).join("");

    container.querySelectorAll("[data-prompt-key]").forEach((button) => {
        button.addEventListener("click", () => selectPrompt(button.dataset.promptKey));
    });
}

function selectPrompt(key) {
    const prompt = settingsState.prompts.find((item) => item.key === key);
    if (!prompt) {
        return;
    }
    settingsState.selectedPromptKey = key;
    document.getElementById("promptGroupLabel").textContent = prompt.group;
    document.getElementById("promptTitle").textContent = prompt.title;
    document.getElementById("promptKeyLabel").textContent = prompt.key;
    document.getElementById("promptOverrideBadge").textContent = prompt.is_overridden ? "override" : "default";
    document.getElementById("promptEditor").value = prompt.current_text;
    document.getElementById("promptDefault").textContent = prompt.default_text;
    document.getElementById("promptSaveStatus").textContent = prompt.is_overridden ? "Override activo" : "Sin cambios";
    renderPromptList();
}

function upsertPrompt(prompt) {
    const index = settingsState.prompts.findIndex((item) => item.key === prompt.key);
    if (index === -1) {
        settingsState.prompts.push(prompt);
    } else {
        settingsState.prompts[index] = prompt;
    }
}

async function loadPrompts() {
    const payload = await api.get("/api/nexus/prompts");
    settingsState.prompts = payload.prompts || [];
    renderPromptList();
    if (settingsState.prompts.length) {
        selectPrompt(settingsState.selectedPromptKey || settingsState.prompts[0].key);
    }
}

async function savePrompt() {
    if (!settingsState.selectedPromptKey) {
        return;
    }
    const status = document.getElementById("promptSaveStatus");
    status.textContent = "Guardando...";
    const payload = await api.put(`/api/nexus/prompts/${encodeURIComponent(settingsState.selectedPromptKey)}`, {
        current_text: document.getElementById("promptEditor").value,
    });
    upsertPrompt(payload.prompt);
    selectPrompt(payload.prompt.key);
    status.textContent = "Guardado";
}

async function resetPrompt() {
    if (!settingsState.selectedPromptKey) {
        return;
    }
    const status = document.getElementById("promptSaveStatus");
    status.textContent = "Reseteando...";
    const payload = await api.post(`/api/nexus/prompts/${encodeURIComponent(settingsState.selectedPromptKey)}/reset`, {});
    upsertPrompt(payload.prompt);
    selectPrompt(payload.prompt.key);
    status.textContent = "Reset aplicado";
}

function fillProviderForm(provider) {
    document.getElementById("providerLabel").value = provider.provider_label || "";
    document.getElementById("providerType").value = provider.provider_type || "openai_compatible";
    document.getElementById("providerBaseUrl").value = provider.api_base_url || "";
    document.getElementById("providerModel").value = provider.model || "";
    document.getElementById("providerApiKey").value = "";
    document.getElementById("providerEnabled").checked = Boolean(provider.enabled);
}

function renderProviderSummary(payload, paths = null) {
    const provider = payload.provider || {};
    document.getElementById("providerSummary").innerHTML = [
        `Etiqueta: ${provider.provider_label || "n/a"}`,
        `Tipo: ${provider.provider_type || "n/a"}`,
        `Base URL: ${provider.api_base_url || "n/a"}`,
        `Modelo: ${provider.model || "n/a"}`,
        `API key: ${provider.api_key || "sin configurar"}`,
        `Habilitado: ${provider.enabled ? "si" : "no"}`,
        `Aplicado: ${payload.applied ? "si" : "no"}`,
        `Actualizado: ${provider.updated_at || "n/a"}`,
    ].map((item) => `<div>${esc(item)}</div>`).join("");

    if (paths) {
        document.getElementById("providerPaths").innerHTML = [
            `Config: ${paths.config_dir || "n/a"}`,
            `Fichero: ${paths.provider_file || "n/a"}`,
        ].map((item) => `<div>${esc(item)}</div>`).join("");
    }
}

async function loadProviderConfig() {
    const payload = await api.get("/api/desktop/providers");
    fillProviderForm(payload.provider || {});
    renderProviderSummary(payload);
    document.getElementById("providerStatus").textContent = payload.applied
        ? "Proveedor remoto cargado en runtime"
        : "Todavia no hay proveedor remoto activo";
}

async function saveProviderConfig(event) {
    event.preventDefault();
    const status = document.getElementById("providerStatus");
    status.textContent = "Guardando y aplicando...";
    const payload = await api.put("/api/desktop/providers", {
        provider_label: document.getElementById("providerLabel").value.trim(),
        provider_type: document.getElementById("providerType").value,
        api_base_url: document.getElementById("providerBaseUrl").value.trim(),
        api_key: document.getElementById("providerApiKey").value.trim(),
        model: document.getElementById("providerModel").value.trim(),
        enabled: document.getElementById("providerEnabled").checked,
    });
    renderProviderSummary(payload, payload.paths);
    document.getElementById("providerApiKey").value = "";
    status.textContent = payload.applied ? "Proveedor guardado y aplicado" : "Configuracion guardada, pero incompleta";
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

function wireEvents() {
    document.getElementById("savePromptBtn").addEventListener("click", () => {
        savePrompt().catch((error) => {
            document.getElementById("promptSaveStatus").textContent = error.message;
        });
    });
    document.getElementById("resetPromptBtn").addEventListener("click", () => {
        resetPrompt().catch((error) => {
            document.getElementById("promptSaveStatus").textContent = error.message;
        });
    });
    document.getElementById("promptEditor").addEventListener("input", () => {
        document.getElementById("promptSaveStatus").textContent = "Cambios sin guardar";
    });
    document.getElementById("providerForm").addEventListener("submit", (event) => {
        saveProviderConfig(event).catch((error) => {
            document.getElementById("providerStatus").textContent = error.message;
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
}

async function bootstrap() {
    setupSectionNav();
    wireEvents();
    resetIntegrationForm();
    await Promise.all([
        loadGeneralSummary(),
        loadPrompts(),
        loadProviderConfig(),
        loadIntegrations(),
    ]);
}

bootstrap().catch((error) => {
    console.error(error);
});
