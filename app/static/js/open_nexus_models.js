const providerForm = document.getElementById("providerForm");
const providerLabel = document.getElementById("providerLabel");
const providerType = document.getElementById("providerType");
const providerBaseUrl = document.getElementById("providerBaseUrl");
const providerModel = document.getElementById("providerModel");
const providerApiKey = document.getElementById("providerApiKey");
const providerEnabled = document.getElementById("providerEnabled");
const providerStatus = document.getElementById("providerStatus");
const providerSummary = document.getElementById("providerSummary");
const providerPaths = document.getElementById("providerPaths");

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

function renderProviderSummary(payload, paths = null) {
    const provider = payload.provider || {};
    providerSummary.innerHTML = [
        `Etiqueta: ${provider.provider_label || "n/a"}`,
        `Tipo: ${provider.provider_type || "n/a"}`,
        `Base URL: ${provider.api_base_url || "n/a"}`,
        `Modelo: ${provider.model || "n/a"}`,
        `API key: ${provider.api_key || "sin configurar"}`,
        `Habilitado: ${provider.enabled ? "sí" : "no"}`,
        `Aplicado: ${payload.applied ? "sí" : "no"}`,
        `Actualizado: ${provider.updated_at || "n/a"}`,
    ].map((item) => `<div>${escapeHtml(item)}</div>`).join("");

    if (paths) {
        providerPaths.innerHTML = [
            `Config: ${paths.config_dir || "n/a"}`,
            `Fichero: ${paths.provider_file || "n/a"}`,
        ].map((item) => `<div>${escapeHtml(item)}</div>`).join("");
    }
}

function fillForm(provider) {
    providerLabel.value = provider.provider_label || "";
    providerType.value = provider.provider_type || "openai_compatible";
    providerBaseUrl.value = provider.api_base_url || "";
    providerModel.value = provider.model || "";
    providerApiKey.value = "";
    providerEnabled.checked = Boolean(provider.enabled);
}

async function loadProviderConfig() {
    const response = await fetch("/api/desktop/providers");
    const payload = await response.json();
    if (!payload.available) {
        providerStatus.textContent = payload.reason || "Desktop no disponible";
        return;
    }
    fillForm(payload.provider || {});
    renderProviderSummary(payload);
    providerStatus.textContent = payload.applied
        ? "Proveedor remoto cargado en el runtime."
        : "Todavía no hay proveedor remoto aplicado.";
}

async function saveProviderConfig(event) {
    event.preventDefault();
    providerStatus.textContent = "Guardando y aplicando...";

    const response = await fetch("/api/desktop/providers", {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            provider_label: providerLabel.value.trim(),
            provider_type: providerType.value,
            api_base_url: providerBaseUrl.value.trim(),
            api_key: providerApiKey.value.trim(),
            model: providerModel.value.trim(),
            enabled: providerEnabled.checked,
        }),
    });

    const payload = await response.json();
    if (!response.ok) {
        providerStatus.textContent = payload.detail || "No se pudo guardar la configuración.";
        return;
    }

    renderProviderSummary(payload, payload.paths);
    providerStatus.textContent = payload.applied
        ? "Proveedor guardado y aplicado al runtime."
        : "Configuración guardada, pero aún no está completa para activarse.";
    providerApiKey.value = "";
}

providerForm.addEventListener("submit", saveProviderConfig);
loadProviderConfig().catch((error) => {
    providerStatus.textContent = `Error cargando configuración: ${error.message}`;
});
