"""
Transcript fix-up: snaps Whisper's misspellings of the kiosk vocabulary back to the real words before the
agent reads the text.

    "es caput cinau besar"        -> "es cappuccino besar"
    "satu caffola tedingin"       -> "satu caffe latte dingin"
    "karamel makiato susu ot"     -> "caramel macchiato susu oat"

Only words from the kiosk's own vocabulary (menu names and aliases, options, payment, yes/no answers)
can be produced, and only from 1-4 word windows that look close to one of them after a light Indonesian
phonetic folding (c/k/q, ch, ph, doubled letters...). Everyday Indonesian words ("saya", "mau", "sama")
are never rewritten.
"""
from __future__ import annotations

import difflib
import re
from functools import lru_cache

from .menu import COMBOS, MENU, _norm

# words that must never be rewritten (and never form a window on their own)
_KEEP = set("""
saya aku mau pesan minta beli ambil tambah tambahin lagi satu dua tiga empat lima enam tujuh delapan sembilan
sepuluh se sama dan atau dengan pakai pake yang itu ini aja saja ya iya ia ok oke boleh nggak gak ga enggak
tidak usah sudah udah cukup kalau kalo ada apa berapa dong deh kak mas mbak terima kasih makasih halo hai
permisi bayar total jadi buat untuk di ke dari nya gelas cup porsi ukuran dibikin bikin jangan tanpa kurang
manis gula susu es panas dingin hangat besar kecil sedang paket mana enak rekomendasi lapar haus tolong
pagi siang sore malam batal ganti hapus selesai mulai ulang makan minum makanan minuman kue roti
camilan sarapan juga lain semua banyak sedikit nanti dulu
""".split())

# options and answers the agent's regexes look for
_PHRASES = ["dingin", "panas", "hangat", "besar", "kecil", "sedang", "kurang manis", "tanpa gula",
            "susu oat", "susu almond", "extra shot", "qris", "tunai", "kartu debit", "kartu kredit",
            "iya boleh", "nggak usah", "sudah itu aja", "makasih"]


def _fold(s: str) -> str:
    """Rough Indonesian ear: how Whisper tends to respell foreign menu words."""
    s = s.replace(" ", "")
    for a, b in (("cch", "k"), ("ch", "c"), ("ph", "f"), ("qu", "k"), ("q", "k"), ("x", "ks"), ("c", "k"),
                 ("y", "i"), ("v", "f"), ("z", "s"), ("w", "u"), ("ee", "i"), ("oo", "u")):
        s = s.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", s)  # cappuccino -> kapukino, latte -> late


def _build() -> tuple[dict[str, str], set[str]]:
    """folded form -> canonical text to write; plus every exact phrase that needs no fixing."""
    target: dict[str, str] = {}
    exact: set[str] = set()
    for m in MENU:
        canon = m["name"].lower()
        for a in [m["name"], *m["aliases"]]:
            a = _norm(a)
            exact.add(a)
            if len(a.replace(" ", "")) >= 4:
                target.setdefault(_fold(a), canon if a not in (m["aliases"][0],) else a)
    for c in COMBOS:
        a = _norm(c["name"])
        exact.add(a)
        target.setdefault(_fold(a), a)
    for p in _PHRASES:
        exact.add(p)
        if len(p.replace(" ", "")) >= 4:
            target.setdefault(_fold(p), p)
    return target, exact


_TARGET, _EXACT = _build()
_TARGET_KEYS = list(_TARGET)

# spellings Whisper has actually produced on this kiosk that fuzzy matching can't reach safely
_RESPELL = {"kyuris": "qris", "kiuris": "qris", "kyu ris": "qris", "q ris": "qris", "ia boleng": "iya boleh",
            "iya boleng": "iya boleh", "ia boleh": "iya boleh", "gausah": "nggak usah", "gak usah": "nggak usah",
            "ngga usah": "nggak usah", "gamau": "nggak mau", "kris": "qris"}
_RESPELL_RE = re.compile(r"\b(" + "|".join(map(re.escape, sorted(_RESPELL, key=len, reverse=True))) + r")\b")

# Whisper glues a short option word onto the previous word ("tedingin", "lattepanas"): split it off
_GLUED = re.compile(r"\b([a-z]{2,})(dingin|panas|hangat|satu|dua|tiga)\b")
# ... and "-nya"/"-ya" onto an option ("dinginnya", "besarnya") -> "dingin ya"
_OPT_NYA = re.compile(r"\b(dingin|panas|hangat|besar|kecil)n?(?:nya|ya)\b")
# ... and digits: "Lemon T2" -> "lemon t 2"
_DIGIT = re.compile(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])")


def _cutoff(n: int) -> float:
    """Shorter words need a closer match (4 letters: 1 edit at most, never 2)."""
    return 0.86 if n <= 5 else 0.8 if n <= 8 else 0.76


@lru_cache(maxsize=4096)
def _best(window: str, strict: bool = False) -> str | None:
    key = _fold(window)
    if len(key) < 4:
        return None
    cutoff = 0.88 if strict else _cutoff(len(key))
    for hit in difflib.get_close_matches(key, _TARGET_KEYS, n=3, cutoff=cutoff):
        # similar length only: "makan siang" (lunch) is not "paket makan siang"
        if 0.75 <= len(key) / len(hit) <= 1.25:
            return _TARGET[hit]
    return None


_FIRST_WORDS = {p.split()[0] for p in _EXACT if len(p.split()[0]) >= 4}


def _split_es(word: str) -> str:
    """Whisper glues "es" (iced) onto the drink: "eskopi", "escapuccino" -> "es kopi", "es capuccino".
    Without this the fuzzy step would read "eskopi susu" as "kopi susu" and lose the "iced"."""
    if not word.startswith("es") or len(word) < 6 or word in _EXACT or word in _KEEP:
        return word
    rest = word[2:]
    # split only when what follows "es" is itself a menu word ("espreso" -> "preso" isn't, so it stays
    # one word and gets fixed to espresso)
    return f"es {rest}" if rest in _FIRST_WORDS or _best(rest) else word


def correct(text: str) -> str:
    """Return the transcript with kiosk words respelled; everything else is left as Whisper wrote it
    (lower-cased, punctuation dropped)."""
    low = _norm(text)
    if not low:
        return ""
    low = _GLUED.sub(lambda m: m.group(0) if m.group(1) in _KEEP | {"ber", "ke", "di"} or m.group(0) in _EXACT
                     else f"{m.group(1)} {m.group(2)}", low)
    low = _DIGIT.sub(" ", low)
    low = _OPT_NYA.sub(r"\1 ya", low)
    low = " ".join(_split_es(w) for w in low.split())
    low = _RESPELL_RE.sub(lambda m: _RESPELL[m.group(1)], low)
    words = low.split()
    out: list[str] = []
    i = 0
    while i < len(words):
        done = False
        for n in (4, 3, 2, 1):
            win = words[i:i + n]
            if len(win) < n:
                continue
            phrase = " ".join(win)
            if phrase in _EXACT:  # already right: keep it, and don't let a longer window swallow it
                out.append(phrase)
                i += n
                done = True
                break
            if all(w in _KEEP for w in win) or any(w.isdigit() for w in win):
                continue
            # a window holding an already-correct menu word ("kue coklat") is merged only on a very
            # close match ("matca late" -> "matcha latte"), so "kue" isn't swallowed into a drink
            fixed = _best(phrase, strict=n > 1 and any(w in _EXACT for w in win))
            # an everyday word at the edge must survive into the fix ("susu ot" -> "susu oat" is fine,
            # "satu caput" -> "cappuccino" would eat the quantity)
            if fixed and ((win[0] in _KEEP and not fixed.startswith(win[0] + " ")) or
                          (win[-1] in _KEEP and not fixed.endswith(" " + win[-1]))):
                fixed = None
            if fixed:
                out.append(fixed)
                i += n
                done = True
                break
        if not done:
            out.append(words[i])
            i += 1
    # the agent treats a trailing "?" as a question ("cappuccino ada?"), so keep it
    return " ".join(out) + ("?" if text.rstrip().endswith("?") else "")
