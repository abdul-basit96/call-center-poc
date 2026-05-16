"""Decode uploaded/browser audio (WebM, etc.) to 16 kHz mono for HF and librosa."""

from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def _suffix_from_hint(filename_hint: str | None) -> str:
    if filename_hint:
        ext = Path(filename_hint).suffix.lower()
        if ext in (".webm", ".ogg", ".opus", ".mp4", ".m4a", ".wav", ".mp3", ".flac"):
            return ext
    return ".webm"


def _decode_with_pyav(audio_bytes: bytes) -> np.ndarray:
    import av

    container = av.open(io.BytesIO(audio_bytes))
    if not container.streams.audio:
        raise RuntimeError("No audio stream in upload")

    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=16000)
    chunks: list[np.ndarray] = []

    for frame in container.decode(audio=0):
        for out in resampler.resample(frame):
            chunks.append(out.to_ndarray().flatten())

    for out in resampler.resample(None):
        chunks.append(out.to_ndarray().flatten())

    if not chunks:
        raise RuntimeError("No audio frames decoded from upload")

    pcm = np.concatenate(chunks).astype(np.float32)
    return pcm / 32768.0


def _decode_with_ffmpeg(audio_bytes: bytes, suffix: str) -> np.ndarray:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "Cannot decode browser audio (WebM/Opus). Install ffmpeg (brew install ffmpeg) "
            "or ensure PyAV can read the file."
        )

    import librosa

    inp_path: str | None = None
    out_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as inp:
            inp.write(audio_bytes)
            inp_path = inp.name
        out_path = inp_path + ".wav"
        proc = subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-y",
                "-i",
                inp_path,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                out_path,
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-800:]
            raise RuntimeError(f"ffmpeg could not decode audio: {tail}")
        y, _sr = librosa.load(out_path, sr=16000, mono=True)
        return np.asarray(y, dtype=np.float32)
    finally:
        for path in (inp_path, out_path):
            if path and os.path.isfile(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass


def decode_audio_bytes_to_mono_16k(
    audio_bytes: bytes,
    *,
    filename_hint: str | None = "recording.webm",
) -> np.ndarray:
    """Return float32 waveform at 16 kHz mono from browser or upload bytes."""
    if not audio_bytes:
        raise ValueError("Empty audio payload")

    suffix = _suffix_from_hint(filename_hint)
    import librosa

    if suffix == ".wav" or audio_bytes[:4] == b"RIFF":
        try:
            y, _sr = librosa.load(io.BytesIO(audio_bytes), sr=16000, mono=True)
            return np.asarray(y, dtype=np.float32)
        except Exception as e:
            logger.debug("Direct librosa decode failed: %s", e)

    # WebM/Opus from MediaRecorder — PyAV first (no system ffmpeg required).
    try:
        return _decode_with_pyav(audio_bytes)
    except Exception as e:
        logger.info("PyAV decode failed (%s), trying ffmpeg", e)

    try:
        return _decode_with_ffmpeg(audio_bytes, suffix)
    except Exception:
        if suffix != ".webm":
            return _decode_with_ffmpeg(audio_bytes, ".webm")
        raise
