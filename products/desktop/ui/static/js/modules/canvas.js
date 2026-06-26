// ==============================================================================
// NEXUS Platform - Canvas Module
// Canvas panel functionality with version control
// ==============================================================================

import { state, updateCanvasContent } from '../core/state.js';
import { saveCanvasEdits as apiSaveCanvasEdits } from '../core/api.js';

const appContainer = document.getElementById('appContainer');
const canvasPanel = document.getElementById('canvasPanel');
const canvasEditor = document.getElementById('canvasEditor');
const canvasPreview = document.getElementById('canvasPreview');
const canvasType = document.getElementById('canvasType');

// Track if there are unsaved changes
let hasUnsavedChanges = false;

// Update Canvas UI with content
export function updateCanvasUI() {
    if (!canvasEditor) return;
    
    canvasEditor.value = state.currentCanvasContent.original;
    canvasType.textContent = state.currentCanvasContent.type;
    switchCanvasTab('original');
    hasUnsavedChanges = false;
}

// Focus/open Canvas panel
export function focusCanvas() {
    if (!canvasPanel || !appContainer) return;
    
    if (!canvasPanel.classList.contains('active')) {
        canvasPanel.classList.add('active');
        appContainer.classList.add('canvas-active');
    }
}

// Close Canvas panel
export function closeCanvas() {
    if (!canvasPanel || !appContainer) return;
    
    // Warn if unsaved changes
    if (hasUnsavedChanges) {
        if (!confirm('Tienes cambios sin guardar. ¿Cerrar de todos modos?')) {
            return;
        }
    }
    
    canvasPanel.classList.remove('active');
    appContainer.classList.remove('canvas-active');
    hasUnsavedChanges = false;
}

// Switch between tabs (original/edited/preview)
export function switchCanvasTab(tab) {
    if (!canvasEditor || !canvasPreview) return;
    
    state.currentActiveTab = tab;
    
    // Update tab UI
    document.querySelectorAll('.canvas-tab').forEach(t => {
        t.classList.remove('active');
    });
    const activeTab = document.querySelector(`[data-tab="${tab}"]`);
    if (activeTab) {
        activeTab.classList.add('active');
    }

    // Hide all content
    canvasEditor.classList.add('hidden');
    canvasPreview.classList.add('hidden');

    // Show selected content
    if (tab === 'original') {
        canvasEditor.classList.remove('hidden');
        canvasEditor.value = state.currentCanvasContent.original;
        canvasEditor.readOnly = true;
        canvasEditor.style.background = 'var(--bg-primary)';
        canvasEditor.style.cursor = 'default';
    } else if (tab === 'edited') {
        canvasEditor.classList.remove('hidden');
        canvasEditor.value = state.currentCanvasContent.edited || state.currentCanvasContent.original;
        canvasEditor.readOnly = false;
        canvasEditor.style.background = 'var(--bg-tertiary)';
        canvasEditor.style.cursor = 'text';
        canvasEditor.focus();
    } else if (tab === 'preview') {
        canvasPreview.classList.remove('hidden');
        renderPreview();
    }
}

// Render preview based on content type
function renderPreview() {
    if (!canvasPreview) return;
    
    const content = state.currentCanvasContent.edited || state.currentCanvasContent.original;
    
    if (state.currentCanvasContent.type === 'Código') {
        // Code preview with syntax highlighting
        const language = state.currentCanvasContent.language || 'text';
        canvasPreview.innerHTML = `<pre><code class="language-${language}">${escapeHtml(content)}</code></pre>`;
        
        if (window.Prism) {
            Prism.highlightAllUnder(canvasPreview);
        }
    } else if (state.currentCanvasContent.type === 'JSON') {
        // Pretty print JSON
        try {
            const parsed = JSON.parse(content);
            const formatted = JSON.stringify(parsed, null, 2);
            canvasPreview.innerHTML = `<pre><code class="language-json">${escapeHtml(formatted)}</code></pre>`;
            
            if (window.Prism) {
                Prism.highlightAllUnder(canvasPreview);
            }
        } catch (e) {
            canvasPreview.innerHTML = `<div style="color: var(--accent-red); padding: 1rem;">Error: JSON inválido<br><br>${escapeHtml(e.message)}</div>`;
        }
    } else {
        // Markdown or plain text
        if (window.marked) {
            canvasPreview.innerHTML = marked.parse(content);
        } else {
            canvasPreview.innerHTML = `<pre>${escapeHtml(content)}</pre>`;
        }
    }
}

// Copy content to clipboard
export function copyCanvasContent() {
    const content = state.currentActiveTab === 'edited' ? 
        (state.currentCanvasContent.edited || state.currentCanvasContent.original) : 
        state.currentCanvasContent.original;
    
    navigator.clipboard.writeText(content).then(() => {
        if (window.showNotification) {
            window.showNotification('Contenido copiado al portapapeles', 'success');
        } else {
        }
    }).catch(err => {
        console.error('Failed to copy:', err);
        if (window.showNotification) {
            window.showNotification('Error al copiar', 'error');
        }
    });
}

// Download content as file
export function downloadCanvasContent() {
    const content = state.currentActiveTab === 'edited' ? 
        (state.currentCanvasContent.edited || state.currentCanvasContent.original) : 
        state.currentCanvasContent.original;
    
    // Determine file extension
    const extensionMap = {
        'markdown': 'md',
        'json': 'json',
        'javascript': 'js',
        'python': 'py',
        'html': 'html',
        'css': 'css',
        'text': 'txt'
    };
    
    const extension = extensionMap[state.currentCanvasContent.language] || 'txt';
    const filename = `nexus-canvas-${Date.now()}.${extension}`;
    
    // Create blob and download
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
    if (window.showNotification) {
        window.showNotification(`Archivo descargado: ${filename}`, 'success');
    }
}

// Save edited content
export async function saveCanvasEdits() {
    const edited = state.currentCanvasContent.edited;
    const original = state.currentCanvasContent.original;
    
    // Check if there are changes
    if (!edited || edited === original) {
        if (window.showNotification) {
            window.showNotification('No hay cambios para guardar', 'warning');
        }
        return;
    }

    // Check if we have a conversation ID
    if (!state.currentConversationId) {
        if (window.showNotification) {
            window.showNotification('No hay conversación activa', 'error');
        }
        return;
    }

    try {
        await apiSaveCanvasEdits(state.currentConversationId, {
            type: state.currentCanvasContent.type,
            language: state.currentCanvasContent.language,
            original: original,
            edited: edited
        });

        hasUnsavedChanges = false;
        
        if (window.showNotification) {
            window.showNotification('Cambios guardados correctamente', 'success');
        }
        
        
    } catch (error) {
        console.error('Failed to save canvas edits:', error);
        
        if (window.showNotification) {
            window.showNotification('Error al guardar cambios', 'error');
        }
    }
}

// Helper: Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Track changes in editor
if (canvasEditor) {
    canvasEditor.addEventListener('input', function() {
        updateCanvasContent({ edited: this.value });
        hasUnsavedChanges = true;
        
        // Update save button visual state
        const saveBtn = document.querySelector('.canvas-btn.save');
        if (saveBtn && hasUnsavedChanges) {
            saveBtn.style.animation = 'pulse 1s infinite';
        }
    });
}

// Warn before closing with unsaved changes
window.addEventListener('beforeunload', (e) => {
    if (hasUnsavedChanges) {
        e.preventDefault();
        e.returnValue = '';
    }
});

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    // Ctrl+S to save
    if (e.ctrlKey && e.key === 's') {
        e.preventDefault();
        if (canvasPanel && canvasPanel.classList.contains('active')) {
            saveCanvasEdits();
        }
    }
    
    // Escape to close canvas
    if (e.key === 'Escape') {
        if (canvasPanel && canvasPanel.classList.contains('active')) {
            closeCanvas();
        }
    }
});

// Export public API
export default {
    updateCanvasUI,
    focusCanvas,
    closeCanvas,
    switchCanvasTab,
    copyCanvasContent,
    downloadCanvasContent,
    saveCanvasEdits
};
