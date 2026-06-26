// ==============================================================================
// NEXUS Platform - History Module - PARTE 1: Core + Load
// ==============================================================================

import { state, setState } from '../core/state.js';
import { loadUserHistory, loadConversationDetail } from '../core/api.js';

const historyContainer = document.getElementById('historyContainer');

// Module state
let abortController = null;
let searchDebounceTimer = null;

// Helper: Debounce function
function debounce(func, wait) {
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(searchDebounceTimer);
            func(...args);
        };
        clearTimeout(searchDebounceTimer);
        searchDebounceTimer = setTimeout(later, wait);
    };
}

// Main load function
export async function loadHistory(append = false) {
    // Cancel previous request
    if (abortController) {
        abortController.abort();
    }
    abortController = new AbortController();

    if (!append) {
        showSkeleton();
    }

    try {
        const data = await loadUserHistory(
            state.currentUsername,
            20,
            { signal: abortController.signal }
        );

        if (data.status === 'success' && data.conversations && data.conversations.length > 0) {
            if (!append) {
                historyContainer.innerHTML = '';
            }

            renderHistoryItems(data.conversations);
            setState('historyHasMore', data.has_more || false);
        } else {
            if (!append) {
                showEmptyState('no-conversations');
            }
        }
    } catch (error) {
        if (error.name === 'AbortError') {
            return;
        }
        console.error('Error loading history:', error);
        showEmptyState('error');
    }
}

// Render items
function renderHistoryItems(conversations) {
    const grouped = groupByDate(conversations);

    Object.keys(grouped).forEach(dateLabel => {
        // Add separator
        const separator = document.createElement('div');
        separator.className = 'history-separator';
        separator.textContent = dateLabel;
        historyContainer.appendChild(separator);

        // Add items
        grouped[dateLabel].forEach(conversation => {
            const item = createHistoryItem(conversation);
            historyContainer.appendChild(item);
        });
    });
}

// Create single history item
function createHistoryItem(conversation) {
    const item = document.createElement('div');
    item.className = 'history-item';
    item.dataset.conversationId = conversation.id;
    item.draggable = true;

    // Build indicators
    let indicators = '';
    if (conversation.unread) {
        indicators += '<span class="status-badge unread">Nuevo</span>';
    }
    if (conversation.favorite) {
        indicators += '<span class="status-badge saved">★</span>';
    }

    item.innerHTML = `
        <div class="history-item-content">
            <div class="history-date">${conversation.display_time}</div>
            <div class="history-preview">${escapeHtml(conversation.preview)}</div>
            ${indicators ? `<div class="history-indicators">${indicators}</div>` : ''}
        </div>
        <div class="history-item-actions">
            <button class="history-action-btn star" data-action="favorite" title="Favorito">
                <i class="fas fa-star"></i>
            </button>
            <button class="history-action-btn" data-action="delete" title="Eliminar">
                <i class="fas fa-trash"></i>
            </button>
        </div>
        ${conversation.message_count ? `<div class="history-badge">${conversation.message_count}</div>` : ''}
    `;

    // Event listeners with delegation
    item.addEventListener('click', (e) => {
        if (e.target.closest('.history-item-actions')) return;
        loadConversation(conversation.id);
    });

    // Action buttons
    const actions = item.querySelector('.history-item-actions');
    actions.addEventListener('click', (e) => {
        e.stopPropagation();
        const btn = e.target.closest('[data-action]');
        if (!btn) return;

        const action = btn.dataset.action;
        if (action === 'delete') {
            deleteConversationWithConfirm(conversation.id);
        } else if (action === 'favorite') {
            toggleFavorite(conversation.id);
        }
    });

    return item;
}

// Load conversation
async function loadConversation(conversationId) {
    try {
        const data = await loadConversationDetail(conversationId);

        if (data.status === 'success' && data.conversation) {
            const conversation = data.conversation;

            const messagesContainer = document.getElementById('messagesContainer');
            messagesContainer.innerHTML = '';
            setState('isWelcomeShown', false);

            if (window.addMessage) {
                if (conversation.query) {
                    window.addMessage(conversation.query, true);
                }
                if (conversation.response) {
                    window.addMessage(conversation.response, false, conversation.thinking);
                }
            }

            // Mark as active
            document.querySelectorAll('.history-item').forEach(item => {
                item.classList.remove('active');
            });

            const activeItem = document.querySelector(`[data-conversation-id="${conversationId}"]`);
            if (activeItem) {
                activeItem.classList.add('active');
            }

            setState('currentConversationId', conversationId);
        }
    } catch (error) {
        console.error('Error loading conversation:', error);
        if (window.addMessage) {
            window.addMessage('Error al cargar la conversación.', false);
        }
    }
}

// Group conversations by date
function groupByDate(conversations) {
    const groups = {
        'Hoy': [],
        'Ayer': [],
        'Esta semana': [],
        'Anterior': []
    };

    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    const weekAgo = new Date(today);
    weekAgo.setDate(weekAgo.getDate() - 7);

    conversations.forEach(conv => {
        const convDate = new Date(conv.timestamp);
        const convDay = new Date(convDate.getFullYear(), convDate.getMonth(), convDate.getDate());

        if (convDay.getTime() === today.getTime()) {
            groups['Hoy'].push(conv);
        } else if (convDay.getTime() === yesterday.getTime()) {
            groups['Ayer'].push(conv);
        } else if (convDay >= weekAgo) {
            groups['Esta semana'].push(conv);
        } else {
            groups['Anterior'].push(conv);
        }
    });

    // Remove empty groups
    Object.keys(groups).forEach(key => {
        if (groups[key].length === 0) {
            delete groups[key];
        }
    });

    return groups;
}

// Helper: Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// UI States
function showSkeleton() {
    historyContainer.innerHTML = '';
    for (let i = 0; i < 5; i++) {
        const skeleton = document.createElement('div');
        skeleton.className = 'history-skeleton';
        skeleton.innerHTML = `
            <div class="skeleton-line"></div>
            <div class="skeleton-line short"></div>
        `;
        historyContainer.appendChild(skeleton);
    }
}

function showEmptyState(type) {
    const messages = {
        'no-conversations': {
            icon: 'fa-comments',
            text: 'Sin conversaciones anteriores<br>Inicia una nueva conversación para comenzar'
        },
        'no-results': {
            icon: 'fa-search',
            text: 'No se encontraron conversaciones<br>Intenta con otros términos de búsqueda'
        },
        'error': {
            icon: 'fa-exclamation-triangle',
            text: 'Error al cargar el historial<br>Por favor, recarga la página'
        }
    };

    const msg = messages[type] || messages['error'];

    historyContainer.innerHTML = `
        <div class="history-empty">
            <div class="history-empty-icon">
                <i class="fas ${msg.icon}"></i>
            </div>
            <div class="history-empty-text">${msg.text}</div>
        </div>
    `;
}
// ==============================================================================
// NEXUS Platform - History Module - PARTE 2: Search + Filters + Sort
// ==============================================================================
// AÑADIR AL FINAL DE LA PARTE 1

// Search with debounce
export const searchHistory = debounce(async (query) => {
    setState('historySearchQuery', query.toLowerCase());
    
    if (!query.trim()) {
        loadHistory();
        return;
    }

    if (abortController) {
        abortController.abort();
    }
    abortController = new AbortController();

    showSkeleton();

    try {
        const data = await loadUserHistory(
            state.currentUsername,
            100,
            { signal: abortController.signal }
        );

        if (data.status === 'success' && data.conversations) {
            const filtered = data.conversations.filter(conv => 
                conv.preview.toLowerCase().includes(query) ||
                conv.query?.toLowerCase().includes(query)
            );

            if (filtered.length > 0) {
                historyContainer.innerHTML = '';
                renderHistoryItems(filtered);
            } else {
                showEmptyState('no-results');
            }
        }
    } catch (error) {
        if (error.name === 'AbortError') return;
        console.error('Search error:', error);
        showEmptyState('error');
    }
}, 300);

// Filter by folder
export async function filterByFolder(folder) {
    setState('historyActiveFolder', folder);
    
    // Update UI
    document.querySelectorAll('.folder-tag').forEach(tag => {
        tag.classList.toggle('active', tag.dataset.folder === folder);
    });

    if (abortController) {
        abortController.abort();
    }
    abortController = new AbortController();

    showSkeleton();

    try {
        const data = await loadUserHistory(
            state.currentUsername,
            100,
            { signal: abortController.signal }
        );

        if (data.status === 'success' && data.conversations) {
            let filtered = data.conversations;

            if (folder !== 'all') {
                filtered = filtered.filter(conv => conv.folder === folder);
            }

            if (filtered.length > 0) {
                historyContainer.innerHTML = '';
                renderHistoryItems(filtered);
            } else {
                showEmptyState('no-results');
            }
        }
    } catch (error) {
        if (error.name === 'AbortError') return;
        console.error('Filter error:', error);
        showEmptyState('error');
    }
}

// Sort history
export function sortHistory(sortBy) {
    setState('historySortBy', sortBy);

    const items = Array.from(historyContainer.querySelectorAll('.history-item'));
    const separators = Array.from(historyContainer.querySelectorAll('.history-separator'));

    // Clear container
    historyContainer.innerHTML = '';

    // Get conversation data
    const conversations = items.map(item => ({
        element: item,
        id: item.dataset.conversationId,
        preview: item.querySelector('.history-preview')?.textContent || '',
        date: item.querySelector('.history-date')?.textContent || ''
    }));

    // Sort
    let sorted;
    switch (sortBy) {
        case 'alphabetical':
            sorted = conversations.sort((a, b) => 
                a.preview.localeCompare(b.preview)
            );
            // No separators for alphabetical
            sorted.forEach(conv => historyContainer.appendChild(conv.element));
            break;

        case 'favorites':
            sorted = conversations.filter(conv => 
                conv.element.querySelector('.status-badge.saved')
            );
            if (sorted.length > 0) {
                const sep = document.createElement('div');
                sep.className = 'history-separator';
                sep.textContent = 'Favoritos';
                historyContainer.appendChild(sep);
                sorted.forEach(conv => historyContainer.appendChild(conv.element));
            }
            
            const nonFavorites = conversations.filter(conv => 
                !conv.element.querySelector('.status-badge.saved')
            );
            if (nonFavorites.length > 0) {
                const sep = document.createElement('div');
                sep.className = 'history-separator';
                sep.textContent = 'Otros';
                historyContainer.appendChild(sep);
                nonFavorites.forEach(conv => historyContainer.appendChild(conv.element));
            }
            break;

        case 'recent':
        default:
            // Restore original order with separators
            // This is the default grouped by date view
            loadHistory();
            return;
    }

    // Update dropdown UI
    const sortDropdown = document.querySelector('.history-sort');
    if (sortDropdown) {
        const labels = {
            'recent': 'Recientes',
            'alphabetical': 'A-Z',
            'favorites': 'Favoritos'
        };
        sortDropdown.textContent = labels[sortBy] || 'Ordenar';
    }
}

// Toggle view (list/grid)
export function toggleView(view) {
    setState('historyView', view);
    
    if (view === 'grid') {
        historyContainer.classList.add('grid-view');
    } else {
        historyContainer.classList.remove('grid-view');
    }

    // Update button UI
    document.querySelectorAll('.view-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.view === view);
    });
}

// Delete conversation with confirmation
async function deleteConversationWithConfirm(conversationId) {
    if (!confirm('¿Eliminar esta conversación?')) {
        return;
    }

    const item = document.querySelector(`[data-conversation-id="${conversationId}"]`);
    if (!item) return;

    // Optimistic update
    const itemBackup = item.cloneNode(true);
    item.style.opacity = '0.5';
    item.style.pointerEvents = 'none';

    try {
        // Import delete function
        const { deleteConversation } = await import('../core/api.js');
        await deleteConversation(conversationId);

        // Success - remove from DOM
        item.remove();

        // If this was the active conversation, reset view
        if (state.currentConversationId === conversationId) {
            if (window.newChat) {
                window.newChat();
            }
        }

        // Show notification
        if (window.showNotification) {
            window.showNotification('Conversación eliminada', 'success');
        }

    } catch (error) {
        console.error('Delete failed:', error);

        // Rollback
        item.replaceWith(itemBackup);

        if (window.showNotification) {
            window.showNotification('Error al eliminar la conversación', 'error');
        }
    }
}

// Toggle favorite
async function toggleFavorite(conversationId) {
    const item = document.querySelector(`[data-conversation-id="${conversationId}"]`);
    if (!item) return;

    const starBtn = item.querySelector('[data-action="favorite"]');
    const indicators = item.querySelector('.history-indicators');
    const existingBadge = indicators?.querySelector('.status-badge.saved');

    // Optimistic update
    const wasFavorite = !!existingBadge;

    try {
        // Import toggle function
        const { toggleConversationFavorite } = await import('../core/api.js');
        await toggleConversationFavorite(conversationId);

        // Update UI
        if (wasFavorite && existingBadge) {
            existingBadge.remove();
            starBtn.innerHTML = '<i class="fas fa-star"></i>';
        } else {
            if (!indicators) {
                const newIndicators = document.createElement('div');
                newIndicators.className = 'history-indicators';
                item.querySelector('.history-item-content').appendChild(newIndicators);
            }
            const badge = document.createElement('span');
            badge.className = 'status-badge saved';
            badge.textContent = '★';
            (indicators || item.querySelector('.history-indicators')).appendChild(badge);
            starBtn.innerHTML = '<i class="fas fa-star" style="color: var(--accent-orange);"></i>';
        }

    } catch (error) {
        console.error('Toggle favorite failed:', error);
        if (window.showNotification) {
            window.showNotification('Error al actualizar favorito', 'error');
        }
    }
}

// Setup infinite scroll
export function setupInfiniteScroll() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting && state.historyHasMore) {
                loadMoreHistory();
            }
        });
    }, {
        root: historyContainer,
        threshold: 0.1
    });

    // Observe last item
    const observeLastItem = () => {
        const items = historyContainer.querySelectorAll('.history-item');
        if (items.length > 0) {
            observer.observe(items[items.length - 1]);
        }
    };

    // Re-observe after new items load
    const originalRender = renderHistoryItems;
    renderHistoryItems = (...args) => {
        originalRender(...args);
        observeLastItem();
    };

    observeLastItem();
    return observer;
}

async function loadMoreHistory() {
    if (!state.historyHasMore) return;

    setState('historyPage', state.historyPage + 1);

    const loader = document.createElement('div');
    loader.className = 'history-loading-more';
    loader.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Cargando más...';
    historyContainer.appendChild(loader);

    try {
        await loadHistory(true);
    } finally {
        loader.remove();
    }
}
// ==============================================================================
// NEXUS Platform - History Module - PARTE 3: Drag & Drop + Cleanup
// ==============================================================================
// AÑADIR AL FINAL DE LA PARTE 2

// Drag & Drop state
const dragListeners = new WeakMap();

// Setup drag and drop for an item
function setupDragDrop(item, conversationId) {
    // Prevent duplicate listeners
    if (dragListeners.has(item)) return;

    const handlers = {
        dragstart: (e) => {
            setState('draggedItemId', conversationId);
            item.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/html', item.innerHTML);
        },

        dragend: (e) => {
            item.classList.remove('dragging');
            setState('draggedItemId', null);
            
            // Remove all drag-over classes
            document.querySelectorAll('.history-item.drag-over').forEach(el => {
                el.classList.remove('drag-over');
            });
        },

        dragover: (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            
            const draggingItem = document.querySelector('.history-item.dragging');
            if (draggingItem && draggingItem !== item) {
                item.classList.add('drag-over');
            }
        },

        dragleave: (e) => {
            if (e.target === item) {
                item.classList.remove('drag-over');
            }
        },

        drop: (e) => {
            e.preventDefault();
            e.stopPropagation();
            
            const draggedId = state.draggedItemId;
            if (!draggedId || draggedId === conversationId) return;

            const draggedItem = document.querySelector(`[data-conversation-id="${draggedId}"]`);
            if (!draggedItem) return;

            // Reorder in DOM
            const rect = item.getBoundingClientRect();
            const midpoint = rect.top + rect.height / 2;
            
            if (e.clientY < midpoint) {
                item.parentNode.insertBefore(draggedItem, item);
            } else {
                item.parentNode.insertBefore(draggedItem, item.nextSibling);
            }

            item.classList.remove('drag-over');

            // TODO: Save new order to backend
        }
    };

    // Attach listeners
    Object.keys(handlers).forEach(event => {
        item.addEventListener(event, handlers[event]);
    });

    // Store for cleanup
    dragListeners.set(item, handlers);
}

// Enhanced createHistoryItem to include drag&drop
const originalCreateHistoryItem = createHistoryItem;
function createHistoryItemWithDrag(conversation) {
    const item = originalCreateHistoryItem(conversation);
    setupDragDrop(item, conversation.id);
    return item;
}

// Override the original
window.createHistoryItem = createHistoryItemWithDrag;

// Setup folder controls
export function setupFolderControls() {
    const foldersContainer = document.querySelector('.history-folders');
    if (!foldersContainer) return;

    const folders = [
        { id: 'all', label: 'Todos', icon: 'fa-list' },
        { id: 'work', label: 'Trabajo', icon: 'fa-briefcase' },
        { id: 'personal', label: 'Personal', icon: 'fa-user' },
        { id: 'archived', label: 'Archivados', icon: 'fa-archive' }
    ];

    foldersContainer.innerHTML = folders.map(folder => `
        <div class="folder-tag ${folder.id === 'all' ? 'active' : ''}" data-folder="${folder.id}">
            <i class="fas ${folder.icon}"></i> ${folder.label}
        </div>
    `).join('');

    // Event delegation for folder clicks
    foldersContainer.addEventListener('click', (e) => {
        const tag = e.target.closest('.folder-tag');
        if (tag) {
            filterByFolder(tag.dataset.folder);
        }
    });
}

// Setup sort controls
export function setupSortControls() {
    const sortDropdown = document.querySelector('.history-sort');
    if (!sortDropdown) return;

    const options = [
        { value: 'recent', label: 'Recientes' },
        { value: 'alphabetical', label: 'A-Z' },
        { value: 'favorites', label: 'Favoritos' }
    ];

    // Create dropdown menu (simple implementation)
    sortDropdown.addEventListener('click', () => {
        const menu = document.createElement('div');
        menu.className = 'sort-dropdown-menu';
        menu.style.cssText = `
            position: absolute;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-primary);
            border-radius: 4px;
            padding: 0.5rem 0;
            margin-top: 0.25rem;
            z-index: 1000;
        `;

        options.forEach(opt => {
            const item = document.createElement('div');
            item.textContent = opt.label;
            item.style.cssText = `
                padding: 0.5rem 1rem;
                cursor: pointer;
                color: var(--text-secondary);
            `;
            item.addEventListener('mouseenter', () => {
                item.style.background = 'var(--bg-primary)';
            });
            item.addEventListener('mouseleave', () => {
                item.style.background = 'transparent';
            });
            item.addEventListener('click', () => {
                sortHistory(opt.value);
                menu.remove();
            });
            menu.appendChild(item);
        });

        sortDropdown.appendChild(menu);

        // Close on outside click
        setTimeout(() => {
            document.addEventListener('click', function closeMenu(e) {
                if (!sortDropdown.contains(e.target)) {
                    menu.remove();
                    document.removeEventListener('click', closeMenu);
                }
            });
        }, 0);
    });
}

// Setup view controls
export function setupViewControls() {
    const viewBtns = document.querySelectorAll('.view-btn');
    viewBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            toggleView(btn.dataset.view);
        });
    });
}

// Setup search input
export function setupSearchInput() {
    const searchInput = document.querySelector('.history-search-input');
    if (!searchInput) return;

    searchInput.addEventListener('input', (e) => {
        searchHistory(e.target.value);
    });

    // Clear search on Escape
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            searchInput.value = '';
            searchHistory('');
        }
    });
}

// Initialize all history features
export function initHistoryModule() {
    setupFolderControls();
    setupSortControls();
    setupViewControls();
    setupSearchInput();
    setupInfiniteScroll();
    
}

// Cleanup function
export function cleanup() {
    // Cancel pending requests
    if (abortController) {
        abortController.abort();
        abortController = null;
    }

    // Clear timers
    if (searchDebounceTimer) {
        clearTimeout(searchDebounceTimer);
        searchDebounceTimer = null;
    }

    // Remove drag listeners
    document.querySelectorAll('.history-item').forEach(item => {
        const handlers = dragListeners.get(item);
        if (handlers) {
            Object.keys(handlers).forEach(event => {
                item.removeEventListener(event, handlers[event]);
            });
            dragListeners.delete(item);
        }
    });

}

// Cleanup on page unload
window.addEventListener('beforeunload', cleanup);

// Export public API
export default {
    loadHistory,
    searchHistory,
    filterByFolder,
    sortHistory,
    toggleView,
    setupInfiniteScroll,
    initHistoryModule,
    cleanup
};
