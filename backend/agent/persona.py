"""User persona preferences for Layer 4 generation."""

from __future__ import annotations

from dataclasses import dataclass

from agent.prompts import (
    DEFAULT_COMMUNICATION_STYLE,
    DEFAULT_SYSTEM_PROMPT_VERSION,
    STYLE_OVERLAYS,
    get_core_system_prompt,
)

PRESET_STYLES = frozenset(STYLE_OVERLAYS.keys())
WELLNESS_GOAL_DELIMITER = "\n\nAdditional Context:\n"

_FORMAT_KEYWORDS = (
    "bullet",
    "bullets",
    "bullet point",
    "numbered list",
    "list format",
    "step-by-step",
    "step by step",
)


@dataclass(frozen=True)
class UserPersona:
    communication_style: str = DEFAULT_COMMUNICATION_STYLE
    preferred_name: str | None = None
    wellness_goal: str | None = None
    coaching_preferences: str | None = None


def resolve_coaching_preferences(persona: UserPersona) -> str | None:
    """Return coaching prefs from the dedicated column, or legacy merged wellness_goal."""
    if persona.coaching_preferences and persona.coaching_preferences.strip():
        return persona.coaching_preferences.strip()
    _, legacy = parse_wellness_fields(persona.wellness_goal)
    return legacy


def parse_wellness_fields(
    wellness_goal: str | None,
) -> tuple[str | None, str | None]:
    """Split stored wellness_goal into primary goal and coaching preferences."""
    if not wellness_goal or not wellness_goal.strip():
        return None, None
    raw = wellness_goal.strip()
    if WELLNESS_GOAL_DELIMITER in raw:
        primary, coaching = raw.split(WELLNESS_GOAL_DELIMITER, 1)
        return primary.strip() or None, coaching.strip() or None
    return raw, None


def wants_structured_format(coaching_preferences: str | None) -> bool:
    if not coaching_preferences:
        return False
    lowered = coaching_preferences.lower()
    return any(keyword in lowered for keyword in _FORMAT_KEYWORDS)


def normalize_style(raw: str | None) -> str:
    if not raw or not raw.strip():
        return DEFAULT_COMMUNICATION_STYLE
    return raw.strip()


def _style_overlay(style: str) -> str:
    if style in STYLE_OVERLAYS:
        return STYLE_OVERLAYS[style]
    return (
        f"Communication style: {style}\n"
        "- Match this tone in every reply while keeping all safety rules above.\n"
        "- Keep it short: 1-3 sentences. One question max."
    )


def resolve_primary_goal(persona: UserPersona) -> str | None:
    if not persona.wellness_goal or not persona.wellness_goal.strip():
        return None
    primary, _ = parse_wellness_fields(persona.wellness_goal)
    return primary


def build_system_instruction(
    persona: UserPersona | None = None,
    version: str = DEFAULT_SYSTEM_PROMPT_VERSION,
) -> str:
    """Build the Gemini system instruction for one chat turn."""
    persona = persona or UserPersona()
    style = normalize_style(persona.communication_style)
    parts = [get_core_system_prompt(version), _style_overlay(style)]

    primary_goal = resolve_primary_goal(persona)
    coaching_preferences = resolve_coaching_preferences(persona)

    context_lines: list[str] = []
    if persona.preferred_name:
        context_lines.append(
            f"The user's preferred name is {persona.preferred_name}. "
            "Address them by it naturally — not in every sentence."
        )
    if primary_goal:
        context_lines.append(
            f"They want to work on: {primary_goal}. "
            "Reference this when it naturally fits the conversation."
        )
    if context_lines:
        parts.append("About this user:\n" + "\n".join(context_lines))

    if coaching_preferences:
        parts.append(
            "Coaching preferences — follow these on every reply unless a safety rule conflicts:\n"
            f"{coaching_preferences}"
        )
        if wants_structured_format(coaching_preferences):
            parts.append(
                "Format note: the user asked for structured replies (e.g. bullet points). "
                "Honor that format even if it means using a short bulleted list instead of "
                "a single paragraph."
            )

    return "\n\n".join(parts)


def closing_instruction(persona: UserPersona | None = None) -> str:
    style = normalize_style(persona.communication_style if persona else None)
    return f"Reply as Copefy in the {style} voice."
