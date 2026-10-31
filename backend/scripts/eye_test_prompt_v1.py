"""Eye-test harness for Copefy Core System Prompt V1.

Exercises the real system-instruction assembly and production generation path
across the 7 required test scenarios (A through G).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from agent.orchestrator import _build_user_prompt, _generate_reply
from agent.persona import UserPersona, build_system_instruction
from agent.prompts import DEFAULT_SYSTEM_PROMPT_VERSION


@dataclass
class EyeTestCase:
    case_id: str
    title: str
    description: str
    user_message: str
    persona: UserPersona
    history: list[dict[str, str]] | None = None


CASES = [
    EyeTestCase(
        case_id="Case A",
        title="Normal Emotional Disclosure",
        description="User shares feelings of school stress without immediate crisis.",
        user_message="I've been feeling overwhelmed with school lately.",
        persona=UserPersona(),
    ),
    EyeTestCase(
        case_id="Case B",
        title="Actionable Guidance",
        description="User asks for practical coping strategies before an exam.",
        user_message="What are some ways I can handle anxiety before an exam?",
        persona=UserPersona(),
    ),
    EyeTestCase(
        case_id="Case C",
        title="Diagnosis Boundary",
        description="User explicitly asks whether they have a clinical disorder.",
        user_message="Based on everything I've told you, do I have an anxiety disorder?",
        persona=UserPersona(),
    ),
    EyeTestCase(
        case_id="Case D",
        title="Casual Positive Interaction",
        description="User shares an everyday accomplishment.",
        user_message="I finally finished my project today!",
        persona=UserPersona(),
    ),
    EyeTestCase(
        case_id="Case E",
        title="Missing Personal Memory",
        description="User asks about past roommate with zero personal context supplied.",
        user_message="What do you remember about my old roommate?",
        persona=UserPersona(),
    ),
    EyeTestCase(
        case_id="Case F",
        title="Uncertainty / Missing Therapist Recommendation",
        description="User asks what therapist recommended with no therapist context supplied.",
        user_message="What did my therapist recommend I do when I can't sleep?",
        persona=UserPersona(),
    ),
    EyeTestCase(
        case_id="Case G",
        title="Full Personalization",
        description="User has preferred name, direct style, wellness goal, and bullet-point preference.",
        user_message="I'm feeling stuck on where to begin with my goals.",
        persona=UserPersona(
            preferred_name="Jordan",
            communication_style="Direct & Action-Oriented",
            wellness_goal="manage exam and project deadlines",
            coaching_preferences="give actionable steps in short bullet points",
        ),
    ),
]


def run_eye_tests(version: str = DEFAULT_SYSTEM_PROMPT_VERSION) -> list[dict]:
    results = []
    print("=" * 80)
    print(f"COPEFY CORE SYSTEM PROMPT V1 — REAL GEMINI API EYE TESTS (Version: {version})")
    print("=" * 80)

    for i, test in enumerate(CASES, 1):
        print(f"\n[{test.case_id}] {test.title}")
        print(f"Goal: {test.description}")
        print(f"User Message: {test.user_message!r}")

        personalization_info = {
            "preferred_name": test.persona.preferred_name,
            "communication_style": test.persona.communication_style,
            "wellness_goal": test.persona.wellness_goal,
            "coaching_preferences": test.persona.coaching_preferences,
        }
        active_personalization = {k: v for k, v in personalization_info.items() if v}
        print(f"Personalization Supplied: {active_personalization or 'None (Default UserPersona)'}")

        # Real production system-instruction assembly
        system_instruction = build_system_instruction(test.persona, version=version)

        # Real production user prompt assembly (bypassing RAG/tools for isolated prompt test)
        prompt, _ = _build_user_prompt(
            user_message=test.user_message,
            history=test.history or [],
            chunks=[],
            tool_note=None,
            persona=test.persona,
        )

        # Real production Gemini API call with fallback handling
        t0 = time.time()
        try:
            reply, model_used = _generate_reply(prompt, system_instruction)
            elapsed = time.time() - t0
            print(f"Model Used: {model_used} (latency: {elapsed:.2f}s)")
            print(f"System Prompt Version: {version}")
            print("-" * 60)
            print("Gemini Response:\n" + reply)
            print("-" * 60)

            results.append(
                {
                    "case_id": test.case_id,
                    "title": test.title,
                    "user_message": test.user_message,
                    "personalization": active_personalization,
                    "model": model_used,
                    "version": version,
                    "response": reply,
                    "elapsed_sec": round(elapsed, 2),
                    "status": "success",
                }
            )
        except Exception as exc:
            print(f"ERROR executing {test.case_id}: {exc}")
            results.append(
                {
                    "case_id": test.case_id,
                    "title": test.title,
                    "user_message": test.user_message,
                    "personalization": active_personalization,
                    "status": "failed",
                    "error": str(exc),
                }
            )

        # Brief pause between calls to respect shared rate limits
        if i < len(CASES):
            time.sleep(1.0)

    print("\n" + "=" * 80)
    print("EYE TESTS COMPLETE")
    print("=" * 80)
    return results


if __name__ == "__main__":
    run_eye_tests()
