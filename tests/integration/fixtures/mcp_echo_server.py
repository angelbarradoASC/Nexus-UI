"""Servidor MCP minimo (stdio) para verificar MCPManager de extremo a
extremo sin depender de un servicio externo. Lanzado como subproceso por
tests/integration/test_mcp_manager_live.py — no se importa directamente."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("test-echo-server")


@mcp.tool()
def echo(text: str) -> str:
    """Devuelve el mismo texto que se le pasa."""
    return f"echo: {text}"


@mcp.tool()
def create_note(title: str) -> str:
    """Tool de 'escritura' (prefijo create_) para probar la heuristica de confirmacion."""
    return f"nota creada: {title}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
