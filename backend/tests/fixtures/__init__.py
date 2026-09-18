"""Synthetic silent WAV used as an audio-journal fixture.

The file is valid RIFF/WAVE with no spoken content. Tests stub transcription,
so this never needs a real speech model.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
SYNTHETIC_WAV_PATH = FIXTURE_DIR / "synthetic_journal.wav"


def synthetic_wav_bytes(*, duration_s: float = 0.25, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    frame_count = int(sample_rate * duration_s)
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * frame_count)
    return buffer.getvalue()


def write_synthetic_wav(path: Path | None = None) -> Path:
    target = path or SYNTHETIC_WAV_PATH
    target.write_bytes(synthetic_wav_bytes())
    return target


def synthetic_mp4_bytes() -> bytes:
    """Minimal ISO BMFF header. Tests stub ffmpeg; this is not a playable movie."""
    # 24-byte ftyp box: size(4) + 'ftyp' + brand + version + compat
    return (
        b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomiso2"
        + b"\x00\x00\x00\x08free"
    )
