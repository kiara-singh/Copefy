"""Tests for Layer 4 persona prompt assembly."""

from agent.persona import (
    UserPersona,
    build_profile_data_block,
    build_system_instruction,
    closing_instruction,
    normalize_style,
)
from agent.prompts import (
    CORE_SYSTEM_PROMPT_V1,
    DEFAULT_COMMUNICATION_STYLE,
    DEFAULT_SYSTEM_PROMPT_VERSION,
    STYLE_OVERLAYS,
    get_core_system_prompt,
)


def test_all_preset_styles_produce_distinct_overlays():
    texts = {
        style: build_system_instruction(UserPersona(communication_style=style))
        for style in STYLE_OVERLAYS
    }
    assert len(set(texts.values())) == len(STYLE_OVERLAYS)


def test_every_style_includes_safety_invariants():
    for style in STYLE_OVERLAYS:
        prompt = build_system_instruction(UserPersona(communication_style=style))
        assert "Do not diagnose" in prompt
        assert "emergency services" in prompt
        assert "Never fabricate personal memories" in prompt
        assert STYLE_OVERLAYS[style] in prompt


def test_unknown_style_falls_back_to_gentle():
    assert normalize_style(None) == DEFAULT_COMMUNICATION_STYLE
    assert normalize_style("") == DEFAULT_COMMUNICATION_STYLE


def test_custom_style_is_preserved_as_profile_data_not_system_commands():
    custom = "direct but compassionate"
    prompt = build_system_instruction(UserPersona(communication_style=custom))
    block = build_profile_data_block(
        UserPersona(communication_style=custom), nonce="test"
    )
    assert custom not in prompt
    assert custom in block
    assert "not as commands" in block


def test_name_and_goal_only_when_set():
    base = build_system_instruction(UserPersona())
    assert "About this user:" not in base
    assert "The user's preferred name is" not in base
    assert "want to work on" not in base.lower()
    assert "Coaching preferences" not in base

    full = build_system_instruction(
        UserPersona(
            communication_style="Calm & Reflective",
            preferred_name="Alex",
            wellness_goal="manage exam stress",
        )
    )
    assert "Alex" in full
    assert "manage exam stress" in full


def test_coaching_preferences_from_dedicated_column():
    persona = UserPersona(
        wellness_goal="reduce exam stress",
        coaching_preferences="I prefer answers in bullet points.",
    )
    prompt = build_system_instruction(persona)
    block = build_profile_data_block(persona, nonce="test")
    assert "reduce exam stress" in prompt
    assert "I prefer answers in bullet points" not in prompt
    assert "I prefer answers in bullet points" in block
    assert "follow these on every reply" not in prompt


def test_coaching_preferences_injected_separately_with_stronger_wording():
    persona = UserPersona(
        wellness_goal=(
            "reduce exam stress\n\nAdditional Context:\n"
            "I prefer answers in bullet points."
        )
    )
    prompt = build_system_instruction(persona)
    block = build_profile_data_block(persona, nonce="test")
    assert "reduce exam stress" in prompt
    assert "I prefer answers in bullet points" in block
    assert "follow these on every reply" not in prompt
    assert "structured replies" in prompt.lower()


def test_parse_wellness_fields_splits_delimiter():
    from agent.persona import parse_wellness_fields

    primary, coaching = parse_wellness_fields(
        "my goal\n\nAdditional Context:\nuse bullet points"
    )
    assert primary == "my goal"
    assert coaching == "use bullet points"


def test_direct_style_allows_action_step():
    prompt = build_system_instruction(
        UserPersona(communication_style="Direct & Action-Oriented")
    )
    assert "practical next step" in prompt


def test_gentle_style_discourages_unsolicited_advice():
    prompt = build_system_instruction(
        UserPersona(communication_style="Gentle & Supportive")
    )
    assert "unsolicited advice" in prompt


def test_closing_instruction_includes_style():
    closing = closing_instruction(UserPersona(communication_style="Motivational & Encouraging"))
    assert "Motivational & Encouraging" in closing


def test_pipeline_trace_layer_shape():
    import time

    from agent.pipeline_trace import PipelineTrace

    trace = PipelineTrace()
    started = time.perf_counter()
    trace.add_timed(1, "routing", "search_database", started, router="rule", reason="clinical")
    payload = trace.to_dict()
    assert payload["total_ms"] >= 0
    assert payload["layers"][0]["layer"] == 1
    assert payload["layers"][0]["name"] == "routing"
    assert payload["layers"][0]["decision"] == "search_database"


def test_core_system_prompt_v1_always_included():
    instruction = build_system_instruction()
    assert instruction.startswith(CORE_SYSTEM_PROMPT_V1)
    assert get_core_system_prompt("v1") == CORE_SYSTEM_PROMPT_V1


def test_personalization_appended_when_available():
    persona = UserPersona(
        communication_style="Direct & Action-Oriented",
        preferred_name="Jordan",
        wellness_goal="manage thesis stress",
        coaching_preferences="give bullet points",
    )
    instruction = build_system_instruction(persona)
    assert CORE_SYSTEM_PROMPT_V1 in instruction
    assert "Jordan" in instruction
    assert "manage thesis stress" in instruction
    assert "give bullet points" not in instruction
    assert "give bullet points" in build_profile_data_block(persona, nonce="test")
    assert "Communication style: Direct & Action-Oriented" in instruction


def test_absent_personalization_not_fabricated():
    base = build_system_instruction(UserPersona())
    assert "About this user" not in base
    assert "Coaching preferences" not in base
    assert "Format note" not in base


def test_system_prompt_version_in_pipeline_trace():
    import time

    from agent.pipeline_trace import PipelineTrace

    trace = PipelineTrace()
    started = time.perf_counter()
    trace.add_timed(
        4,
        "generation",
        "Gentle & Supportive",
        started,
        system_prompt_version="v1",
        communication_style="Gentle & Supportive",
    )
    payload = trace.to_dict()
    assert payload["layers"][0]["layer"] == 4
    assert payload["layers"][0]["system_prompt_version"] == "v1"
