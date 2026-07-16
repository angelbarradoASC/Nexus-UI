"""Helpers for applying desktop-local remote LLM configuration."""

from __future__ import annotations

from desktop.storage.provider_config import DesktopLLMProviderConfig
from desktop.storage.router_config import DesktopLLMRouterConfig


def apply_desktop_router_config(cfg, router: DesktopLLMRouterConfig) -> None:
    """Apply all 4 LLM levels from the router config onto cfg."""
    try:
        cfg.llm_priority = router.priority
    except Exception:
        pass

    def _apply(url_attr, key_attr, model_attr, level_cfg):
        if level_cfg.is_configured and level_cfg.enabled:
            setattr(cfg, url_attr, level_cfg.url.rstrip("/"))
            setattr(cfg, key_attr, level_cfg.api_key or "not-needed")
            setattr(cfg, model_attr, level_cfg.model)
        else:
            setattr(cfg, url_attr, None)

    _apply("llm_l0_url", "llm_l0_key", "llm_l0_model", router.l0)
    if router.l0.is_configured and router.l0.enabled:
        cfg.llm_api_base_url = router.l0.url.rstrip("/")
        cfg.llm_api_key = router.l0.api_key or "not-needed"
        cfg.llm_model = router.l0.model
    else:
        cfg.llm_api_base_url = None

    _apply("llm_l1_url", "llm_l1_key", "llm_l1_model", router.l1)
    _apply("llm_l2_url", "llm_l2_key", "llm_l2_model", router.l2)
    _apply("llm_l3_url", "llm_l3_key", "llm_l3_model", router.l3)


def apply_desktop_provider_to_cfg(cfg, provider: DesktopLLMProviderConfig) -> None:
    """
    Apply the persisted desktop provider on top of the process config.

    We intentionally treat desktop provider config as an override for the
    first remote level, because Open-Nexus is expected to run without local
    models and point to a remote inference server.
    """

    if not provider.enabled or not provider.is_configured:
        return

    cfg.llm_l0_url = None
    cfg.llm_api_base_url = None
    cfg.llm_l0_key = "not-needed"
    cfg.llm_api_key = "not-needed"
    cfg.llm_l0_model = "disabled"
    cfg.llm_model = "disabled"

    cfg.nvidia_use_as_l1 = False
    cfg.llm_l1_url = provider.api_base_url.rstrip("/")
    cfg.llm_l1_key = provider.api_key
    cfg.llm_l1_model = provider.model
