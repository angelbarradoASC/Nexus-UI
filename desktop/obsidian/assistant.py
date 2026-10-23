"""
desktop/obsidian/assistant.py
--------------------------------
Punto de entrada del chat de PEPO para la boveda de Obsidian.

Fase 0 (solo lectura): "repasa mi boveda" produce el informe determinista de `audit.py`. Escribir o modificar
notas llega en la fase 1 (con vista previa y confirmacion); mientras tanto PEPO lo dice con claridad en vez de
inventarse un resultado.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import Any

from desktop.code_agent.workspace import WorkspaceError

from .audit import AuditReport, audit_graph, format_report
from .graph import VaultGraph
from .vault import Vault

_AUDIT = re.compile(r"\b(repasa|repasar|repaso|revisa|revisar|audita|auditar|analiza|analizar|estado|que hay|como esta|enlaces rotos|resumen)\b")
_MODIFY = re.compile(r"\b(enlaza|enlazar|ordena|ordenar|organiza|organizar|formato|formatea|limpia|arregla|mueve|etiqueta)\b")
_WRITE = re.compile(r"\b(apunta|apuntar|anota|anotar|escribe|escribir|crea|crear|guarda|guardar|añade|anade|redacta|redactar)\b")


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def classify_intent(message: str) -> str:
    """'audit' | 'modify' | 'write' | 'unknown'. Heuristico: la fase 1 lo refinara con el LLM."""
    text = _plain(message)
    if _WRITE.search(text) and re.search(r"\b(nota|notas|apunte|idea|resumen de|apunta|apuntar|anota|anotar)\b", text):
        return "write"
    if _MODIFY.search(text):
        return "modify"
    if _AUDIT.search(text):
        return "audit"
    return "unknown"


_NOT_YET = (
    "Todavía no escribo ni modifico notas: esa parte (con vista previa y tu confirmación antes de tocar nada) es la "
    "siguiente fase. Por ahora puedo **repasar tu bóveda**: enlaces rotos, notas vacías o huérfanas, títulos duplicados "
    "y menciones que podrían ser enlaces. Pídeme «repasa mi bóveda»."
)


class ObsidianAssistant:
    def __init__(self, settings: Any) -> None:
        self._settings = settings

    def open_vault(self) -> Vault | str:
        """La boveda autorizada, o un mensaje (str) apto para el usuario si no se puede usar."""
        if not self._settings.enabled:
            return "El asistente de Obsidian está desactivado en Configuración."
        path, _ = self._settings.effective_vault()
        if path is None:
            return (
                "No encuentro ninguna bóveda de Obsidian. Abre una en Obsidian o indícame la carpeta en "
                "Configuración › Obsidian."
            )
        try:
            return Vault(path)
        except WorkspaceError as exc:
            return str(exc)

    @staticmethod
    def build_report(vault: Vault) -> AuditReport:
        graph = VaultGraph.build(vault)
        return audit_graph(graph, vault.root.name, vault.skipped_protected)

    async def handle(self, message: str) -> str:
        vault = self.open_vault()
        if isinstance(vault, str):
            return vault
        intent = classify_intent(message)
        if intent == "write":
            return _NOT_YET
        report = await asyncio.to_thread(self.build_report, vault)
        text = format_report(report)
        if intent == "modify":
            text += (
                "\n\n---\nEsto es lo que cambiaría para enlazar y ordenar, pero todavía no modifico notas: "
                "llegará en la siguiente fase, con vista previa y tu confirmación."
            )
        return text
