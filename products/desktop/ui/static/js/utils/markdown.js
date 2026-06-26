// ==============================================================================
// NEXUS Platform - Markdown Utils
// Content detection and rendering helpers
// ==============================================================================

// Detect special content for Canvas
export function detectSpecialContent(content) {
    // 1. Code blocks
    const codeBlockRegex = /```(\w+)?\n([\s\S]+?)```/g;
    const codeMatches = [...content.matchAll(codeBlockRegex)];
    
    if (codeMatches.length > 0 && codeMatches[0][2].length > 100) {
        const code = codeMatches[0][2].trim();
        const language = codeMatches[0][1] || 'text';
        const lines = code.split('\n').length;
        
        return {
            type: 'Código',
            content: code,
            language: language,
            summary: `Código ${language} (${lines} líneas)`
        };
    }

    // 2. Long content (documents)
    if (content.length > 500 && !content.includes('<') && !content.includes('>')) {
        return {
            type: 'Documento',
            content: content,
            language: 'markdown',
            summary: content.substring(0, 200) + '...'
        };
    }

    // 3. Tables
    const lines = content.split('\n');
    const tableLines = lines.filter(line => line.includes('|'));
    
    if (tableLines.length > 3) {
        return {
            type: 'Tabla',
            content: content,
            language: 'markdown',
            summary: `Tabla de datos (${tableLines.length} filas)`
        };
    }

    // 4. JSON
    try {
        const jsonMatch = content.match(/\{[\s\S]+\}/);
        if (jsonMatch) {
            const parsed = JSON.parse(jsonMatch[0]);
            const keys = Object.keys(parsed);
            
            return {
                type: 'JSON',
                content: jsonMatch[0],
                language: 'json',
                summary: `Estructura JSON (${keys.length} propiedades)`
            };
        }
    } catch (e) {
        // Not valid JSON
    }

    // 5. XML
    if (content.trim().startsWith('<?xml') || content.includes('<') && content.includes('</')) {
        const tagCount = (content.match(/<\w+/g) || []).length;
        if (tagCount > 3) {
            return {
                type: 'XML',
                content: content,
                language: 'xml',
                summary: `Documento XML (${tagCount} elementos)`
            };
        }
    }

    return null;
}

// Export for window access
if (typeof window !== 'undefined') {
    window.detectSpecialContent = detectSpecialContent;
}

export default {
    detectSpecialContent
};