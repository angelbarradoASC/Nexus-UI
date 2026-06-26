// ==============================================================================
// NEXUS Platform - API Client
// Centralized fetch calls (ready for telemetry)
// ==============================================================================

export async function sendChatMessage(message, selectedAgent = 'general') {
    const formData = new FormData();
    formData.append('user_message', message);
    formData.append('selected_agent', selectedAgent);

    const response = await fetch('/chat', {
        method: 'POST',
        body: formData
    });
    
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    return await response.json();
}

/**
 * Abre un EventSource al endpoint SSE del task.
 * @param {string}   taskId
 * @param {function} onChunk  - llamado con cada string de texto parcial
 * @param {function} onDone   - llamado con el objeto {thinking, audit, ...} final
 * @param {function} onError  - llamado con mensaje de error string
 * @returns {EventSource}     - el cliente SSE (cerrar con .close() si hace falta)
 */
export function openChatStream(taskId, onChunk, onDone, onError) {
    const es = new EventSource(`/chat/stream/${taskId}`);

    es.onmessage = (event) => {
        let data;
        try {
            data = JSON.parse(event.data);
        } catch {
            return;
        }
        if (data.type === 'chunk') {
            onChunk(data.content);
        } else if (data.type === 'done') {
            onDone(data);
            es.close();
        } else if (data.type === 'error') {
            onError(data.content ?? 'Error desconocido');
            es.close();
        }
    };

    es.onerror = () => {
        onError('Error de conexión con el servidor');
        es.close();
    };

    return es;
}

export async function checkTaskResponse(taskId) {
    const response = await fetch(`/check_response/${taskId}`);
    
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    return await response.json();
}

export async function loadUserHistory(username, limit = 10) {
    const response = await fetch(`/api/history/${username}?limit=${limit}`);
    
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    return await response.json();
}

export async function loadConversationDetail(conversationId) {
    const response = await fetch(`/api/conversation/${conversationId}`);
    
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    return await response.json();
}

export async function saveCanvasEdits(conversationId, content) {
    const response = await fetch('/api/canvas/save', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            conversation_id: conversationId,
            edited_content: content
        })
    });
    
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    return await response.json();
}

export async function deleteConversation(conversationId) {
    const response = await fetch(`/api/conversation/${conversationId}`, {
        method: 'DELETE'
    });
    
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    return await response.json();
}

export async function updateConversationFolder(conversationId, folder) {
    const response = await fetch(`/api/conversation/${conversationId}/folder`, {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ folder })
    });
    
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    return await response.json();
}

export async function toggleConversationFavorite(conversationId) {
    const response = await fetch(`/api/conversation/${conversationId}/favorite`, {
        method: 'POST'
    });
    
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    return await response.json();
}