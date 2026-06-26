function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

let latestOutreachCampaignId = null;
let latestProspectingRunId = null;
let latestProspectingResults = [];

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
    if (value === "degraded" || value === "running" || value === "searching" || value === "extracting" || value === "validating" || value === "scoring" || value === "pending") return "degraded";
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

function renderProspectingResults(items) {
    const tbody = document.getElementById("prospectingResultsBody");
    if (!tbody) return;
    if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="12" class="empty-table">Sin resultados todavia.</td></tr>';
        return;
    }
    tbody.innerHTML = items.map((item) => `
        <tr>
            <td>${escapeHtml(item.name || "")}</td>
            <td>${escapeHtml(item.vertical || "-")}</td>
            <td>${escapeHtml(item.city || item.province || "-")}</td>
            <td>${item.website ? `<a href="${escapeHtml(item.website)}" target="_blank" rel="noreferrer">abrir</a>` : "-"}</td>
            <td>${escapeHtml(item.email || "-")}</td>
            <td>${escapeHtml(item.phone || "-")}</td>
            <td><span class="pill">${escapeHtml(item.score ?? 0)}</span></td>
            <td>${escapeHtml(item.priority || "-")}</td>
            <td>${item.crm_duplicate ? '<span class="pill">duplicado</span>' : escapeHtml(item.crm_state || "pendiente")}</td>
            <td>${escapeHtml(item.reason || item.discard_reason || "-")}</td>
            <td>${item.source_url ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">fuente</a>` : "-"}</td>
            <td class="prospecting-actions-cell">
                <button class="btn btn-small btn-secondary" type="button" data-action="evidence" data-result-id="${escapeHtml(item.result_id)}">Evidencia</button>
                <button class="btn btn-small" type="button" data-action="push" data-result-id="${escapeHtml(item.result_id)}">CRM</button>
            </td>
        </tr>
    `).join("");
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
        message.textContent = `Run ${run.run_id || ""}: ${summary.usable_results ?? 0} utiles - ${summary.discarded ?? 0} descartados - ${summary.duplicates ?? 0} duplicados.${queries ? ` Queries: ${queries}` : ""}`;
    }
}

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
            renderFeed("prospectingFeed", [], () => "", "Todavia no hay runs de prospeccion.");
            renderProspectingResults([]);
            return;
        }
        const run = await requestJson(`/api/nexus/prospecting/runs/${encodeURIComponent(runId)}`);
        latestProspectingRunId = run.run_id;
        latestProspectingResults = run.results || [];
        renderProspectingSummary(run);
        renderProspectingResults(latestProspectingResults);
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

function splitCsvList(value) {
    return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

async function runProspecting(event) {
    event.preventDefault();
    const payload = {
        vertical: document.getElementById("prospectingVertical")?.value || "public_administration",
        target_description: document.getElementById("prospectingTargetDescription")?.value.trim() || "",
        city: document.getElementById("prospectingCity")?.value.trim() || "",
        province: document.getElementById("prospectingProvince")?.value.trim() || "",
        region: document.getElementById("prospectingRegion")?.value.trim() || "",
        radius_km: Number(document.getElementById("prospectingRadius")?.value || 35),
        desired_count: Number(document.getElementById("prospectingDesiredCount")?.value || 20),
        minimum_score: Number(document.getElementById("prospectingMinimumScore")?.value || 50),
        must_have: splitCsvList(document.getElementById("prospectingMustHave")?.value || ""),
        nice_to_have: splitCsvList(document.getElementById("prospectingNiceToHave")?.value || ""),
        exclude: splitCsvList(document.getElementById("prospectingExclude")?.value || ""),
        crm_tags: splitCsvList(document.getElementById("prospectingCrmTags")?.value || ""),
        dry_run: document.getElementById("prospectingDryRun")?.checked !== false,
        async_mode: document.getElementById("prospectingAsyncMode")?.checked === true,
    };
    const message = document.getElementById("prospectingResultMessage");
    if (!payload.city && !payload.province && !payload.region) {
        if (message) message.textContent = "Necesito al menos una ciudad, provincia o region para arrancar.";
        return;
    }
    if (message) message.textContent = payload.async_mode ? "Cola de prospeccion enviada..." : "Lanzando prospeccion...";
    try {
        const response = await requestJson("/api/nexus/prospecting/run", {
            method: "POST",
            body: JSON.stringify(payload),
        });
        latestProspectingRunId = response.run_id;
        if (payload.async_mode) {
            if (message) message.textContent = `Run ${response.run_id} en marcha. Usa Recargar para revisar progreso.`;
            await loadProspecting(response.run_id);
            return;
        }
        await loadProspecting(response.run_id);
    } catch (error) {
        if (message) message.textContent = `Error al prospectar: ${error.message}`;
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
        latestProspectingRunId = response.run_id;
        await loadProspecting(response.run_id);
    } catch (error) {
        if (message) message.textContent = `No se pudo reanudar el run: ${error.message}`;
    }
}

async function pushValidResults() {
    const message = document.getElementById("crmSyncResult");
    if (!latestProspectingRunId) {
        if (message) message.textContent = "Todavia no hay ningun run de prospeccion para empujar al CRM.";
        return;
    }
    if (message) message.textContent = "Empujando resultados validos al CRM...";
    try {
        const response = await requestJson("/api/nexus/prospecting/push-valid-to-crm", {
            method: "POST",
            body: JSON.stringify({ run_id: latestProspectingRunId, dry_run: true }),
        });
        if (message) message.textContent = `${response.pushed_count || 0} resultados preparados para CRM en modo preview.`;
    } catch (error) {
        if (message) message.textContent = `No se pudo preparar el CRM: ${error.message}`;
    }
}

async function pushSingleResult(resultId) {
    const message = document.getElementById("crmSyncResult");
    if (message) message.textContent = "Preparando el resultado para CRM...";
    try {
        const response = await requestJson(`/api/nexus/prospecting/results/${encodeURIComponent(resultId)}/push-to-crm`, {
            method: "POST",
            body: JSON.stringify({ dry_run: true }),
        });
        if (message) {
            message.textContent = response.company_payload
                ? `Preview CRM listo para ${response.company_payload.name}.`
                : "Resultado preparado para CRM.";
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
        if (message) {
            message.textContent = discarded.length
                ? discarded.slice(0, 3).map((item) => `${item.name}: ${item.discard_reason}`).join(" - ")
                : "No hay descartados en este run.";
        }
    } catch (error) {
        if (message) message.textContent = `No se pudieron cargar los descartados: ${error.message}`;
    }
}

function showEvidence(resultId) {
    const result = latestProspectingResults.find((item) => item.result_id === resultId);
    const message = document.getElementById("prospectingResultMessage");
    if (!result || !message) return;
    const evidence = [result.source_url, ...(result.evidence_urls || [])].filter(Boolean);
    message.innerHTML = evidence.length
        ? evidence.map((url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(url)}</a>`).join("<br>")
        : "No hay evidencia adicional para este resultado.";
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

document.addEventListener("DOMContentLoaded", async () => {
    document.getElementById("prospectingForm")?.addEventListener("submit", runProspecting);
    document.getElementById("refreshProspectingBtn")?.addEventListener("click", () => loadProspecting());
    document.getElementById("pushValidProspectsBtn")?.addEventListener("click", pushValidResults);
    document.getElementById("loadDiscardedBtn")?.addEventListener("click", loadDiscarded);
    document.getElementById("resumeProspectingBtn")?.addEventListener("click", resumeProspecting);
    document.getElementById("outreachForm")?.addEventListener("submit", launchOutreach);
    document.getElementById("outreachDailyCap")?.addEventListener("input", (event) => {
        if (event.target instanceof HTMLInputElement) {
            event.target.dataset.userTouched = "true";
        }
    });
    document.getElementById("prospectingResultsBody")?.addEventListener("click", async (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        const action = target.dataset.action;
        const resultId = target.dataset.resultId;
        if (!action || !resultId) return;
        if (action === "push") {
            await pushSingleResult(resultId);
        } else if (action === "evidence") {
            showEvidence(resultId);
        }
    });
    document.querySelectorAll(".tab-chip").forEach((button) => {
        button.addEventListener("click", () => {
            document.querySelectorAll(".tab-chip").forEach((chip) => chip.classList.remove("active"));
            button.classList.add("active");
            const target = button.dataset.feedTab;
            ["prospecting", "outreach", "activity"].forEach((name) => {
                const feed = document.getElementById(`${name}Feed`);
                if (feed) feed.classList.toggle("hidden-feed", name !== target);
            });
        });
    });

    await Promise.all([loadOutreach(), loadCRMStatus(), loadAuditActivity(), loadProspecting()]);
});
