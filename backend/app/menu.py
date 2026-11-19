"""
Menu, options and combo definitions for the coffee-shop kiosk (Bahasa Indonesia).

All prices are in IDR and live ONLY here. The LLM never computes or quotes a
price on its own: it receives prices from this module as facts.
"""
from __future__ import annotations

import difflib
import re

CURRENCY = "Rp"

# ---------------------------------------------------------------- options
SIZES = {"regular": 0, "large": 6000}
MILKS = {"regular": 0, "oat": 7000, "almond": 7000}
ADDONS = {
    "extra_shot": ("Tambah shot espresso", 6000),
    "vanilla_syrup": ("Sirup vanila", 5000),
    "caramel_syrup": ("Sirup karamel", 5000),
    "hazelnut_syrup": ("Sirup hazelnut", 5000),
    "whipped_cream": ("Whipped cream", 4000),
}
SUGAR_LEVELS = ["normal", "less", "none"]

# Indonesian labels for option values (used in replies and the UI)
LABEL = {
    "large": "besar", "regular": "reguler", "iced": "dingin", "hot": "panas",
    "oat": "susu oat", "almond": "susu almond", "less": "kurang manis", "none": "tanpa gula", "normal": "normal",
}

# ---------------------------------------------------------------- items
# kind: "drink" items take size/temperature/milk/addons/sugar, "food" items do not.
MENU: list[dict] = [
    # kopi
    {"id": "espresso", "name": "Espresso", "category": "coffee", "kind": "drink", "price": 22000,
     "temps": ["hot"], "milk": False, "desc": "Double shot dari house blend kami.",
     "aliases": ["espresso", "expresso", "kopi espresso"]},
    {"id": "americano", "name": "Americano", "category": "coffee", "kind": "drink", "price": 25000,
     "temps": ["hot", "iced"], "milk": False, "desc": "Espresso dengan air. Tegas dan bersih.",
     "aliases": ["americano", "amerikano", "black coffee", "kopi hitam", "long black"]},
    {"id": "cappuccino", "name": "Cappuccino", "category": "coffee", "kind": "drink", "price": 30000,
     "temps": ["hot", "iced"], "milk": True, "desc": "Espresso, susu panas, dan busa susu yang tebal.",
     "aliases": ["cappuccino", "capuccino", "cappucino", "kapucino", "kapuccino", "cappuccinos"]},
    {"id": "cafe_latte", "name": "Caffe Latte", "category": "coffee", "kind": "drink", "price": 32000,
     "temps": ["hot", "iced"], "milk": True, "desc": "Espresso lembut dengan banyak susu.",
     "aliases": ["latte", "lattes", "cafe latte", "caffe latte", "kafe latte", "late", "coffee latte"]},
    {"id": "caramel_macchiato", "name": "Caramel Macchiato", "category": "coffee", "kind": "drink",
     "price": 36000, "temps": ["hot", "iced"], "milk": True,
     "desc": "Vanila, susu, dan espresso dengan siraman karamel.",
     "aliases": ["caramel macchiato", "karamel macchiato", "macchiato", "makiato", "caramel latte"]},
    {"id": "mocha", "name": "Mocha", "category": "coffee", "kind": "drink", "price": 35000,
     "temps": ["hot", "iced"], "milk": True, "desc": "Espresso, cokelat, dan susu.",
     "aliases": ["mocha", "moka", "mochaccino", "cafe mocha"]},
    {"id": "kopi_susu_aren", "name": "Kopi Susu Gula Aren", "category": "coffee", "kind": "drink",
     "price": 28000, "temps": ["iced", "hot"], "milk": True,
     "desc": "Es kopi susu dengan manis gula aren. Paling laris di sini.",
     "aliases": ["kopi susu", "kopi susu gula aren", "gula aren", "es kopi susu", "kopsus", "kopi aren"]},
    {"id": "cold_brew", "name": "Cold Brew", "category": "coffee", "kind": "drink", "price": 30000,
     "temps": ["iced"], "milk": False, "desc": "Diseduh dingin 18 jam. Halus dan rendah asam.",
     "aliases": ["cold brew", "coldbrew", "kopi cold brew"]},
    # non-kopi
    {"id": "matcha_latte", "name": "Matcha Latte", "category": "non-coffee", "kind": "drink",
     "price": 34000, "temps": ["hot", "iced"], "milk": True, "desc": "Matcha Jepang dengan susu.",
     "aliases": ["matcha", "macha", "matcha latte", "green tea latte", "teh hijau"]},
    {"id": "chocolate", "name": "Signature Chocolate", "category": "non-coffee", "kind": "drink",
     "price": 30000, "temps": ["hot", "iced"], "milk": True, "desc": "Cokelat pekat dengan susu.",
     "aliases": ["chocolate", "coklat", "cokelat", "choco", "es coklat", "es cokelat", "hot chocolate",
                 "signature chocolate"]},
    {"id": "lemon_tea", "name": "Lemon Tea", "category": "non-coffee", "kind": "drink", "price": 22000,
     "temps": ["iced", "hot"], "milk": False, "desc": "Teh hitam dengan lemon segar.",
     "aliases": ["lemon tea", "teh lemon", "es teh lemon", "teh", "es teh", "ice tea", "iced tea"]},
    # makanan
    {"id": "croissant", "name": "Butter Croissant", "category": "food", "kind": "food", "price": 22000,
     "desc": "Renyah dan harum mentega, dipanggang pagi ini.",
     "aliases": ["croissant", "croissants", "butter croissant", "kroisan", "krosan", "croisant", "kroasan",
                 "kruasan", "kruasang", "krawasan", "krawasang", "kroasang", "kroisang"]},
    {"id": "banana_bread", "name": "Banana Bread", "category": "food", "kind": "food", "price": 25000,
     "desc": "Roti pisang lembut dengan kenari.",
     "aliases": ["banana bread", "roti pisang", "bolu pisang", "banana cake"]},
    {"id": "choco_muffin", "name": "Chocolate Muffin", "category": "food", "kind": "food", "price": 24000,
     "desc": "Muffin double cokelat.",
     "aliases": ["muffin", "mafin", "muffin coklat", "muffin cokelat", "chocolate muffin", "choco muffin"]},
    {"id": "cinnamon_roll", "name": "Cinnamon Roll", "category": "food", "kind": "food", "price": 26000,
     "desc": "Roti gulung kayu manis dengan glaze cream cheese.",
     "aliases": ["cinnamon roll", "cinnamon", "roti kayu manis", "kayu manis", "sinamon"]},
    {"id": "chicken_sandwich", "name": "Chicken Pesto Sandwich", "category": "food", "kind": "food",
     "price": 38000, "desc": "Ayam panggang, pesto, dan mozzarella di roti sourdough.",
     "aliases": ["sandwich", "sandwic", "sandwich ayam", "roti isi", "roti isi ayam", "chicken sandwich",
                 "chicken pesto sandwich"]},
]
MENU_BY_ID = {m["id"]: m for m in MENU}

# ---------------------------------------------------------------- combos
_COFFEE = {m["id"] for m in MENU if m["category"] == "coffee"}
_NONCOFFEE = {m["id"] for m in MENU if m["category"] == "non-coffee"}
_DRINKS = _COFFEE | _NONCOFFEE

COMBOS: list[dict] = [
    {"id": "lunch_set", "name": "Paket Makan Siang", "discount": 10000,
     "desc": "Minuman apa saja + Chicken Pesto Sandwich",
     "slots": [_DRINKS, {"chicken_sandwich"}], "upsell_food": "chicken_sandwich"},
    {"id": "morning_duo", "name": "Paket Pagi", "discount": 8000,
     "desc": "Kopi apa saja + Butter Croissant atau Banana Bread",
     "slots": [_COFFEE, {"croissant", "banana_bread"}], "upsell_food": "croissant"},
    {"id": "sweet_break", "name": "Paket Santai", "discount": 6000,
     "desc": "Minuman non-kopi + Chocolate Muffin atau Cinnamon Roll",
     "slots": [_NONCOFFEE, {"choco_muffin", "cinnamon_roll"}], "upsell_food": "choco_muffin"},
]
COMBO_BY_ID = {c["id"]: c for c in COMBOS}


def money(v: int) -> str:
    return f"{CURRENCY}{v:,.0f}".replace(",", ".")


# ---------------------------------------------------------------- matching
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())).strip()


_ALIAS_INDEX: dict[str, str] = {}
for _m in MENU:
    for _a in [_m["name"], _m["id"].replace("_", " "), *_m["aliases"]]:
        _ALIAS_INDEX[_norm(_a)] = _m["id"]


_COMPACT = {a.replace(" ", ""): i for a, i in _ALIAS_INDEX.items() if len(a) >= 5}
_OPTION_WORDS = {"es", "ice", "iced", "dingin", "panas", "hangat", "hot", "besar", "gede", "large", "kecil",
                 "reguler", "regular", "satu", "dua", "tiga", "empat", "lima", "se", "segelas", "secangkir",
                 "sepotong", "a", "an", "one", "two", "yang", "pakai", "pake", "susu", "oat", "almond", "ya"}


def match_item(name: str) -> str | None:
    """Resolve a free-text item name to a menu id (exact alias, contained alias, then fuzzy)."""
    n = _norm(name)
    if not n:
        return None
    if n in _ALIAS_INDEX:
        return _ALIAS_INDEX[n]
    hits = [a for a in _ALIAS_INDEX if re.search(rf"\b{re.escape(a)}\b", n)]
    if hits:
        return _ALIAS_INDEX[max(hits, key=len)]
    n = re.sub(r"nya\b", "", n)  # Indonesian "-nya" suffix: "lattenya" -> "latte"
    if n in _ALIAS_INDEX:
        return _ALIAS_INDEX[n]
    close = difflib.get_close_matches(n, list(_ALIAS_INDEX), n=1, cutoff=0.75)
    if close:
        return _ALIAS_INDEX[close[0]]
    # speech-to-text often splits or respells foreign words ("caput cinau", "kapu cino"): drop option words
    # ("es", "besar", "satu"...) and compare without spaces
    core = " ".join(w for w in n.split() if w not in _OPTION_WORDS)
    if core != n and (hit := (_ALIAS_INDEX.get(core) or None)):
        return hit
    compact = core.replace(" ", "")
    close = difflib.get_close_matches(compact, list(_COMPACT), n=1, cutoff=0.68)
    return _COMPACT[close[0]] if close else None


def find_items_in_text(text: str) -> list[str]:
    """Every menu id whose alias appears in the text (longest alias wins on overlap)."""
    n = f" {_norm(text)} "
    found: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for alias in sorted(_ALIAS_INDEX, key=len, reverse=True):
        for m in re.finditer(rf"(?<= ){re.escape(alias)}(?:nya)?(?= )", n):
            s, e = m.span()
            if any(s < te and e > ts for ts, te in taken):
                continue
            taken.append((s, e))
            found.append((s, _ALIAS_INDEX[alias]))
    return [i for _, i in sorted(found)]


def match_addon(name: str) -> str | None:
    n = _norm(name)
    if n.replace(" ", "_") in ADDONS:
        return n.replace(" ", "_")
    table = {
        "extra shot": "extra_shot", "double shot": "extra_shot", "tambah shot": "extra_shot",
        "shot": "extra_shot", "vanilla": "vanilla_syrup", "vanila": "vanilla_syrup",
        "caramel": "caramel_syrup", "karamel": "caramel_syrup", "hazelnut": "hazelnut_syrup",
        "whipped": "whipped_cream", "whip": "whipped_cream", "krim": "whipped_cream",
    }
    for k, v in table.items():
        if k in n:
            return v
    return None


def menu_for_prompt() -> str:
    """Compact menu listing used as grounding for the reply writer."""
    lines = [f"- {m['name']} ({m['category']}) {money(m['price'])}: {m['desc']}" for m in MENU]
    lines.append("Paket: " + "; ".join(f"{c['name']} = {c['desc']}, hemat {money(c['discount'])}"
                                       for c in COMBOS))
    return "\n".join(lines)


def public_menu() -> dict:
    return {
        "currency": CURRENCY,
        "items": [{k: v for k, v in m.items() if k != "aliases"} for m in MENU],
        "sizes": SIZES, "milks": MILKS,
        "addons": {k: {"label": v[0], "price": v[1]} for k, v in ADDONS.items()},
        "sugar_levels": SUGAR_LEVELS,
        "labels": LABEL,
        "combos": [{"id": c["id"], "name": c["name"], "discount": c["discount"], "desc": c["desc"]}
                   for c in COMBOS],
    }
