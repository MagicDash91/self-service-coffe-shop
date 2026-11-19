"""
Pretend to be the ESP32 voice unit: send raw 16 kHz PCM to /api/device/{id}/turn and save the reply.

    .venv\\Scripts\\python tools\\device_sim.py "dua caffe latte dingin"      # text -> server TTS -> as "speech"
    .venv\\Scripts\\python tools\\device_sim.py --wav my_recording.wav       # a real recording
    .venv\\Scripts\\python tools\\device_sim.py --reset                      # new order

The reply audio is written to reply_<n>.wav next to this script, so you can listen to it.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import wave
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.speech import _decode  # noqa: E402  (PyAV only, no models loaded)


def _req(url: str, data: bytes | None = None, headers: dict | None = None, method: str | None = None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    return urllib.request.urlopen(req, timeout=300)


def to_pcm16k(audio: bytes) -> bytes:
    import numpy as np
    return (np.clip(_decode(audio), -1, 1) * 32767).astype("<i2").tobytes()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", help="what the customer says (synthesised by the server's TTS)")
    ap.add_argument("--wav", help="send this audio file instead")
    ap.add_argument("--reset", action="store_true", help="start a new order for the device")
    ap.add_argument("--server", default="http://127.0.0.1:8020")
    ap.add_argument("--device", default="kiosk-1")
    ap.add_argument("--token", default="")
    a = ap.parse_args()
    auth = {"X-Device-Token": a.token} if a.token else {}

    if a.reset:
        print(json.load(_req(f"{a.server}/api/device/{a.device}/reset", b"", auth, "POST")))
        return
    if a.wav:
        audio = Path(a.wav).read_bytes()
    elif a.text:
        audio = _req(f"{a.server}/api/tts", json.dumps({"text": a.text}).encode(),
                     {"Content-Type": "application/json"}).read()
    else:
        ap.error("give TEXT, --wav or --reset")

    pcm = to_pcm16k(audio)
    print(f"sending {len(pcm) / 32000:.1f}s of raw PCM ({len(pcm)} bytes)")
    with _req(f"{a.server}/api/device/{a.device}/turn", pcm,
              {"Content-Type": "application/octet-stream", **auth}, "POST") as r:
        reply = r.read()
        h = r.headers
    for k in ("X-Status", "X-Transcript", "X-Reply", "X-Stage", "X-Total", "X-Items", "X-Order-Number", "X-Timings"):
        print(f"{k:15} {unquote(h.get(k, ''))}")

    out_dir = Path(__file__).resolve().parent
    n = len(list(out_dir.glob("reply_*.wav"))) + 1
    out = out_dir / f"reply_{n}.wav"
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(h.get("X-Sample-Rate", 16000)))
        wf.writeframes(reply)
    print(f"reply audio: {len(reply) / 32000:.1f}s -> {out}")


if __name__ == "__main__":
    main()
