const runtimeSummary = document.getElementById("runtimeSummary");
const responsePane = document.getElementById("responsePane");
const resolutionPane = document.getElementById("resolutionPane");
const capabilitiesPane = document.getElementById("capabilitiesPane");
const shellForm = document.getElementById("shellForm");
const shellInput = document.getElementById("shellInput");

let runtimeSnapshot = null;

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

async function loadRuntime() {
    const response = await fetch("/api/desktop/runtime");
    const payload = await response.json();
    if (!payload.available) {
        runtimeSummary.innerHTML = `<div>${escapeHtml(payload.reason || "Desktop no disponible")}</div>`;
        return;
    }
    runtimeSnapshot = payload.runtime;
    renderRuntime(runtimeSnapshot);
}

function renderRuntime(runtime) {
    runtimeSummary.innerHTML = [
        `Producto: Open-Nexus`,
        `Modo: ${runtime.mode}`,
        `Contexto: ${runtime.context}`,
        `Skills: ${runtime.skills.total}`,
        `Capacidades: ${runtime.permissions.total}`,
        `Proveedor remoto: ${runtime.remote_provider?.enabled ? (runtime.remote_provider.model || "activo") : "sin activar"}`,
    ].map((item) => `<div>${escapeHtml(item)}</div>`).join("");

    capabilitiesPane.innerHTML = (runtime.capabilities || []).slice(0, 12)
        .map((item) => `<div>${escapeHtml(item.key)} · nivel ${escapeHtml(item.permission_level)}</div>`)
        .join("");
}

async function runCommand(event) {
    event.preventDefault();
    const userInput = shellInput.value.trim();
    if (!userInput) {
        return;
    }
    responsePane.textContent = "Ejecutando...";
    resolutionPane.innerHTML = "<div>Resolviendo skill...</div>";

    const [resolveResp, chatResp] = await Promise.all([
        fetch("/api/desktop/resolve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_input: userInput }),
        }),
        fetch("/api/nexus/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: userInput, user_id: "open-nexus", mode: "general" }),
        }),
    ]);

    const resolvePayload = await resolveResp.json();
    const chatPayload = await chatResp.json();

    const resolution = resolvePayload.resolution || {};
    resolutionPane.innerHTML = [
        `Skill: ${resolution.skill_id || "n/a"}`,
        `Confianza: ${resolution.confidence ?? "n/a"}`,
        `Modo: ${resolution.execution_mode || "n/a"}`,
        `Razon: ${resolution.rationale || "n/a"}`,
    ].map((item) => `<div>${escapeHtml(item)}</div>`).join("");

    responsePane.textContent = chatPayload.response || "Sin respuesta";
}

shellForm.addEventListener("submit", runCommand);
loadRuntime().catch((error) => {
    runtimeSummary.innerHTML = `<div>Error cargando runtime: ${escapeHtml(error.message)}</div>`;
});
