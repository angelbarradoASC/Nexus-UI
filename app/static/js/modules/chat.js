// ==============================================================================
// NEXUS Platform - Chat Module (Production Ready)
// Message handling with retry logic, timeouts, and cleanup
// ==============================================================================

import { state, setState } from '../core/state.js';
import { sendChatMessage, openChatStream } from '../core/api.js';

const messagesContainer = document.getElementById('messagesContainer');
const welcomeScreen = document.getElementById('welcomeScreen');
const sendBtn = document.getElementById('sendBtn');

// Active timers / SSE for cleanup
const activeTimers = new Set();

// Constants
const MAX_RETRIES = 3;

// Helper: Sleep for retry logic
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// Helper: Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Send message with exponential backoff retry
async function sendMessageWithRetry(message, retries = MAX_RETRIES) {
    for (let i = 0; i < retries; i++) {
        try {
            return await sendChatMessage(message, state.selectedAgent || 'general');
        } catch (error) {
            if (i === retries - 1) throw error;
            const delay = Math.pow(2, i) * 1000; // 1s, 2s, 4s
            await sleep(delay);
        }
    }
}

export async function sendMessage(message) {
    if (state.isWelcomeShown) {
        welcomeScreen.style.display = 'none';
        setState('isWelcomeShown', false);
    }

    addMessage(message, true);
    showTypingIndicator();
    
    sendBtn.disabled = true;
    sendBtn.querySelector('span').textContent = 'Enviando...';

    try {
        const data = await sendMessageWithRetry(message);

        // Cerrar stream previo si lo hubiera
        if (state.activeStream) {
            state.activeStream.close();
            setState('activeStream', null);
        }

        setState('currentTaskId', data.task_id);

        // Crear burbuja de respuesta vacía donde irán llegando los chunks
        const { messageDiv, contentEl } = createStreamingBubble();

        const es = openChatStream(
            data.task_id,
            // onChunk — append texto parcial
            (chunk) => {
                contentEl.dataset.raw = (contentEl.dataset.raw || '') + chunk;
                // Renderizar markdown parcial en tiempo real
                contentEl.innerHTML = window.marked
                    ? marked.parse(contentEl.dataset.raw)
                    : escapeHtml(contentEl.dataset.raw);
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            },
            // onDone — metadata final
            (doneData) => {
                removeTypingIndicator();
                finalizeStreamingBubble(messageDiv, contentEl, doneData);
                resetSendButton();
                setState('currentTaskId', null);
                setState('activeStream', null);
                setTimeout(() => { if (window.loadHistory) window.loadHistory(); }, 1000);
            },
            // onError
            (errMsg) => {
                removeTypingIndicator();
                contentEl.innerHTML = escapeHtml(errMsg);
                resetSendButton();
                setState('currentTaskId', null);
                setState('activeStream', null);
            },
        );

        setState('activeStream', es);

    } catch (error) {
        removeTypingIndicator();
        addMessage('Error al enviar el mensaje después de varios intentos. Por favor, verifica tu conexión.', false);
        resetSendButton();
    }
}

/** Crea la burbuja vacía del asistente y devuelve referencias para actualizarla. */
function createStreamingBubble() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });

    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant streaming';

    const contentEl = document.createElement('div');
    contentEl.className = 'message-content streaming-content';
    contentEl.dataset.raw = '';

    messageDiv.innerHTML = `
        <div class="message-header">
            <div class="message-avatar">AI</div>
            <div class="message-author">NEXUS</div>
            <div class="message-time">${timeStr}</div>
        </div>
    `;
    messageDiv.appendChild(contentEl);
    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    return { messageDiv, contentEl };
}

/** Finaliza la burbuja streaming: renderiza markdown completo, añade thinking si existe. */
function finalizeStreamingBubble(messageDiv, contentEl, doneData) {
    messageDiv.classList.remove('streaming');

    const rawText = contentEl.dataset.raw || '';
    const parsed  = window.marked ? marked.parse(rawText) : escapeHtml(rawText);

    const thinking = doneData?.thinking || '';
    const thinkingHtml = thinking
        ? `<details style="margin-top:1rem;padding:0.5rem;background:var(--bg-primary);border-radius:6px;">
               <summary style="cursor:pointer;font-size:0.9rem;color:var(--text-muted);">
                   <i class="fas fa-brain"></i> Ver proceso de pensamiento
               </summary>
               <pre style="margin-top:0.5rem;font-size:0.8rem;color:var(--text-secondary);white-space:pre-wrap;">${escapeHtml(thinking)}</pre>
           </details>`
        : '';

    contentEl.innerHTML = parsed + thinkingHtml;

    if (window.Prism) Prism.highlightAllUnder(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

export function addMessage(content, isUser = false, thinking = null) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user' : 'assistant'}`;
    
    const now = new Date();
    const timeStr = now.toLocaleTimeString('es-ES', { 
        hour: '2-digit', 
        minute: '2-digit' 
    });

    // Detect special content for Canvas (if active)
    const specialContent = window.detectSpecialContent ? window.detectSpecialContent(content) : null;
    let displayContent = content;
    let canvasIndicator = '';

    if (!isUser && state.canvasActive && specialContent) {
        state.currentCanvasContent.original = specialContent.content;
        state.currentCanvasContent.edited = specialContent.content;
        state.currentCanvasContent.type = specialContent.type;
        state.currentCanvasContent.language = specialContent.language || 'text';
        
        if (window.updateCanvasUI) window.updateCanvasUI();
        
        displayContent = specialContent.summary || content.substring(0, 200) + '...';
        canvasIndicator = `<div class="canvas-indicator" onclick="window.focusCanvas()">
            <i class="fas fa-external-link-alt"></i> Ver contenido completo en Canvas
            <span style="background: rgba(255,255,255,0.2); padding: 0.2rem 0.4rem; border-radius: 3px; font-size: 0.8rem;">
                ${escapeHtml(specialContent.type)}
            </span>
        </div>`;
    }

    const parsedContent = window.marked ? marked.parse(displayContent) : escapeHtml(displayContent);
    
    // Sanitize thinking output to prevent XSS
    const thinkingHtml = thinking && !isUser ? 
        `<details style="margin-top: 1rem; padding: 0.5rem; background: var(--bg-primary); border-radius: 6px;">
            <summary style="cursor: pointer; font-size: 0.9rem; color: var(--text-muted);">
                <i class="fas fa-brain"></i> Ver proceso de pensamiento
            </summary>
            <pre style="margin-top: 0.5rem; font-size: 0.8rem; color: var(--text-secondary); white-space: pre-wrap;">${escapeHtml(thinking)}</pre>
        </details>` : '';

    messageDiv.innerHTML = `
        <div class="message-header">
            <div class="message-avatar">${isUser ? escapeHtml(state.currentUsername[0].toUpperCase()) : 'AI'}</div>
            <div class="message-author">${isUser ? escapeHtml(state.currentUsername) : 'NEXUS'}</div>
            <div class="message-time">${timeStr}</div>
        </div>
        <div class="message-content">
            ${parsedContent}
            ${canvasIndicator}
            ${thinkingHtml}
        </div>
    `;

    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    // Highlight code blocks
    if (window.Prism) {
        Prism.highlightAllUnder(messageDiv);
    }
}

function showTypingIndicator() {
    const typingDiv = document.createElement('div');
    typingDiv.className = 'typing-indicator';
    typingDiv.id = 'typingIndicator';
    
    const startTime = Date.now();
    
    typingDiv.innerHTML = `
        <div class="typing-dots">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
        <span style="font-size: 0.9rem; color: var(--text-muted);" id="typingTimer">Procesando...</span>
    `;
    
    messagesContainer.appendChild(typingDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    
    // Update timer display
    const updateTimer = setInterval(() => {
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        const timerSpan = document.getElementById('typingTimer');
        if (timerSpan) {
            timerSpan.textContent = `Procesando... (${elapsed}s)`;
        } else {
            clearInterval(updateTimer);
            activeTimers.delete(updateTimer);
        }
    }, 1000);
    
    activeTimers.add(updateTimer);
}

function removeTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) {
        indicator.remove();
    }
    
    // Cleanup all active timers
    activeTimers.forEach(timer => clearInterval(timer));
    activeTimers.clear();
}

function resetSendButton() {
    sendBtn.disabled = false;
    sendBtn.querySelector('span').textContent = 'Enviar';
}

export function newChat() {
    // Cerrar stream activo si lo hay
    if (state.activeStream) {
        state.activeStream.close();
        setState('activeStream', null);
    }
    
    // Cleanup typing indicators
    removeTypingIndicator();
    
    // Reset UI
    document.querySelectorAll('.history-item').forEach(item => {
        item.classList.remove('active');
    });
    
    messagesContainer.innerHTML = '';
    const welcomeDiv = document.createElement('div');
    welcomeDiv.className = 'welcome-screen';
    welcomeDiv.id = 'welcomeScreen';
    welcomeDiv.innerHTML = `
        <h2 class="welcome-title">Bienvenido a NEXUS</h2>
        <p class="welcome-subtitle">Part Of JAINA · listo para trabajar</p>
    `;
    messagesContainer.appendChild(welcomeDiv);
    setState('isWelcomeShown', true);
    
    const input = document.getElementById('messageInput');
    if (input) input.focus();
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (state.activeStream) {
        state.activeStream.close();
    }
    removeTypingIndicator();
});