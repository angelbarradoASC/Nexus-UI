"""
app/exceptions.py
------------------
Excepciones propias de NEXUS-UI y handlers HTTP para FastAPI.

Uso en routers:
    raise NotFoundError("Conversación")
    raise AuthError()

Registro en main.py:
    from exceptions import register_exception_handlers
    register_exception_handlers(app)
"""

from __future__ import annotations

from loguru import logger
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


# ── Jerarquía de excepciones ──────────────────────────────────────────────────

class AppError(Exception):
    """Base para todos los errores de la aplicación."""

    def __init__(
        self,
        mensaje: str,
        codigo: str = "ERROR_GENERICO",
        status_code: int = 500,
    ) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.status_code = status_code


class NotFoundError(AppError):
    def __init__(self, recurso: str) -> None:
        super().__init__(f"{recurso} no encontrado", "NOT_FOUND", 404)


class AuthError(AppError):
    def __init__(self, detalle: str = "No autenticado") -> None:
        super().__init__(detalle, "AUTH_ERROR", 401)


class ForbiddenError(AppError):
    def __init__(self, detalle: str = "Sin permisos para esta operación") -> None:
        super().__init__(detalle, "FORBIDDEN", 403)


class LLMError(AppError):
    def __init__(self, detalle: str = "Error al llamar al modelo LLM") -> None:
        super().__init__(detalle, "LLM_ERROR", 502)


class DBError(AppError):
    def __init__(self, detalle: str = "Error de base de datos") -> None:
        super().__init__(detalle, "DB_ERROR", 503)


class SSHError(AppError):
    def __init__(self, host: str, detalle: str) -> None:
        super().__init__(f"Error SSH en {host}: {detalle}", "SSH_ERROR", 502)


class JiraError(AppError):
    def __init__(self, detalle: str) -> None:
        super().__init__(f"Error JIRA: {detalle}", "JIRA_ERROR", 502)


class ConfigError(AppError):
    def __init__(self, campo: str) -> None:
        super().__init__(
            f"Variable de configuración obligatoria no definida: {campo}",
            "CONFIG_ERROR",
            500,
        )


# ── Registro de handlers en FastAPI ───────────────────────────────────────────

def register_exception_handlers(app: FastAPI) -> None:
    """
    Registra handlers globales en la app FastAPI.
    Llamar en main.py tras crear la app.
    """

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "AppError | codigo={} | mensaje={} | method={} | path={}",
            exc.codigo,
            str(exc),
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": str(exc), "codigo": exc.codigo},
        )

    @app.exception_handler(Exception)
    async def _generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Error no controlado | method={} | path={}",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={"error": "Error interno del servidor", "codigo": "SERVER_ERROR"},
        )
