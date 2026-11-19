"""
Free, local speech.

* STT: faster-whisper (OpenAI Whisper weights, MIT) on CPU int8. Decodes the
  browser's webm/opus recording through PyAV, so no ffmpeg install is needed.
* TTS: Piper (rhasspy, MIT) neural voice, ONNX on CPU.
  Optional TTS_ENGINE=edge uses Microsoft Edge's free online voices instead.

Models load lazily on first use and stay in memory.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import threading
import time
import wave

from . import config

log = logging.getLogger("kiosk.speech")
_lock = threading.Lock()
_whisper = None
_piper = None

# What Whisper should expect. Built from the live menu so it never drifts from what's on sale.
# `hotwords` biases decoding toward these spellings; the prompt is a sample order in the style we want
# back (Indonesian, menu names spelled as on the menu, numbers as words).
def _hotwords() -> str:
    from .menu import COMBOS, MENU
    words = [m["name"] for m in MENU] + [c["name"] for c in COMBOS]
    words += ["dingin", "panas", "besar", "kurang manis", "tanpa gula", "susu oat", "susu almond", "extra shot",
              "QRIS", "tunai", "kartu debit", "iya boleh", "nggak usah"]
    return ", ".join(words)


# Starting with "Es Kopi ..." matters: without it Whisper writes "Eskopi" and digits ("1") for numbers.
_PROMPT = ("Halo Kak, saya mau satu Cappuccino panas sama Butter Croissant. Es Kopi Susu Gula Aren satu, "
           "terus dua Caffe Latte dingin, "
           "yang satu pakai susu oat, kurang manis. Iya boleh, Paket Pagi aja. Sudah itu aja, bayar pakai QRIS.")


def _get_whisper():
    global _whisper
    with _lock:
        if _whisper is None:
            from faster_whisper import WhisperModel
            t0 = time.perf_counter()
            _whisper = WhisperModel(config.WHISPER_MODEL, device=config.WHISPER_DEVICE,
                                    compute_type=config.WHISPER_COMPUTE, download_root=str(config.WHISPER_DIR))
            log.info("Whisper %s loaded in %.1fs", config.WHISPER_MODEL, time.perf_counter() - t0)
    return _whisper


def _decode(audio: bytes):
    """Any browser recording (webm/opus, ogg, wav, mp4) -> 16 kHz mono float32, using PyAV directly.
    (faster-whisper's own decoder passes an argument PyAV >= 15 no longer accepts.)"""
    import av
    import numpy as np

    chunks = []
    with av.open(io.BytesIO(audio)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):  # flush
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def transcribe(audio: bytes) -> dict:
    return transcribe_samples(_decode(audio))


def _level(samples):
    """Remove DC and bring quiet recordings (an INMP441 at arm's length) up to a normal speaking level,
    so the voice detector doesn't drop soft words. Loud audio is left alone."""
    import numpy as np

    x = samples - float(np.mean(samples)) if len(samples) else samples
    rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    if 1e-4 < rms < 0.05:
        x = x * min(0.07 / rms, 30.0)
    return np.clip(x, -1.0, 1.0).astype(np.float32)


def _trace_inputs(inputs: dict) -> dict:
    """Never ship raw audio to LangSmith, just its length."""
    s = inputs.get("samples")
    return {"audio_seconds": round(len(s) / 16000, 2) if s is not None else None}


try:  # LangSmith trace (active only when LANGSMITH_TRACING=true): shows raw vs fixed transcript per turn
    from langsmith import traceable as _traceable
    _trace = _traceable(name="speech_to_text", run_type="tool", process_inputs=_trace_inputs)
except Exception:  # noqa: BLE001
    def _trace(fn):
        return fn


@_trace
def transcribe_samples(samples) -> dict:
    """16 kHz mono float32 samples -> text (used directly by the ESP32 endpoint).
    `text` is the transcript after stt_fix (menu words respelled); `raw_text` is Whisper's own output."""
    from .stt_fix import correct

    t0 = time.perf_counter()
    segments, info = _get_whisper().transcribe(
        _level(samples), language=config.WHISPER_LANGUAGE, beam_size=config.WHISPER_BEAM,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 600, "speech_pad_ms": 300},
        condition_on_previous_text=False, without_timestamps=True,
        initial_prompt=_PROMPT, hotwords=_hotwords())
    raw = " ".join(s.text.strip() for s in segments).strip()
    text = correct(raw) if config.STT_FIX else raw
    if text != menu_norm(raw):
        log.info("stt fix: %r -> %r", raw, text)
    return {"text": text, "raw_text": raw, "language": info.language, "duration_s": round(info.duration, 2),
            "ms": round((time.perf_counter() - t0) * 1000)}


def menu_norm(s: str) -> str:
    from .menu import _norm
    return _norm(s)


def _get_piper():
    global _piper
    with _lock:
        if _piper is None:
            from piper import PiperVoice
            path = config.PIPER_DIR / f"{config.PIPER_VOICE}.onnx"
            if not path.exists():
                raise FileNotFoundError(f"Piper voice not found at {path}. Run: python -m piper.download_voices "
                                        f"{config.PIPER_VOICE} --data-dir models/piper")
            _piper = PiperVoice.load(path)
            log.info("Piper voice %s loaded", config.PIPER_VOICE)
    return _piper


_SATUAN = ["", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan", "sepuluh",
           "sebelas"]


def terbilang(n: int) -> str:
    """32000 -> 'tiga puluh dua ribu' (Indonesian number words)."""
    if n < 12:
        return _SATUAN[n]
    if n < 20:
        return f"{_SATUAN[n - 10]} belas"
    if n < 100:
        return f"{_SATUAN[n // 10]} puluh {terbilang(n % 10)}".strip()
    if n < 200:
        return f"seratus {terbilang(n - 100)}".strip()
    if n < 1000:
        return f"{_SATUAN[n // 100]} ratus {terbilang(n % 100)}".strip()
    if n < 2000:
        return f"seribu {terbilang(n - 1000)}".strip()
    if n < 1_000_000:
        return f"{terbilang(n // 1000)} ribu {terbilang(n % 1000)}".strip()
    return f"{terbilang(n // 1_000_000)} juta {terbilang(n % 1_000_000)}".strip()


def _speakable(text: str) -> str:
    """'Rp32.000' -> 'tiga puluh dua ribu rupiah', '2x' -> 'dua', 'A003' -> 'A nol nol tiga'."""
    import re as _re
    text = _re.sub(r"Rp\s?(\d{1,3}(?:\.\d{3})*)", lambda m: terbilang(int(m.group(1).replace(".", ""))) + " rupiah", text)
    text = _re.sub(r"\b(\d{1,2})x ", lambda m: terbilang(int(m.group(1))) + " ", text)
    text = _re.sub(r"\bA(\d{3})\b", lambda m: "A " + " ".join("nol" if d == "0" else terbilang(int(d))
                                                               for d in m.group(1)), text)
    return text.replace("QRIS", "kyuris")


def synthesize(text: str) -> tuple[bytes, str]:
    """Returns (audio bytes, media type)."""
    text = _speakable(text)[:1200]
    if config.TTS_ENGINE == "edge":
        return _edge(text), "audio/mpeg"
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        _get_piper().synthesize_wav(text, wf)
    return buf.getvalue(), "audio/wav"


def synthesize_pcm(text: str, gain: float = 1.0) -> bytes:
    """TTS as raw 16 kHz / 16-bit / mono little-endian PCM, ready to push straight into an I2S DAC
    (ESP32 + MAX98357A) with no decoding on the device."""
    import numpy as np

    audio, _ = synthesize(text)
    samples = _decode(audio) * gain
    return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def _edge(text: str) -> bytes:
    import edge_tts

    async def run() -> bytes:
        out = bytearray()
        async for chunk in edge_tts.Communicate(text, config.EDGE_VOICE).stream():
            if chunk["type"] == "audio":
                out += chunk["data"]
        return bytes(out)

    return asyncio.run(run())


def preload() -> None:
    for name, fn in (("whisper", _get_whisper), ("piper", _get_piper)):
        try:
            fn()
        except Exception as exc:
            log.warning("%s preload failed: %s", name, exc)
