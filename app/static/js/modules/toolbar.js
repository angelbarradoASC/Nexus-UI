// ==============================================================================
// NEXUS Platform - Toolbar Module
// Toolbar controls and agent selection
// ==============================================================================

import { state, setState } from '../core/state.js';

const appContainer = document.getElementById('appContainer');
const canvasPanel = document.getElementById('canvasPanel');

// Toggle tools (web, canvas, files)
export function toggleTool(tool) {
    const button = document.getElementById(tool + 'Toggle');
    if (!button) return;
    
    const isActive = button.classList.contains('active');
    
    if (tool === 'canvas') {
        setState('canvasActive', !isActive);
        
        if (!isActive) {
            button.classList.add('active');
            state.activeTools.push('canvas');
            if (canvasPanel) canvasPanel.classList.add('active');
            if (appContainer) appContainer.classList.add('canvas-active');
        } else {
            button.classList.remove('active');
            setState('activeTools', state.activeTools.filter(t => t !== 'canvas'));
            if (canvasPanel) canvasPanel.classList.remove('active');
            if (appContainer) appContainer.classList.remove('canvas-active');
        }
    } else {
        // Web, Files, etc.
        if (isActive) {
            button.classList.remove('active');
            setState('activeTools', state.activeTools.filter(t => t !== tool));
        } else {
            button.classList.add('active');
            state.activeTools.push(tool);
        }
    }
    
}

// Toggle sidebar (mobile)
export function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) {
        sidebar.classList.toggle('show');
    }
}

// Change agent type
export function changeAgent(agentType) {
    
    // Update UI
    const agentSelect = document.getElementById('agentSelect');
    if (agentSelect) {
        agentSelect.value = agentType;
    }
    
    // Store in state
    setState('selectedAgent', agentType);
    
    // Show notification
    const agentNames = {
        'general': 'Asistente General',
        'analyst': 'Analista de Datos',
        'coder': 'Generador de Código',
        'researcher': 'Investigador'
    };
    
    if (window.showNotification) {
        window.showNotification(`Agente cambiado: ${agentNames[agentType]}`, 'success');
    }
}

// Initialize toolbar
export function initToolbar() {
    // Agent selector
    const agentSelect = document.getElementById('agentSelect');
    if (agentSelect) {
        agentSelect.addEventListener('change', (e) => {
            changeAgent(e.target.value);
        });
    }
    
}

// Export public API
export default {
    toggleTool,
    toggleSidebar,
    changeAgent,
    initToolbar
};
