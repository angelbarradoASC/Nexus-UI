// ==============================================================================
// NEXUS Platform - Alerts Module (Prometheus/AlertManager Integration)
// Drag & Drop de alertas al chat para analisis automatico
// ==============================================================================

import { state, setState } from '../core/state.js';
import { sendMessage } from './chat.js';

const alertsPanel = document.getElementById('alertsPanel');
const alertsList = document.getElementById('alertsList');
const alertsToggle = document.getElementById('alertsToggle');
const messagesContainer = document.getElementById('messagesContainer');

// Estado del modulo
const alertsState = {
    alerts: [],
    polling: null,
    isOpen: false,
    filter: 'all', // all, firing, resolved
    severity: 'all' // all, critical, warning, info
};

// Configuracion desde env o defaults
const ALERTMANAGER_URL = window.NEXUS_CONFIG?.alertmanager_url || 'http://192.168.1.150:9094';
const PROMETHEUS_URL = window.NEXUS_CONFIG?.prometheus_url || 'http://192.168.1.150:9090';
const POLL_INTERVAL = 30000; // 30 segundos

// Inicializar modulo
export function initAlertsModule() {
    if (!alertsPanel || !alertsList) {
        console.warn('Alerts panel elements not found');
        return;
    }

    setupEventListeners();
    loadAlerts();
    startPolling();
    
}

// Setup event listeners
function setupEventListeners() {
    // Toggle panel
    if (alertsToggle) {
        alertsToggle.addEventListener('click', toggleAlertsPanel);
    }

    // Close panel button
    const closeBtn = alertsPanel?.querySelector('.alerts-close-btn');
    if (closeBtn) {
        closeBtn.addEventListener('click', toggleAlertsPanel);
    }

    // Filter buttons
    const filterBtns = alertsPanel?.querySelectorAll('[data-filter]');
    filterBtns?.forEach(btn => {
        btn.addEventListener('click', () => {
            alertsState.filter = btn.dataset.filter;
            updateFilterUI();
            renderAlerts();
        });
    });

    // Severity filter
    const severitySelect = alertsPanel?.querySelector('#alertSeverityFilter');
    if (severitySelect) {
        severitySelect.addEventListener('change', (e) => {
            alertsState.severity = e.target.value;
            renderAlerts();
        });
    }

    // Setup drop zone en el chat
    setupChatDropZone();

    // Refresh button
    const refreshBtn = alertsPanel?.querySelector('.alerts-refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            loadAlerts();
            showRefreshAnimation(refreshBtn);
        });
    }
}

// Toggle panel
export function toggleAlertsPanel() {
    alertsState.isOpen = !alertsState.isOpen;
    
    if (alertsState.isOpen) {
        alertsPanel?.classList.add('open');
        loadAlerts();
    } else {
        alertsPanel?.classList.remove('open');
    }

    // Update toggle button
    if (alertsToggle) {
        alertsToggle.classList.toggle('active', alertsState.isOpen);
    }
}

// Cargar alertas desde AlertManager
export async function loadAlerts() {
    try {
        showLoadingSkeleton();

        // Fetch desde AlertManager API
        const response = await fetch(`${ALERTMANAGER_URL}/api/v2/alerts`, {
            headers: { 'Accept': 'application/json' }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const alerts = await response.json();
        alertsState.alerts = processAlerts(alerts);
        
        renderAlerts();
        updateAlertsBadge();

    } catch (error) {
        console.error('Error loading alerts:', error);
        showErrorState(error.message);
    }
}

// Procesar y enriquecer alertas
function processAlerts(rawAlerts) {
    return rawAlerts.map(alert => {
        const labels = alert.labels || {};
        const annotations = alert.annotations || {};
        
        return {
            id: generateAlertId(alert),
            name: labels.alertname || 'Unknown Alert',
            severity: labels.severity || 'info',
            status: alert.status?.state || 'unknown',
            instance: labels.instance || 'N/A',
            job: labels.job || 'N/A',
            description: annotations.description || annotations.summary || 'No description',
            startsAt: alert.startsAt,
            endsAt: alert.endsAt,
            labels: labels,
            annotations: annotations,
            fingerprint: alert.fingerprint
        };
    });
}

// Generar ID unico para alerta
function generateAlertId(alert) {
    return alert.fingerprint || `${alert.labels?.alertname}-${alert.startsAt}`;
}

// Renderizar alertas
function renderAlerts() {
    if (!alertsList) return;

    // Filtrar
    let filtered = alertsState.alerts;

    if (alertsState.filter !== 'all') {
        filtered = filtered.filter(a => a.status === alertsState.filter);
    }

    if (alertsState.severity !== 'all') {
        filtered = filtered.filter(a => a.severity === alertsState.severity);
    }

    // Ordenar por severidad y tiempo
    const severityOrder = { critical: 0, warning: 1, info: 2 };
    filtered.sort((a, b) => {
        const sevDiff = (severityOrder[a.severity] || 3) - (severityOrder[b.severity] || 3);
        if (sevDiff !== 0) return sevDiff;
        return new Date(b.startsAt) - new Date(a.startsAt);
    });

    // Renderizar
    if (filtered.length === 0) {
        alertsList.innerHTML = `
            <div class="alerts-empty">
                <i class="fas fa-check-circle"></i>
                <p>No hay alertas activas</p>
            </div>
        `;
        return;
    }

    alertsList.innerHTML = filtered.map(alert => createAlertCard(alert)).join('');

    // Setup drag & drop para cada alerta
    alertsList.querySelectorAll('.alert-card').forEach(card => {
        setupAlertDragDrop(card);
    });
}

// Crear card de alerta
function createAlertCard(alert) {
    const severityIcons = {
        critical: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };

    const icon = severityIcons[alert.severity] || 'fa-bell';
    const duration = calculateDuration(alert.startsAt);

    return `
        <div class="alert-card severity-${alert.severity}" 
             data-alert-id="${alert.id}"
             draggable="true">
            <div class="alert-header">
                <div class="alert-icon">
                    <i class="fas ${icon}"></i>
                </div>
                <div class="alert-title-section">
                    <div class="alert-name">${escapeHtml(alert.name)}</div>
                    <div class="alert-meta">
                        <span class="alert-instance">${escapeHtml(alert.instance)}</span>
                        <span class="alert-duration">${duration}</span>
                    </div>
                </div>
                <div class="alert-severity-badge badge-${alert.severity}">
                    ${alert.severity}
                </div>
            </div>
            <div class="alert-description">
                ${escapeHtml(alert.description)}
            </div>
            <div class="alert-actions">
                <button class="alert-action-btn" onclick="window.analyzeAlert('${alert.id}')">
                    <i class="fas fa-brain"></i> Analizar
                </button>
                <button class="alert-action-btn" onclick="window.viewAlertDetails('${alert.id}')">
                    <i class="fas fa-info"></i> Detalles
                </button>
            </div>
        </div>
    `;
}

// Setup drag & drop para una alerta
function setupAlertDragDrop(card) {
    const alertId = card.dataset.alertId;

    card.addEventListener('dragstart', (e) => {
        const alert = alertsState.alerts.find(a => a.id === alertId);
        if (!alert) return;

        e.dataTransfer.effectAllowed = 'copy';
        e.dataTransfer.setData('text/plain', formatAlertForChat(alert));
        e.dataTransfer.setData('application/json', JSON.stringify(alert));
        
        card.classList.add('dragging');
        
        // Visual feedback
        if (messagesContainer) {
            messagesContainer.classList.add('drop-target-active');
        }
    });

    card.addEventListener('dragend', () => {
        card.classList.remove('dragging');
        if (messagesContainer) {
            messagesContainer.classList.remove('drop-target-active');
        }
    });
}

// Setup drop zone en el chat
function setupChatDropZone() {
    if (!messagesContainer) return;

    messagesContainer.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
        messagesContainer.classList.add('drag-over');
    });

    messagesContainer.addEventListener('dragleave', (e) => {
        if (e.target === messagesContainer) {
            messagesContainer.classList.remove('drag-over');
        }
    });

    messagesContainer.addEventListener('drop', (e) => {
        e.preventDefault();
        messagesContainer.classList.remove('drag-over', 'drop-target-active');

        try {
            const alertData = e.dataTransfer.getData('application/json');
            if (!alertData) return;

            const alert = JSON.parse(alertData);
            handleAlertDrop(alert);

        } catch (error) {
            console.error('Error handling alert drop:', error);
        }
    });
}

// Manejar drop de alerta
function handleAlertDrop(alert) {
    const message = `Analiza esta alerta de Prometheus:

Nombre: ${alert.name}
Severidad: ${alert.severity}
Estado: ${alert.status}
Instancia: ${alert.instance}
Descripcion: ${alert.description}

Proporciona:
1. Analisis del problema
2. Posibles causas
3. Pasos de resolucion recomendados
4. Scripts o comandos utiles`;

    // Enviar mensaje al chat
    if (sendMessage) {
        sendMessage(message);
        
        // Notificacion visual
        if (window.showNotification) {
            window.showNotification('Alerta enviada para analisis', 'success');
        }
    }
}

// Formatear alerta para texto
function formatAlertForChat(alert) {
    return `[ALERT] ${alert.name} - ${alert.severity} - ${alert.instance}`;
}

// Analizar alerta (boton)
export function analyzeAlert(alertId) {
    const alert = alertsState.alerts.find(a => a.id === alertId);
    if (!alert) return;

    handleAlertDrop(alert);
}

// Ver detalles de alerta
export function viewAlertDetails(alertId) {
    const alert = alertsState.alerts.find(a => a.id === alertId);
    if (!alert) return;

    // Modal con detalles completos
    showAlertDetailsModal(alert);
}

// Mostrar modal de detalles
function showAlertDetailsModal(alert) {
    const modal = document.createElement('div');
    modal.className = 'alert-details-modal';
    modal.innerHTML = `
        <div class="alert-details-content">
            <div class="alert-details-header">
                <h3>${escapeHtml(alert.name)}</h3>
                <button class="modal-close-btn" onclick="this.closest('.alert-details-modal').remove()">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <div class="alert-details-body">
                <div class="detail-section">
                    <h4>Estado</h4>
                    <div class="detail-grid">
                        <div class="detail-item">
                            <span class="detail-label">Severidad:</span>
                            <span class="badge-${alert.severity}">${alert.severity}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Estado:</span>
                            <span>${alert.status}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Inicio:</span>
                            <span>${formatTimestamp(alert.startsAt)}</span>
                        </div>
                    </div>
                </div>
                <div class="detail-section">
                    <h4>Labels</h4>
                    <div class="labels-list">
                        ${Object.entries(alert.labels).map(([k, v]) => 
                            `<div class="label-tag">${escapeHtml(k)}: ${escapeHtml(v)}</div>`
                        ).join('')}
                    </div>
                </div>
                <div class="detail-section">
                    <h4>Descripcion</h4>
                    <p>${escapeHtml(alert.description)}</p>
                </div>
            </div>
            <div class="alert-details-footer">
                <button class="btn-primary" onclick="window.analyzeAlert('${alert.id}'); this.closest('.alert-details-modal').remove();">
                    <i class="fas fa-brain"></i> Analizar con IA
                </button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // Close on backdrop click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.remove();
        }
    });
}

// Actualizar badge de alertas
function updateAlertsBadge() {
    const badge = document.getElementById('alertsBadge');
    if (!badge) return;

    const firingAlerts = alertsState.alerts.filter(a => a.status === 'firing');
    const criticalCount = firingAlerts.filter(a => a.severity === 'critical').length;

    if (firingAlerts.length > 0) {
        badge.textContent = firingAlerts.length;
        badge.style.display = 'flex';
        badge.className = criticalCount > 0 ? 'alerts-badge critical' : 'alerts-badge warning';
    } else {
        badge.style.display = 'none';
    }
}

// Polling automatico
function startPolling() {
    if (alertsState.polling) {
        clearInterval(alertsState.polling);
    }

    alertsState.polling = setInterval(() => {
        if (alertsState.isOpen) {
            loadAlerts();
        }
    }, POLL_INTERVAL);
}

// Cleanup
export function cleanup() {
    if (alertsState.polling) {
        clearInterval(alertsState.polling);
        alertsState.polling = null;
    }
}

// Helpers
function calculateDuration(startsAt) {
    const start = new Date(startsAt);
    const now = new Date();
    const diff = now - start;

    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (days > 0) return `${days}d ${hours % 24}h`;
    if (hours > 0) return `${hours}h ${minutes % 60}m`;
    return `${minutes}m`;
}

function formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleString('es-ES', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

function updateFilterUI() {
    const filterBtns = alertsPanel?.querySelectorAll('[data-filter]');
    filterBtns?.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === alertsState.filter);
    });
}

function showLoadingSkeleton() {
    if (!alertsList) return;
    alertsList.innerHTML = `
        <div class="alerts-loading">
            <div class="skeleton-alert"></div>
            <div class="skeleton-alert"></div>
            <div class="skeleton-alert"></div>
        </div>
    `;
}

function showErrorState(message) {
    if (!alertsList) return;
    alertsList.innerHTML = `
        <div class="alerts-error">
            <i class="fas fa-exclamation-triangle"></i>
            <p>Error al cargar alertas</p>
            <small>${escapeHtml(message)}</small>
        </div>
    `;
}

function showRefreshAnimation(btn) {
    const icon = btn.querySelector('i');
    if (!icon) return;
    
    icon.classList.add('fa-spin');
    setTimeout(() => {
        icon.classList.remove('fa-spin');
    }, 1000);
}

// Cleanup on unload
window.addEventListener('beforeunload', cleanup);

// Expose to window
window.analyzeAlert = analyzeAlert;
window.viewAlertDetails = viewAlertDetails;

export default {
    initAlertsModule,
    toggleAlertsPanel,
    loadAlerts,
    analyzeAlert,
    viewAlertDetails,
    cleanup
};
