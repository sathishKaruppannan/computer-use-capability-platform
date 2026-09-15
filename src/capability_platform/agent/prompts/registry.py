from __future__ import annotations

from capability_platform.agent.prompts import demo_v1, production_v1
from capability_platform.agent.prompts.base import PromptVariant

PROMPT_VARIANTS: dict[str, PromptVariant] = {
    "production": production_v1.VARIANT,
    "demo": demo_v1.VARIANT,
}


def get_prompt_variant(name: str) -> PromptVariant:
    try:
        return PROMPT_VARIANTS[name]
    except KeyError:
        raise ValueError(f"Unknown prompt variant: {name!r}. Known: {sorted(PROMPT_VARIANTS)}") from None
