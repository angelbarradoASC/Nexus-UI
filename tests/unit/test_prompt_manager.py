from __future__ import annotations

from nexus.prompts.catalogue import DEFAULT_PROMPTS
from nexus.prompts.service import PromptManager


async def test_prompt_manager_lists_defaults(tmp_path):
    manager = PromptManager(tmp_path)

    payload = await manager.list_prompts()

    assert payload["status"] == "success"
    assert payload["total"] == len(DEFAULT_PROMPTS)
    assert any(item["key"] == "outreach.system" for item in payload["prompts"])
    assert any(item["key"] == "sales.prospecting.guardrails" for item in payload["prompts"])
    assert any(item["key"] == "sales.prospecting.source_strategy" for item in payload["prompts"])
    assert any(item["key"] == "sales.prospecting.interpret" for item in payload["prompts"])
    assert any(item["key"] == "sales.prospecting.refine" for item in payload["prompts"])
    assert any(item["key"] == "sales.prospecting.search_audit" for item in payload["prompts"])
    assert any(item["key"] == "sales.prospecting.crm_packager" for item in payload["prompts"])


async def test_prompt_manager_updates_and_resets(tmp_path):
    manager = PromptManager(tmp_path)

    updated = await manager.update_prompt("outreach.system", "Prompt nuevo de prueba que supera el minimo.")
    assert updated["prompt"]["is_overridden"] is True
    assert updated["prompt"]["current_text"] == "Prompt nuevo de prueba que supera el minimo."

    reset = await manager.reset_prompt("outreach.system")
    assert reset["prompt"]["is_overridden"] is False
    assert reset["prompt"]["current_text"] == DEFAULT_PROMPTS["outreach.system"].default_text
