const state = {
    prompts: [],
    selectedKey: null,
};

const groupList = document.getElementById("promptGroupList");
const promptTitle = document.getElementById("promptTitle");
const promptDescription = document.getElementById("promptDescription");
const promptGroupLabel = document.getElementById("promptGroupLabel");
const promptKeyLabel = document.getElementById("promptKeyLabel");
const promptOverrideBadge = document.getElementById("promptOverrideBadge");
const promptEditor = document.getElementById("promptEditor");
const promptDefault = document.getElementById("promptDefault");
const promptSaveStatus = document.getElementById("promptSaveStatus");
const savePromptBtn = document.getElementById("savePromptBtn");
const resetPromptBtn = document.getElementById("resetPromptBtn");

async function loadPrompts() {
    const response = await fetch("/api/nexus/prompts");
    const payload = await response.json();
    state.prompts = payload.prompts || [];
    renderPromptList();
    if (!state.selectedKey && state.prompts.length) {
        selectPrompt(state.prompts[0].key);
    }
}

function renderPromptList() {
    if (!state.prompts.length) {
        groupList.innerHTML = '<div class="empty-state">No hay prompts cargados.</div>';
        return;
    }
    const groups = state.prompts.reduce((acc, prompt) => {
        if (!acc[prompt.group]) {
            acc[prompt.group] = [];
        }
        acc[prompt.group].push(prompt);
        return acc;
    }, {});

    groupList.innerHTML = Object.entries(groups)
        .map(([group, prompts]) => `
            <section class="prompt-group">
                <p class="prompt-group-title">${escapeHtml(group)}</p>
                ${prompts.map((prompt) => `
                    <button class="prompt-nav-item ${prompt.key === state.selectedKey ? "active" : ""}" type="button" data-key="${escapeAttribute(prompt.key)}">
                        <strong>${escapeHtml(prompt.title)}</strong>
                        <span>${escapeHtml(prompt.description)}</span>
                    </button>
                `).join("")}
            </section>
        `)
        .join("");

    groupList.querySelectorAll("[data-key]").forEach((button) => {
        button.addEventListener("click", () => selectPrompt(button.dataset.key));
    });
}

function selectPrompt(key) {
    const prompt = state.prompts.find((item) => item.key === key);
    if (!prompt) {
        return;
    }
    state.selectedKey = key;
    promptTitle.textContent = prompt.title;
    promptDescription.textContent = prompt.description;
    promptGroupLabel.textContent = prompt.group;
    promptKeyLabel.textContent = prompt.key;
    promptOverrideBadge.textContent = prompt.is_overridden ? "override" : "default";
    promptEditor.value = prompt.current_text;
    promptDefault.textContent = prompt.default_text;
    promptSaveStatus.textContent = prompt.is_overridden ? "Override activo" : "Sin cambios";
    renderPromptList();
}

async function savePrompt() {
    if (!state.selectedKey) {
        return;
    }
    promptSaveStatus.textContent = "Guardando...";
    const response = await fetch(`/api/nexus/prompts/${encodeURIComponent(state.selectedKey)}`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({current_text: promptEditor.value}),
    });
    const payload = await response.json();
    if (!response.ok) {
        promptSaveStatus.textContent = payload.detail || "No se pudo guardar";
        return;
    }
    upsertPrompt(payload.prompt);
    selectPrompt(payload.prompt.key);
    promptSaveStatus.textContent = "Guardado";
}

async function resetPrompt() {
    if (!state.selectedKey) {
        return;
    }
    promptSaveStatus.textContent = "Reseteando...";
    const response = await fetch(`/api/nexus/prompts/${encodeURIComponent(state.selectedKey)}/reset`, {
        method: "POST",
    });
    const payload = await response.json();
    if (!response.ok) {
        promptSaveStatus.textContent = payload.detail || "No se pudo resetear";
        return;
    }
    upsertPrompt(payload.prompt);
    selectPrompt(payload.prompt.key);
    promptSaveStatus.textContent = "Reset aplicado";
}

function upsertPrompt(prompt) {
    const index = state.prompts.findIndex((item) => item.key === prompt.key);
    if (index === -1) {
        state.prompts.push(prompt);
        return;
    }
    state.prompts[index] = prompt;
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

function escapeAttribute(value) {
    return escapeHtml(value).replaceAll('"', "&quot;");
}

savePromptBtn.addEventListener("click", savePrompt);
resetPromptBtn.addEventListener("click", resetPrompt);
promptEditor.addEventListener("input", () => {
    promptSaveStatus.textContent = "Cambios sin guardar";
});

loadPrompts().catch((error) => {
    groupList.innerHTML = `<div class="empty-state">No he podido cargar los prompts: ${escapeHtml(error.message)}</div>`;
});
