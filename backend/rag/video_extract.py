"""Extract a WAV audio track from a video container using local ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class AudioExtractError(RuntimeError):
    """Raised when a video has no usable audio track or ffmpeg fails."""


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


def extract_audio_wav(video_bytes: bytes) -> bytes:
    """Return 16 kHz mono WAV bytes from the first audio stream.

    Does not decode or send video frames to any model.
    """
    if not video_bytes:
        raise AudioExtractError("Video file is empty.")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AudioExtractError(
            "ffmpeg is required to extract audio from video journals."
        )

    ffprobe = shutil.which("ffprobe")
    with tempfile.TemporaryDirectory(prefix="copefy-video-") as tmp:
        src = Path(tmp) / "input.bin"
        dst = Path(tmp) / "audio.wav"
        src.write_bytes(video_bytes)

        has_audio = False
        if ffprobe:
            probe = _run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "a",
                    "-show_entries",
                    "stream=index",
                    "-of",
                    "csv=p=0",
                    str(src),
                ]
            )
            has_audio = bool((probe.stdout or "").strip()) and probe.returncode == 0
        else:
            inspect = _run([ffmpeg, "-i", str(src)])
            has_audio = "Audio:" in (inspect.stderr or "")

        if not has_audio:
            raise AudioExtractError("Video has no usable audio track.")

        extract = _run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(src),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                str(dst),
            ]
        )
        if extract.returncode != 0 or not dst.exists() or dst.stat().st_size < 44:
            detail = (extract.stderr or extract.stdout or "ffmpeg extract failed").strip()
            raise AudioExtractError(detail[:300] or "ffmpeg extract failed.")
        wav = dst.read_bytes()
        if wav[0:4] != b"RIFF" or wav[8:12] != b"WAVE":
            raise AudioExtractError("Extracted audio was not a valid WAV file.")
        return wav
