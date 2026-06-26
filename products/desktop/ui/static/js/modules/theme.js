// ==============================================================================
// NEXUS Platform - Theme Module (Dark Mode Toggle)
// Persistencia en localStorage + animaciones suaves
// ==============================================================================

const THEME_KEY = 'nexus-theme';
const themes = {
    light: 'light',
    dark: 'dark',
    auto: 'auto'
};

let currentTheme = themes.light;

// Inicializar tema
export function initTheme() {
    // Cargar tema guardado o detectar preferencia del sistema
    const savedTheme = localStorage.getItem(THEME_KEY);
    
    if (savedTheme && themes[savedTheme]) {
        currentTheme = savedTheme;
    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        currentTheme = themes.dark;
    }

    applyTheme(currentTheme, false);
    setupThemeToggle();
    setupSystemThemeListener();
    
}

// Aplicar tema
export function applyTheme(theme, animate = true) {
    const root = document.documentElement;
    
    // Animacion de transicion
    if (animate) {
        root.style.setProperty('--transition-theme', '0.3s ease');
        setTimeout(() => {
            root.style.removeProperty('--transition-theme');
        }, 300);
    }

    // Aplicar clase
    root.classList.remove('theme-light', 'theme-dark');
    root.classList.add(`theme-${theme}`);

    // Actualizar variables CSS
    if (theme === themes.dark) {
        applyDarkVariables();
    } else {
        applyLightVariables();
    }

    currentTheme = theme;
    localStorage.setItem(THEME_KEY, theme);

    // Actualizar UI del toggle
    updateToggleUI();

    // Dispatch event para otros modulos
    window.dispatchEvent(new CustomEvent('themeChanged', { 
        detail: { theme } 
    }));
}

// Variables dark mode
function applyDarkVariables() {
    const root = document.documentElement;
    
    root.style.setProperty('--bg-primary', '#1a1a1a');
    root.style.setProperty('--bg-secondary', '#242424');
    root.style.setProperty('--bg-tertiary', '#2e2e2e');
    root.style.setProperty('--bg-hover', '#383838');

    root.style.setProperty('--sidebar-bg', '#0d0d0d');
    root.style.setProperty('--sidebar-hover', '#1a1a1a');
    root.style.setProperty('--sidebar-active', '#242424');

    root.style.setProperty('--border-primary', '#404040');
    root.style.setProperty('--border-secondary', '#333333');
    root.style.setProperty('--border-dark', '#555555');

    root.style.setProperty('--text-primary', '#e8e8e8');
    root.style.setProperty('--text-secondary', '#b4b4b4');
    root.style.setProperty('--text-muted', '#8e8e8e');
    root.style.setProperty('--text-on-dark', '#f0f0f0');
    root.style.setProperty('--text-on-dark-secondary', '#c4c4c4');

    // Mantener accents (ya funcionan bien en dark)
}

// Variables light mode (defaults)
function applyLightVariables() {
    const root = document.documentElement;
    
    root.style.setProperty('--bg-primary', '#ffffff');
    root.style.setProperty('--bg-secondary', '#f7f7f8');
    root.style.setProperty('--bg-tertiary', '#ececf1');
    root.style.setProperty('--bg-hover', '#e8e8ed');

    root.style.setProperty('--sidebar-bg', '#202123');
    root.style.setProperty('--sidebar-hover', '#2a2b32');
    root.style.setProperty('--sidebar-active', '#343541');

    root.style.setProperty('--border-primary', '#d9d9e3');
    root.style.setProperty('--border-secondary', '#ececf1');
    root.style.setProperty('--border-dark', '#4d4d4f');

    root.style.setProperty('--text-primary', '#2e2e2e');
    root.style.setProperty('--text-secondary', '#6e6e80');
    root.style.setProperty('--text-muted', '#8e8ea0');
    root.style.setProperty('--text-on-dark', '#ececec');
    root.style.setProperty('--text-on-dark-secondary', '#b4b4b4');
}

// Toggle tema
export function toggleTheme() {
    const newTheme = currentTheme === themes.dark ? themes.light : themes.dark;
    applyTheme(newTheme, true);
}

// Setup toggle button
function setupThemeToggle() {
    const toggleBtn = document.getElementById('themeToggle');
    if (!toggleBtn) {
        console.warn('Theme toggle button not found');
        return;
    }

    toggleBtn.addEventListener('click', toggleTheme);
    updateToggleUI();
}

// Actualizar UI del toggle
function updateToggleUI() {
    const toggleBtn = document.getElementById('themeToggle');
    if (!toggleBtn) return;

    const icon = toggleBtn.querySelector('i');
    if (!icon) return;

    // Cambiar icono con animacion
    icon.style.transform = 'scale(0)';
    
    setTimeout(() => {
        if (currentTheme === themes.dark) {
            icon.className = 'fas fa-moon';
            toggleBtn.title = 'Dark Mode';
        } else {
            icon.className = 'fas fa-sun';
            toggleBtn.title = 'Light Mode';
        }
        icon.style.transform = 'scale(1)';
    }, 150);
}

// Escuchar cambios del sistema
function setupSystemThemeListener() {
    if (!window.matchMedia) return;

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    
    mediaQuery.addEventListener('change', (e) => {
        // Solo aplicar si no hay preferencia guardada o es auto
        const savedTheme = localStorage.getItem(THEME_KEY);
        if (!savedTheme || savedTheme === themes.auto) {
            const systemTheme = e.matches ? themes.dark : themes.light;
            applyTheme(systemTheme, true);
        }
    });
}

// Exportar tema actual
export function getCurrentTheme() {
    return currentTheme;
}

// Exportar estado dark
export function isDarkMode() {
    return currentTheme === themes.dark;
}

// Transicion suave al cargar pagina (evita flash)
export function preventFlash() {
    const savedTheme = localStorage.getItem(THEME_KEY);
    if (savedTheme === themes.dark) {
        document.documentElement.classList.add('theme-dark');
    }
}

// Llamar esto lo antes posible en el <head>
if (typeof window !== 'undefined') {
    preventFlash();
}

export default {
    initTheme,
    applyTheme,
    toggleTheme,
    getCurrentTheme,
    isDarkMode,
    preventFlash
};
