// ==============================================================================
// NEXUS Platform - Main Application Entry Point (Enhanced)
// Initializes all modules including new alerts and theme modules
// ==============================================================================

import { state, setState } from './core/state.js';
import { sendMessage, newChat, addMessage } from './modules/chat.js';
import { loadHistory, initHistoryModule } from './modules/history.js';
import { toggleTool, toggleSidebar, initToolbar } from './modules/toolbar.js';
import {
    switchCanvasTab,
    copyCanvasContent,
    downloadCanvasContent,
    saveCanvasEdits,
    focusCanvas,
    updateCanvasUI
} from './modules/canvas.js';
import { detectSpecialContent } from './utils/markdown.js';
import { showNotification } from './utils/notifications.js';
import { initAlertsModule, toggleAlertsPanel } from './modules/alerts.js';
import { initTheme, toggleTheme } from './modules/theme.js';

// Set username from template
const usernameElement = document.getElementById('username');
if (usernameElement) {
    setState('currentUsername', usernameElement.textContent.trim());
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', function() {

    setupEventListeners();
    initToolbar();
    initHistoryModule();
    initTheme();
    initAlertsModule();
    loadHistory();

    const messageInput = document.getElementById('messageInput');
    if (messageInput) messageInput.focus();

});

// Setup event listeners
function setupEventListeners() {
    const messageInput = document.getElementById('messageInput');
    const chatForm = document.getElementById('chatForm');

    if (!messageInput || !chatForm) {
        console.error('Critical elements not found');
        return;
    }

    // Auto-resize textarea
    messageInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });

    // Ctrl+Enter to send
    messageInput.addEventListener('keydown', function(e) {
        if (e.ctrlKey && e.key === 'Enter') {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit'));
        }
    });

    // Form submit
    chatForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const message = messageInput.value.trim();
        if (message) {
            sendMessage(message);
            messageInput.value = '';
            messageInput.style.height = 'auto';
        }
    });
}

// Expose functions to window for HTML onclick handlers
window.newChat = newChat;
window.toggleTool = toggleTool;
window.toggleSidebar = toggleSidebar;
window.switchCanvasTab = switchCanvasTab;
window.copyCanvasContent = copyCanvasContent;
window.downloadCanvasContent = downloadCanvasContent;
window.saveCanvasEdits = saveCanvasEdits;
window.focusCanvas = focusCanvas;
window.logout = () => window.location.href = '/logout';
window.toggleTheme = toggleTheme;
window.toggleAlertsPanel = toggleAlertsPanel;

// Expose utils to window
window.addMessage = addMessage;
window.loadHistory = loadHistory;
window.detectSpecialContent = detectSpecialContent;
window.showNotification = showNotification;
window.updateCanvasUI = updateCanvasUI;

// Expose state for debugging (development only)
if (window.location.hostname === 'localhost') {
    window.nexusState = state;
    window.nexusDebug = {
        state,
        sendMessage,
        loadHistory,
        newChat,
        toggleTheme,
        toggleAlertsPanel
    };
}

