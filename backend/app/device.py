"""
Voice endpoints for thin-client kiosk units (ESP32-S3 + I2S mic + I2S amp).

The device does no AI. It records 16 kHz / 16-bit / mono PCM while the button is held,
POSTs it here, and plays the raw PCM that comes back straight into its I2S DAC.
Speech-to-text, the LangGraph agent and TTS all run on this server.

    POST /api/device/{device_id}/turn      body: raw PCM s16le 16 kHz mono (or a WAV file)
                                            -> 200 raw PCM s16le 16 kHz mono + X-* headers
    POST /api/device/{device_id}/reset     start a new order for this device
    GET  /api/device/{device_id}           current session (lets a tablet UI follow the same cart)
    GET  /api/device/prompt/{name}         fixed phrases as PCM (the device caches them in flash)

Each device id is mapped to one LangGraph session. After DEVICE_IDLE_RESET_S of silence the
next turn starts a fresh session (= the next customer).
Header text is percent-encoded UTF-8 so it stays valid in HTTP headers.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from functools import lru_cache
from urllib.parse import quote

import numpy as np
from fastapi import APIRouter, Header, HTTPException, Path, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from . import agent, config, speech
from .cart import describe_line, totals

log = logging.getLogger("kiosk.device")
router = APIRouter(prefix="/api/device", tags=["device"])

SAMPLE_RATE = 16000
MAX_SECONDS = 20
MIN_SECONDS = 0.3
DeviceId = Path(pattern=r"^[A-Za-z0-9_-]{1,32}$")

PROMPTS = {
    "greet": "Halo Kak, selamat datang di Kopi Pagi! Tahan tombolnya, lalu sebutkan pesanannya ya.",
    "wait": "Sebentar ya, Kak.",
    "retry": "Maaf Kak, suaranya kurang jelas. Coba tahan tombolnya dan ulangi lagi ya.",
    "new": "Siap, pesanan baru dimulai. Mau pesan apa, Kak?",
    "offline": "Maaf Kak, sistem sedang gangguan. Silakan pesan langsung di kasir ya.",
}

_devices: dict[str, dict] = {}  # device_id -> {"session_id": str, "last": epoch seconds}
_lock = threading.Lock()


# ---------------------------------------------------------------- helpers
def _auth(token: str | None) -> None:
    if config.DEVICE_TOKEN and token != config.DEVICE_TOKEN:
        raise HTTPException(401, "Bad or missing X-Device-Token")


def _session_for(device_id: str, fresh: bool = False) -> str:
    """The device's current session; a new one if forced, idle too long, or lost (server restart)."""
    now = time.time()
    with _lock:
        d = _devices.get(device_id)
        if d and not fresh and now - d["last"] < config.DEVICE_IDLE_RESET_S:
            try:
                agent.get_state(d["session_id"])
                d["last"] = now
                return d["session_id"]
            except KeyError:
                pass
        sid = agent.new_session()
        _devices[device_id] = {"session_id": sid, "last": now}
        log.info("device %s -> new session %s", device_id, sid[:8])
        return sid


def _samples_from_body(body: bytes) -> np.ndarray:
    """Raw s16le 16 kHz mono PCM (what the ESP32 sends), or any container PyAV can read (WAV, webm...)."""
    if body[:4] in (b"RIFF", b"OggS", b"\x1aE\xdf\xa3", b"fLaC"):
        return speech._decode(body)
    if len(body) % 2:
        body = body[:-1]
    return np.frombuffer(body, dtype="<i2").astype(np.float32) / 32768.0


def _h(text: str) -> str:
    """Header-safe text: percent-encode anything that isn't plain readable ASCII."""
    return quote(text or "", safe=" ,.!?-:()/+'")


@lru_cache(maxsize=16)
def _prompt_pcm(name: str) -> bytes:
    return speech.synthesize_pcm(PROMPTS[name], config.DEVICE_TTS_GAIN)


def _pcm_response(pcm: bytes, headers: dict[str, str]) -> Response:
    headers = {"X-Sample-Rate": str(SAMPLE_RATE), "X-Audio-Format": "s16le-mono",
               "Cache-Control": "no-store", **headers}
    return Response(pcm, media_type="application/octet-stream", headers=headers)


def _do_turn(device_id: str, body: bytes) -> Response:
    t0 = time.perf_counter()
    samples = _samples_from_body(body)
    seconds = len(samples) / SAMPLE_RATE
    sid = _session_for(device_id)

    if seconds < MIN_SECONDS:
        return _pcm_response(_prompt_pcm("retry"), {"X-Status": "too_short", "X-Session": sid})

    stt = speech.transcribe_samples(samples)
    text = stt["text"].strip()
    t_stt = time.perf_counter()

    if not re.search(r"[A-Za-z]{2,}", text):
        state, reply, status = agent.get_state(sid), PROMPTS["retry"], "no_speech"
    else:
        state = agent.chat(sid, text)
        reply, status = state["reply"], "ok"
    t_agent = time.perf_counter()

    pcm = _prompt_pcm("retry") if status == "no_speech" else speech.synthesize_pcm(reply, config.DEVICE_TTS_GAIN)
    t_tts = time.perf_counter()

    cart = state.get("cart") or []
    tot = totals(cart)
    order = state.get("order") or {}
    timings = f"stt={int((t_stt - t0) * 1000)};agent={int((t_agent - t_stt) * 1000)};tts={int((t_tts - t_agent) * 1000)}"
    log.info("device %s heard %r -> %s (%s, %.1fs audio)", device_id, text, status, timings, seconds)
    return _pcm_response(pcm, {
        "X-Status": status,
        "X-Session": sid,
        "X-Transcript": _h(text),
        "X-Reply": _h(reply),
        "X-Stage": state.get("stage", "ordering"),
        "X-Total": str(tot["total"]),
        "X-Item-Count": str(tot["item_count"]),
        "X-Items": _h("; ".join(describe_line(l) for l in cart)),
        "X-Order-Number": order.get("number", ""),
        "X-Timings": timings,
    })


# ---------------------------------------------------------------- routes
@router.get("/prompt/{name}")
async def prompt(name: str, x_device_token: str | None = Header(None)):
    _auth(x_device_token)
    if name not in PROMPTS:
        raise HTTPException(404, f"Unknown prompt. Available: {', '.join(PROMPTS)}")
    pcm = await run_in_threadpool(_prompt_pcm, name)
    return _pcm_response(pcm, {"X-Reply": _h(PROMPTS[name])})


@router.post("/{device_id}/turn")
async def turn(request: Request, device_id: str = DeviceId, x_device_token: str | None = Header(None)):
    _auth(x_device_token)
    body = await request.body()
    if len(body) > MAX_SECONDS * SAMPLE_RATE * 2 + 4096:
        raise HTTPException(413, f"Recording longer than {MAX_SECONDS}s")
    try:
        return await run_in_threadpool(_do_turn, device_id, body)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("device turn failed")
        raise HTTPException(500, f"Turn failed: {exc}")


@router.post("/{device_id}/reset")
def reset(device_id: str = DeviceId, x_device_token: str | None = Header(None)):
    _auth(x_device_token)
    return {"session_id": _session_for(device_id, fresh=True)}


@router.get("/{device_id}")
def device_session(device_id: str = DeviceId, x_device_token: str | None = Header(None)):
    """For a tablet next to the voice unit: poll this and render the same cart."""
    _auth(x_device_token)
    from .main import _view  # local import: main imports this module

    with _lock:
        d = _devices.get(device_id)
    if not d:
        raise HTTPException(404, "Device has no session yet")
    try:
        state = agent.get_state(d["session_id"])
    except KeyError:
        raise HTTPException(404, "Session expired")
    return {"device_id": device_id, "session_id": d["session_id"], **_view(state)}
