// ==============================================================================
// NEXUS Platform - Notifications Utils
// Toasts, alerts and UI feedback
// ==============================================================================

const messagesContainer = document.getElementById('messagesContainer');

// Show typing indicator
export function showTypingIndicator() {
    if (!messagesContainer) return;
    
    const typingDiv = document.createElement('div');
    typingDiv.className = 'typing-indicator';
    typingDiv.id = 'typingIndicator';
    typingDiv.innerHTML = `
        <div class="typing-dots">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
        <span style="font-size: 0.9rem; color: var(--text-muted);">Procesando...</span>
    `;
    messagesContainer.appendChild(typingDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// Remove typing indicator
export function removeTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) indicator.remove();
}

// Show toast notification
export function showNotification(message, type = 'success') {
    const notification = document.createElement('div');
    
    const colors = {
        'success': 'var(--accent-green)',
        'warning': 'var(--accent-orange)',
        'error': 'var(--accent-red)',
        'info': 'var(--accent-blue)'
    };
    
    const icons = {
        'success': 'fa-check-circle',
        'warning': 'fa-exclamation-triangle',
        'error': 'fa-times-circle',
        'info': 'fa-info-circle'
    };
    
    notification.style.cssText = `
        position: fixed;
        top: 80px;
        right: 20px;
        background: ${colors[type] || colors.success};
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 6px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        z-index: 10000;
        animation: slideIn 0.3s ease;
        display: flex;
        align-items: center;
        gap: 0.75rem;
        max-width: 400px;
    `;
    
    notification.innerHTML = `
        <i class="fas ${icons[type] || icons.success}"></i>
        <span>${message}</span>
    `;
    
    document.body.appendChild(notification);
    
    // Auto-dismiss after 3 seconds
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
    
    return notification;
}

// Show confirmation dialog
export function showConfirm(message, onConfirm, onCancel) {
    const overlay = document.createElement('div');
    overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.7);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10001;
        animation: fadeIn 0.2s ease;
    `;
    
    const dialog = document.createElement('div');
    dialog.style.cssText = `
        background: var(--bg-secondary);
        border: 1px solid var(--border-primary);
        border-radius: 8px;
        padding: 1.5rem;
        max-width: 400px;
        width: 90%;
    `;
    
    dialog.innerHTML = `
        <div style="font-size: 1.1rem; margin-bottom: 1rem; color: var(--text-primary);">
            ${message}
        </div>
        <div style="display: flex; gap: 0.5rem; justify-content: flex-end;">
            <button class="cancel-btn" style="background: var(--bg-tertiary); color: var(--text-secondary); border: 1px solid var(--border-primary); border-radius: 6px; padding: 0.5rem 1rem; cursor: pointer;">
                Cancelar
            </button>
            <button class="confirm-btn" style="background: var(--accent-blue); color: white; border: none; border-radius: 6px; padding: 0.5rem 1rem; cursor: pointer;">
                Confirmar
            </button>
        </div>
    `;
    
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    
    // Event handlers
    dialog.querySelector('.cancel-btn').addEventListener('click', () => {
        overlay.remove();
        if (onCancel) onCancel();
    });
    
    dialog.querySelector('.confirm-btn').addEventListener('click', () => {
        overlay.remove();
        if (onConfirm) onConfirm();
    });
    
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            overlay.remove();
            if (onCancel) onCancel();
        }
    });
}

// Export for window access
if (typeof window !== 'undefined') {
    window.showNotification = showNotification;
    window.showConfirm = showConfirm;
}

export default {
    showTypingIndicator,
    removeTypingIndicator,
    showNotification,
    showConfirm
};