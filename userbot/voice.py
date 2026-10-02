"""Understand voice and round-video messages: transcribe them locally with Whisper.

Runs fully on this machine (faster-whisper, "small" multilingual model, downloaded once on first use);
audio never leaves the computer. The transcript is what the model sees instead of "[voice message]".
"""
import asyncio
import io
import logging

from . import config as C

log = logging.getLogger("userbot.voice")

_model = None
_lock = asyncio.Lock()
_cache: dict[int, str] = {}  # document id -> transcript


def decode(data: bytes):
    """Any audio/video container -> 16 kHz mono float32 samples."""
    import av
    import numpy as np

    chunks = []
    with av.open(io.BytesIO(data)) as container:
        stream = next(s for s in container.streams if s.type == "audio")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):  # flush
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def _transcribe(data: bytes) -> str:
    global _model
    from faster_whisper import WhisperModel

    if _model is None:
        _model = WhisperModel(C.WHISPER_MODEL, device="cpu", compute_type="int8")
    samples = decode(data)
    if len(samples) < 16000 * 0.4:  # under ~0.4s: nothing to hear
        return ""
    segments, info = _model.transcribe(samples, beam_size=1, vad_filter=True)
    # A laugh, a sigh or background noise still comes back as "words" — with low confidence. Those are dropped:
    # answering a made-up transcript is worse than knowing there was nothing to hear.
    kept = [s.text.strip() for s in segments if s.no_speech_prob < 0.6 and s.avg_logprob > -1.0]
    text = " ".join(kept).strip()
    if text and info.language_probability < 0.4 and len(text) < 60:
        log.info("Heard %.0fs of audio but no clear speech (%s, %.2f) — treated as wordless", len(samples) / 16000,
                 info.language, info.language_probability)
        return ""
    log.info("Transcribed %.0fs of audio (%s): %d chars", len(samples) / 16000, info.language, len(text))
    return text


async def transcript(msg) -> str:
    """Transcript of a voice / round-video message ('' if it can't be heard). Cached per message."""
    if not C.VOICE_TRANSCRIBE or not (msg.voice or msg.video_note):
        return ""
    key = msg.document.id
    if key in _cache:
        return _cache[key]
    if (msg.file.duration or 0) > C.VOICE_MAX_SECONDS:
        return ""
    try:
        data = await msg.download_media(file=bytes)
        async with _lock:  # one transcription at a time; it's CPU-heavy
            text = await asyncio.to_thread(_transcribe, data)
    except Exception:
        log.exception("Could not transcribe voice message")
        text = ""
    _cache[key] = text
    return text
