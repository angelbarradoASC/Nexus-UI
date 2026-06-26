// ==============================================================================
// NEXUS Platform - State Management
// Variables globales y configuración
// ==============================================================================

export const state = {
    // Task management
    currentTaskId: null,
    pollingInterval: null,
    
    // UI state
    isWelcomeShown: true,
    activeTools: ['web'],
    
    // User
    currentUsername: '',
    
    // Canvas
    canvasActive: false,
    currentCanvasContent: {
        original: '',
        edited: '',
        type: 'code',
        language: 'javascript'
    },
    currentActiveTab: 'original',
    
    // History
    conversationHistory: [],
    currentConversationId: null,
    historyView: 'list', // 'list' or 'grid'
    historySortBy: 'recent', // 'recent', 'alphabetical', 'favorites'
    historySearchQuery: '',
    historyActiveFolder: 'all', // 'all', 'work', 'personal', 'archived'
    
    // Pagination
    historyPage: 1,
    historyHasMore: true,
    
    // Drag & Drop
    draggedItemId: null
};

export function setState(key, value) {
    state[key] = value;
}

export function getState(key) {
    return state[key];
}

export function updateCanvasContent(updates) {
    state.currentCanvasContent = {
        ...state.currentCanvasContent,
        ...updates
    };
}

export function resetState() {
    state.currentTaskId = null;
    state.pollingInterval = null;
    state.isWelcomeShown = true;
    state.currentConversationId = null;
}