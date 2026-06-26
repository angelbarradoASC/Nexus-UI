"""
app/nexus/policy/guardrails.py
--------------------------------
Motor de guardrails para NEXUS.

Principios de diseño:
  - La clasificación de riesgo es DETERMINISTA: regex, no LLM.
    Un LLM barato no puede ser el único guardián de una acción destructiva.
  - Las políticas definen 4 niveles: READ / WRITE / DESTRUCTIVE / BLOCKED.
  - Falla cerrado: acción sin patrón claro → WRITE (no READ).
  - Strict mode: para entornos críticos en producción.

Niveles:
  READ        → auto_approved     (lectura, observabilidad)
  WRITE       → auto_approved + log prominente
  DESTRUCTIVE → human_required    (siempre, sin excepción)
  BLOCKED     → bloqueado         (sin posibilidad de apelación)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


# ── Tipos ─────────────────────────────────────────────────────────────────────

class RiskClass(str, Enum):
    READ        = "read"
    WRITE       = "write"
    DESTRUCTIVE = "destructive"
    BLOCKED     = "blocked"


@dataclass(frozen=True)
class GuardrailVerdict:
    risk_class:  RiskClass
    risk_score:  float   # 0.0 (seguro) – 1.0 (máximo riesgo)
    verdict:     str     # auto_approved | human_required | blocked
    reason:      str
    matched_pattern: str = ""


# ── Clasificador de riesgo ────────────────────────────────────────────────────

class RiskClassifier:
    """
    Clasifica comandos/acciones por nivel de riesgo usando patrones regex.
    No depende de ningún LLM. Compilado una sola vez al instanciar.
    """

    # Nunca se ejecutan. Ni con aprobación humana.
    _BLOCKED: list[str] = [
        r"rm\s+-rf\s+/(?!\w)",          # rm -rf / (raíz del sistema)
        r"rm\s+-rf\s+/\s*$",
        r":()\s*\{\s*:|:&\s*\};:",       # fork bomb
        r"dd\s+if=.*of=/dev/sd",         # dd sobre disco físico
        r"mkfs\.",                        # formatear sistema de ficheros
        r">\s*/dev/sda",                  # sobreescribir disco
        r"passwd\s+root\b",              # cambiar password root sin sudo interactivo
    ]

    # Requieren aprobación humana obligatoria.
    _DESTRUCTIVE: list[str] = [
        r"\brm\s+-[rRf]{1,3}\s+/",       # rm recursivo en ruta absoluta
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bpoweroff\b",
        r"\binit\s+[06]\b",
        r"\bkill\s+-9\b",
        r"\bkillall\b",
        r"\bpkill\b",
        r"\bsystemctl\s+(stop|disable|mask)\b",
        r"\bservice\s+\w+\s+stop\b",
        r"\bdrop\s+table\b",
        r"\btruncate\s+table\b",
        r"\bdelete\s+from\b.*where\b",    # DELETE con WHERE (parcial pero destructivo)
        r"\bdelete\s+from\b(?!\s+\w+\s+where)",  # DELETE sin WHERE (aún más destructivo)
        r"\bformat\b.*(disk|drive|volume|partition)",
        r"mv\s+.*?/etc/",                # mover ficheros de configuración del sistema
        r"\bchmod\s+[0-7]*0{3}\s+/",    # quitar todos los permisos en ruta del sistema
        r"\biptables\s+-F\b",            # flush de todas las reglas de firewall
        r"\bufw\s+disable\b",
        r"\bsetenforce\s+0\b",           # desactivar SELinux
    ]

    # Se ejecutan automáticamente con log prominente.
    _WRITE: list[str] = [
        r"\bsystemctl\s+(restart|start|reload|enable)\b",
        r"\bservice\s+\w+\s+(restart|start)\b",
        r"\bsed\s+-i\b",
        r"\bchmod\b",
        r"\bchown\b",
        r"\bcp\s+",
        r"\bmv\s+",
        r"\bmkdir\b",
        r"\btouch\b",
        r"\becho\s+.*>\s*(?!/dev/null)",  # echo con redirección real
        r"\bcurl\b.*-[Xx]\s*POST",
        r"\bcurl\b.*--data\b",
        r"\bwget\b",
        r"\bapt(?:-get)?\s+(install|remove|purge|upgrade)\b",
        r"\byum\s+(install|remove|erase|update)\b",
        r"\bdnf\s+(install|remove|erase|update)\b",
        r"\bpip\s+install\b",
        r"\bnpm\s+(install|update|uninstall)\b",
        r"\binsert\s+into\b",
        r"\bupdate\b.*\bset\b",
        r"\bcreate\s+table\b",
        r"\balter\s+table\b",
        r"\bgit\s+(push|merge|rebase|reset)\b",
        r"\bdocker\s+(run|start|stop|rm|rmi)\b",
        r"\bkubectl\s+(apply|delete|scale|patch)\b",
    ]

    def __init__(self) -> None:
        self._blocked_re     = [re.compile(p, re.IGNORECASE) for p in self._BLOCKED]
        self._destructive_re = [re.compile(p, re.IGNORECASE) for p in self._DESTRUCTIVE]
        self._write_re       = [re.compile(p, re.IGNORECASE) for p in self._WRITE]

    def classify(self, action: str) -> tuple[RiskClass, float, str]:
        """
        Returns (risk_class, risk_score, matched_pattern).
        Falla cerrado: sin match explícito de READ → devuelve WRITE.
        """
        text = action.strip()

        for pattern in self._blocked_re:
            if pattern.search(text):
                return RiskClass.BLOCKED, 1.0, pattern.pattern

        for pattern in self._destructive_re:
            if pattern.search(text):
                return RiskClass.DESTRUCTIVE, 0.85, pattern.pattern

        for pattern in self._write_re:
            if pattern.search(text):
                return RiskClass.WRITE, 0.40, pattern.pattern

        # Heurística adicional: redirección a ruta absoluta
        if re.search(r">>?\s*/\w", text, re.IGNORECASE):
            return RiskClass.WRITE, 0.45, "redirect_to_absolute_path"

        # Solo se clasifica como READ si es exclusivamente lectura obvia
        read_only = re.compile(
            r"^\s*(?:cat|less|more|head|tail|grep|awk|sed\s+(?!-i)|"
            r"find|ls|du|df|free|top|htop|uptime|ps|netstat|ss|"
            r"ping|traceroute|nslookup|dig|curl\s+(?!.*-[Xx]\s*POST)(?!.*--data)|"
            r"systemctl\s+(?:status|is-active|is-enabled|list-units)|"
            r"journalctl|tail\s+-[fn]|dmesg|uname|hostname|whoami|"
            r"id|env|printenv|echo\s+\$|date|cal|which|whereis|"
            r"lsof|iostat|vmstat|sar|strace\s+-p)\b",
            re.IGNORECASE,
        )
        if read_only.match(text):
            return RiskClass.READ, 0.05, "read_only_command"

        # Fallback seguro: WRITE (no asumir que algo es seguro sin evidencia)
        return RiskClass.WRITE, 0.35, "no_pattern_fallback_write"


# ── Motor de guardrails ───────────────────────────────────────────────────────

class GuardrailEngine:
    """
    Evalúa acciones y emite un GuardrailVerdict.

    strict_mode=False (default):
        READ / WRITE → auto_approved
        DESTRUCTIVE  → human_required
        BLOCKED      → blocked

    strict_mode=True (producción crítica):
        WRITE también → human_required
    """

    def __init__(self, *, strict_mode: bool = False) -> None:
        self._classifier  = RiskClassifier()
        self._strict_mode = strict_mode

    def evaluate(self, action: str) -> GuardrailVerdict:
        risk_class, risk_score, matched = self._classifier.classify(action)

        if risk_class == RiskClass.BLOCKED:
            return GuardrailVerdict(
                risk_class=risk_class,
                risk_score=risk_score,
                verdict="blocked",
                reason="Acción prohibida por política de seguridad — no ejecutable",
                matched_pattern=matched,
            )

        if risk_class == RiskClass.DESTRUCTIVE:
            return GuardrailVerdict(
                risk_class=risk_class,
                risk_score=risk_score,
                verdict="human_required",
                reason="Acción destructiva — requiere aprobación explícita de un operador",
                matched_pattern=matched,
            )

        if risk_class == RiskClass.WRITE and self._strict_mode:
            return GuardrailVerdict(
                risk_class=risk_class,
                risk_score=risk_score,
                verdict="human_required",
                reason="Modo estricto: todas las escrituras requieren aprobación manual",
                matched_pattern=matched,
            )

        return GuardrailVerdict(
            risk_class=risk_class,
            risk_score=risk_score,
            verdict="auto_approved",
            reason="Dentro de los límites de auto-ejecución",
            matched_pattern=matched,
        )

    def bulk_evaluate(self, actions: list[str]) -> list[GuardrailVerdict]:
        """Pre-valida una lista de acciones (plan completo)."""
        return [self.evaluate(a) for a in actions]

    def plan_is_safe(self, actions: list[str]) -> bool:
        """True solo si TODAS las acciones del plan son auto_approved."""
        return all(v.verdict == "auto_approved" for v in self.bulk_evaluate(actions))

    def highest_risk(self, actions: list[str]) -> GuardrailVerdict:
        """Devuelve el veredicto de mayor riesgo de una lista."""
        verdicts = self.bulk_evaluate(actions)
        order = {"blocked": 3, "human_required": 2, "auto_approved": 1}
        return max(verdicts, key=lambda v: order.get(v.verdict, 0))


# ── Compatibilidad con coordinator.py existente ───────────────────────────────

def can_auto_execute(severity: str) -> bool:
    return severity.lower() != "critical"


def should_create_ticket(severity: str, runbook: dict) -> bool:
    auto_actions = set(runbook.get("auto_actions", []))
    return severity.lower() == "critical" or "ticket" in auto_actions
