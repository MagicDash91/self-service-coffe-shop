"""
Speech-to-text accuracy check for the kiosk.

    .venv\\Scripts\\python tools\\stt_eval.py            # generate clips (once) and score the current pipeline
    .venv\\Scripts\\python tools\\stt_eval.py --baseline # also score the old pipeline (greedy, fixed prompt, no fix-up)

Each test sentence is spoken by two Indonesian neural voices (edge-tts, cached in tools/stt_eval_audio/), in
a clean and a "noisy" variant (quiet + cafe-like noise, like a cheap I2S mic). A clip passes when the
kiosk's own matchers pull the right menu items and options/answers out of the transcript, which is what
matters for ordering, not exact spelling.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import menu, speech  # noqa: E402
from app.agent import _CANCEL, _DONE, _NO, _PAY, _YES  # noqa: E402

AUDIO = Path(__file__).resolve().parent / "stt_eval_audio"
VOICES = ["id-ID-ArdiNeural", "id-ID-GadisNeural"]

# (sentence, expected menu ids, expected slots)
CASES: list[tuple[str, list[str], set[str]]] = [
    ("saya mau satu cappuccino panas", ["cappuccino"], {"hot"}),
    ("dua caffe latte dingin ya", ["cafe_latte"], {"iced"}),
    ("es kopi susu gula aren satu, yang besar", ["kopi_susu_aren"], {"iced", "large"}),
    ("caramel macchiato pakai susu oat", ["caramel_macchiato"], {"oat"}),
    ("matcha latte kurang manis", ["matcha_latte"], {"less"}),
    ("satu butter croissant sama cinnamon roll", ["croissant", "cinnamon_roll"], set()),
    ("americano dingin tanpa gula", ["americano"], {"iced", "nosugar"}),
    ("saya pesan mocha panas ukuran besar", ["mocha"], {"hot", "large"}),
    ("cold brew satu, banana bread satu", ["cold_brew", "banana_bread"], set()),
    ("signature chocolate dingin", ["chocolate"], {"iced"}),
    ("lemon tea dua", ["lemon_tea"], set()),
    ("chicken pesto sandwich satu", ["chicken_sandwich"], set()),
    ("chocolate muffin sama espresso", ["choco_muffin", "espresso"], set()),
    ("es cappuccino susu almond satu", ["cappuccino"], {"iced", "almond"}),
    ("kalau caramel macchiato yang dingin ada?", ["caramel_macchiato"], {"iced"}),
    ("tambah satu croissant lagi", ["croissant"], set()),
    ("lattenya dibikin besar ya", ["cafe_latte"], {"large"}),
    ("saya mau matcha dingin sama kopi susu panas", ["matcha_latte", "kopi_susu_aren"], {"iced", "hot"}),
    ("halo, saya mau pesan cinnamon roll sama americano panas", ["cinnamon_roll", "americano"], {"hot"}),
    ("iya boleh", [], {"yes"}),
    ("iya, saya ambil paketnya", [], {"yes"}),
    ("nggak usah, makasih", [], {"no"}),
    ("bayar pakai QRIS", [], {"qris"}),
    ("saya bayar tunai saja", [], {"cash"}),
    ("pakai kartu debit", [], {"card"}),
    ("sudah, itu aja", [], {"done"}),
]

_SLOTS = {
    "hot": re.compile(r"panas\b|\b(hangat|hot)\b"),
    "iced": re.compile(r"dingin\b|\b(es|iced|ice)\b"),
    "large": re.compile(r"\b(besar|gede|large)\b"),
    "oat": re.compile(r"\boat\b"),
    "almond": re.compile(r"\balmond\b"),
    "less": re.compile(r"\b(kurang manis|gula sedikit|sedikit gula)\b"),
    "nosugar": re.compile(r"\b(tanpa gula|nggak pakai gula|gak pakai gula)\b"),
    "qris": _PAY["qris"], "cash": _PAY["cash"], "card": _PAY["card"],
    "yes": _YES, "no": _NO, "done": _DONE, "cancel": _CANCEL,
}


def slots_in(text: str) -> set[str]:
    low = menu._norm(text)
    return {k for k, rx in _SLOTS.items() if rx.search(low)}


def score(text: str, items: list[str], slots: set[str]) -> tuple[bool, str]:
    got_items = menu.find_items_in_text(text)
    got_slots = slots_in(text)
    miss = [i for i in items if i not in got_items] + sorted(slots - got_slots)
    extra = [i for i in got_items if i not in items]
    ok = not miss and not extra
    return ok, ("" if ok else f"missing {miss} extra {extra}")


# ---------------------------------------------------------------- audio
def _clip_path(i: int, voice: str) -> Path:
    return AUDIO / f"{i:02d}_{voice.split('-')[2]}.wav"


async def _tts(text: str, voice: str, rate: str) -> bytes:
    import edge_tts
    out = bytearray()
    async for chunk in edge_tts.Communicate(text, voice, rate=rate).stream():
        if chunk["type"] == "audio":
            out += chunk["data"]
    return bytes(out)


def generate() -> None:
    AUDIO.mkdir(exist_ok=True)
    for i, (text, _, _) in enumerate(CASES):
        for v, voice in enumerate(VOICES):
            p = _clip_path(i, voice)
            if p.exists():
                continue
            for attempt in range(4):  # TLS on this network is flaky
                try:
                    mp3 = asyncio.run(_tts(text, voice, "+8%" if v else "-4%"))
                    break
                except Exception as exc:  # noqa: BLE001
                    print(f"  retry {voice} #{i}: {exc}")
                    time.sleep(2)
            else:
                raise SystemExit("edge-tts unreachable; try again (or on the VPN)")
            pcm = (np.clip(speech._decode(mp3), -1, 1) * 32767).astype("<i2")
            with wave.open(str(p), "wb") as wf:
                wf.setnchannels(1), wf.setsampwidth(2), wf.setframerate(16000)
                wf.writeframes(pcm.tobytes())
            print(f"  clip {p.name}")


def load(p: Path) -> np.ndarray:
    with wave.open(str(p)) as wf:
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype(np.float32) / 32768.0


def noisy(x: np.ndarray, seed: int) -> np.ndarray:
    """Quiet, band-limited speech with cafe-like noise (~12 dB SNR), like an INMP441 at arm's length."""
    rng = np.random.default_rng(seed)
    y = x * 0.18
    y = np.convolve(y, np.ones(3) / 3, mode="same")              # dull the highs
    noise = np.cumsum(rng.standard_normal(len(y))) * 0.02         # rumble (brown-ish)
    noise -= np.convolve(noise, np.ones(400) / 400, mode="same")  # keep it zero-mean
    noise += rng.standard_normal(len(y))                          # hiss
    sp = np.sqrt(np.mean(y ** 2) + 1e-12)
    noise *= sp / (np.sqrt(np.mean(noise ** 2)) + 1e-12) / (10 ** (12 / 20))
    return np.clip(y + noise, -1, 1).astype(np.float32)


# ---------------------------------------------------------------- pipelines
_OLD_HOTWORDS = ("Kopi Susu Gula Aren, latte, cappuccino, americano, espresso, caramel macchiato, mocha, "
                 "cold brew, matcha, croissant, banana bread, muffin, cinnamon roll, sandwich, susu oat, "
                 "susu almond, tambah shot, kurang manis, tanpa gula, es, panas, besar, QRIS, tunai, kartu")


def baseline(samples: np.ndarray) -> str:
    """The pipeline as it was before the STT upgrade."""
    segs, _ = speech._get_whisper().transcribe(
        samples, language="id", beam_size=1, vad_filter=True,
        initial_prompt=f"Pesanan di kedai kopi. Menu: {_OLD_HOTWORDS}.")
    return " ".join(s.text.strip() for s in segs).strip()


def current(samples: np.ndarray) -> str:
    return speech.transcribe_samples(samples)["text"]


def run(name: str, fn) -> float:
    print(f"\n=== {name} ===")
    passed = total = 0
    t_all = 0.0
    fails = []
    for i, (text, items, slots) in enumerate(CASES):
        for voice in VOICES:
            clean = load(_clip_path(i, voice))
            for variant, x in (("clean", clean), ("noisy", noisy(clean, i))):
                t0 = time.perf_counter()
                out = fn(x)
                t_all += time.perf_counter() - t0
                ok, why = score(out, items, slots)
                total += 1
                passed += ok
                if not ok:
                    fails.append(f"  [{variant:5} {voice.split('-')[2]:5}] said {text!r}\n"
                                 f"      heard {out!r} -> {why}")
    print("\n".join(fails))
    acc = passed / total
    print(f"{name}: {passed}/{total} correct ({acc:.0%}), avg {t_all / total:.2f}s per clip")
    return acc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true")
    args = ap.parse_args()
    generate()
    speech._get_whisper()
    results = {}
    if args.baseline:
        results["baseline"] = run("baseline", baseline)
    results["current"] = run("current", current)
    print("\n" + "  ".join(f"{k}={v:.0%}" for k, v in results.items()))
