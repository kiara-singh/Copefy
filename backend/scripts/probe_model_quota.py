"""Find which Gemini models have enough free-tier headroom to run an eval.

Fires a short burst at each candidate and reports the first quota error, which is
the only place the API tells us the actual limit and whether it is per-minute
(throttleable) or per-day (a hard ceiling for the day).
"""

from __future__ import annotations

import sys

from google import genai
from google.genai import types
from google.genai.errors import ClientError

from config import settings

CANDIDATES = (
    "gemini-3.5-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-3.1-flash-lite",
)

BURST = 8


def _quota_details(exc: ClientError) -> str:
    details = (exc.details or {}).get("error", {}).get("details", [])
    for detail in details:
        for violation in detail.get("violations", []):
            quota_id = violation.get("quotaId", "?")
            value = violation.get("quotaValue", "?")
            return f"{quota_id} = {value}"
    return "unknown quota"


def probe(model: str) -> None:
    client = genai.Client(api_key=settings.gemini_api_key)
    config = types.GenerateContentConfig(max_output_tokens=8, temperature=0.0)

    for attempt in range(1, BURST + 1):
        try:
            client.models.generate_content(
                model=model, contents="Reply with OK.", config=config
            )
        except ClientError as exc:
            if exc.code == 429:
                print(f"{model}: {attempt - 1} ok, then 429 -> {_quota_details(exc)}")
            else:
                print(f"{model}: error {exc.code} -> {exc.message}")
            return
        except Exception as exc:  # noqa: BLE001
            print(f"{model}: failed -> {exc}")
            return

    print(f"{model}: {BURST}/{BURST} ok, no rate limit hit")


def main() -> None:
    models = sys.argv[1:] or list(CANDIDATES)
    for model in models:
        probe(model)


if __name__ == "__main__":
    main()
