"""Shared helpers for parsing JSON out of LLM responses."""

from __future__ import annotations

import json
import re


def strip_llm_fences(raw: str) -> str:
    """Remove markdown code fences from an LLM response string.

    Handles both  ```json ... ```  and plain  ``` ... ``` wrappers.
    This was previously inlined in 6+ places across agents and service files.
    """
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    return raw


def parse_llm_json(raw: str) -> dict | None:
    """Strip fences, extract the first JSON object, and parse it.

    Returns None on any failure (malformed, empty, non-JSON) instead of raising.
    """
    cleaned = strip_llm_fences(raw)
    s, e = cleaned.find("{"), cleaned.rfind("}")
    if s < 0 or e < s:
        return None
    try:
        return json.loads(cleaned[s : e + 1])
    except json.JSONDecodeError:
        return None
