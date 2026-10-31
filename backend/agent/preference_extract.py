"""Map filtered persona text onto personalization knobs Copefy may honor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent.injection_filter import (
    COACHING_MAX_CHARS,
    GOAL_MAX_CHARS,
    STYLE_MAX_CHARS,
    PERSONA_INSTRUCTIONS_MAX_CHARS,
    PERSONA_NAME_MAX_CHARS,
    PERSONA_ROLE_MAX_CHARS,
    PERSONA_TRAITS_MAX_CHARS,
    filter_instruction_overwrites,
    filter_preferred_name,
)
from agent.prompts import DEFAULT_COMMUNICATION_STYLE

if TYPE_CHECKING:
    from agent.persona import UserPersona


@dataclass(frozen=True)
class PreferenceKnobs:
    preferred_name: str | None
    style_preset: str | None
    custom_tone: str | None
    wellness_goal: str | None
    coaching_notes: str | None
    structured_format: bool

    @property
    def display_style(self) -> str:
        return self.style_preset or DEFAULT_COMMUNICATION_STYLE


@dataclass(frozen=True)
class ActivePersonaKnobs:
    name: str | None
    role_type: str | None
    personality: str | None
    custom_guidance: str | None


def extract_active_persona(persona: UserPersona | None) -> ActivePersonaKnobs:
    """Filter every user-authored field of the selected AI persona."""
    selected = persona.active_persona if persona else None
    if selected is None:
        return ActivePersonaKnobs(None, None, None, None)
    return ActivePersonaKnobs(
        name=filter_instruction_overwrites(
            selected.name, max_chars=PERSONA_NAME_MAX_CHARS
        ),
        role_type=filter_instruction_overwrites(
            selected.role_type, max_chars=PERSONA_ROLE_MAX_CHARS
        ),
        personality=filter_instruction_overwrites(
            selected.base_personality, max_chars=PERSONA_TRAITS_MAX_CHARS
        ),
        custom_guidance=filter_instruction_overwrites(
            selected.custom_instructions, max_chars=PERSONA_INSTRUCTIONS_MAX_CHARS
        ),
    )


def extract_preference_knobs(persona: UserPersona | None) -> PreferenceKnobs:
    """Sanitize persona fields and keep only allowlisted personalization knobs."""
    from agent.persona import (
        PRESET_STYLES,
        UserPersona as Persona,
        parse_wellness_fields,
        resolve_coaching_preferences,
        wants_structured_format,
    )

    persona = persona or Persona()
    raw_style = (persona.communication_style or "").strip()
    if raw_style in PRESET_STYLES:
        style_preset = raw_style
        custom_tone = None
    else:
        style_preset = None
        custom_tone = filter_instruction_overwrites(raw_style, max_chars=STYLE_MAX_CHARS)

    primary, _ = parse_wellness_fields(persona.wellness_goal)
    wellness_goal = filter_instruction_overwrites(primary, max_chars=GOAL_MAX_CHARS)
    coaching_notes = filter_instruction_overwrites(
        resolve_coaching_preferences(persona), max_chars=COACHING_MAX_CHARS
    )
    return PreferenceKnobs(
        preferred_name=filter_preferred_name(persona.preferred_name),
        style_preset=style_preset,
        custom_tone=custom_tone,
        wellness_goal=wellness_goal,
        coaching_notes=coaching_notes,
        structured_format=wants_structured_format(coaching_notes),
    )
