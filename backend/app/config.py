"""Settings, read from environment variables (or backend/.env) with sensible local defaults."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
_env = BASE_DIR / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# LLM (Ollama)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi4-mini")
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "60m")
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "120"))

# Speech-to-text (faster-whisper, local)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "id") or None  # set empty for auto-detect
WHISPER_BEAM = int(os.getenv("WHISPER_BEAM", "5"))  # 1 = greedy (faster, more typos)
STT_FIX = os.getenv("STT_FIX", "1") != "0"  # respell menu words Whisper got wrong (app/stt_fix.py)
WHISPER_DIR = BASE_DIR / "models" / "whisper"

# Text-to-speech
TTS_ENGINE = os.getenv("TTS_ENGINE", "piper")  # piper (local) | edge (free online) | none
PIPER_VOICE = os.getenv("PIPER_VOICE", "id_ID-news_tts-medium")
PIPER_DIR = BASE_DIR / "models" / "piper"
EDGE_VOICE = os.getenv("EDGE_VOICE", "id-ID-GadisNeural")

# ESP32 / thin-client voice units (see app/device.py and esp32/)
DEVICE_TOKEN = os.getenv("DEVICE_TOKEN", "")  # empty = no auth (LAN prototype); set it in production
DEVICE_IDLE_RESET_S = float(os.getenv("DEVICE_IDLE_RESET_S", "180"))  # silent this long = next customer
DEVICE_TTS_GAIN = float(os.getenv("DEVICE_TTS_GAIN", "0.9"))  # volume of the PCM sent to the speaker

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3020,http://127.0.0.1:3020").split(",")
