"""Multi-level LLM router configuration for Open-Nexus desktop."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class LLMLevelConfig:
    url: str = ""
    api_key: str = ""
    model: str = ""
    enabled: bool = True

    @classmethod
    def from_dict(cls, d: dict | None) -> "LLMLevelConfig":
        d = d or {}
        return cls(
            url=str(d.get("url", "") or "").strip(),
            api_key=str(d.get("api_key", "") or "").strip(),
            model=str(d.get("model", "") or "").strip(),
            enabled=bool(d.get("enabled", True)),
        )

    def to_dict(self, *, mask_key: bool = False) -> dict:
        return {
            "url": self.url,
            "api_key": "****" if mask_key and self.api_key else self.api_key,
            "model": self.model,
            "enabled": self.enabled,
        }

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.model)


@dataclass(slots=True)
class DesktopLLMRouterConfig:
    priority: str = "cost"
    l0: LLMLevelConfig = field(default_factory=LLMLevelConfig)
    l1: LLMLevelConfig = field(default_factory=LLMLevelConfig)
    l2: LLMLevelConfig = field(default_factory=LLMLevelConfig)
    l3: LLMLevelConfig = field(default_factory=LLMLevelConfig)
    updated_at: str = ""

    @classmethod
    def from_app_config(cls, cfg) -> "DesktopLLMRouterConfig":
        """Deriva la tabla L0-L3 desde AppConfig (env/.env) — se usa como
        default de la API cuando todavía no existe `llm_router.json`
        guardado. Antes esto era un dict ad-hoc suelto en
        `products/desktop/backend/app.py` (`_cfg_as_router_defaults()`),
        una sexta representación de esta misma tabla — ahora es un
        constructor de la clase que ya modela exactamente esta forma.
        Nunca expone `api_key` real (queda vacía; el valor real solo vive
        en `cfg` hasta que el usuario guarda su propia config desde la UI).
        """
        return cls(
            priority=cfg.llm_priority,
            l0=LLMLevelConfig(
                url=cfg.llm_l0_url or cfg.llm_api_base_url or "",
                model=cfg.llm_l0_model or cfg.llm_model or "",
                enabled=bool(cfg.llm_l0_url or cfg.llm_api_base_url),
            ),
            l1=LLMLevelConfig(
                url=cfg.llm_l1_url or "",
                model=cfg.llm_l1_model or "",
                enabled=bool(cfg.llm_l1_url),
            ),
            l2=LLMLevelConfig(
                url=cfg.llm_l2_url or "",
                model=cfg.llm_l2_model or "",
                enabled=bool(cfg.llm_l2_url),
            ),
            l3=LLMLevelConfig(
                url=cfg.llm_l3_url or "",
                model=cfg.llm_l3_model or "",
                enabled=bool(cfg.llm_l3_url),
            ),
        )

    @classmethod
    def from_dict(cls, d: dict | None) -> "DesktopLLMRouterConfig":
        d = d or {}
        return cls(
            priority=str(d.get("priority", "cost") or "cost"),
            l0=LLMLevelConfig.from_dict(d.get("l0")),
            l1=LLMLevelConfig.from_dict(d.get("l1")),
            l2=LLMLevelConfig.from_dict(d.get("l2")),
            l3=LLMLevelConfig.from_dict(d.get("l3")),
            updated_at=str(d.get("updated_at", "") or ""),
        )

    def to_dict(self, *, mask_keys: bool = False) -> dict:
        return {
            "priority": self.priority,
            "l0": self.l0.to_dict(mask_key=mask_keys),
            "l1": self.l1.to_dict(mask_key=mask_keys),
            "l2": self.l2.to_dict(mask_key=mask_keys),
            "l3": self.l3.to_dict(mask_key=mask_keys),
            "updated_at": self.updated_at,
        }

    def touched(self) -> "DesktopLLMRouterConfig":
        return DesktopLLMRouterConfig(
            priority=self.priority,
            l0=self.l0,
            l1=self.l1,
            l2=self.l2,
            l3=self.l3,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    @property
    def has_any_level(self) -> bool:
        return any(lv.is_configured for lv in (self.l0, self.l1, self.l2, self.l3))
