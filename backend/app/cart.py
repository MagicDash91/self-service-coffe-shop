"""
Cart maths: line pricing, automatic combo discounts and combo upsell offers.

Everything here is deterministic Python so totals are always correct, whatever
the LLM says. The agent only decides WHAT to do; this module does the sums.
"""
from __future__ import annotations

import uuid

from .menu import ADDONS, COMBO_BY_ID, COMBOS, LABEL, MENU_BY_ID, MILKS, SIZES, SUGAR_LEVELS, money

# upsell preference: cheapest add-on first, the sandwich last
_UPSELL_ORDER = ["morning_duo", "sweet_break", "lunch_set"]


def build_line(item_id: str, qty: int = 1, size: str | None = None, temperature: str | None = None,
               milk: str | None = None, addons: list[str] | None = None,
               sugar: str | None = None) -> tuple[dict, list[str]]:
    """Create a priced cart line. Returns (line, notes) where notes explain any option we had to drop."""
    item = MENU_BY_ID[item_id]
    notes: list[str] = []
    qty = max(1, min(int(qty or 1), 20))
    line = {"line_id": uuid.uuid4().hex[:8], "item_id": item_id, "name": item["name"],
            "kind": item["kind"], "qty": qty}

    if item["kind"] == "drink":
        line["size"] = size if size in SIZES else "regular"
        temps = item["temps"]
        if temperature and temperature not in temps:
            notes.append(f"{item['name']} hanya tersedia {LABEL[temps[0]]}")
        line["temperature"] = temperature if temperature in temps else temps[0]
        if milk and milk != "regular" and not item["milk"]:
            notes.append(f"{item['name']} tidak pakai susu, jadi pilihan {LABEL.get(milk, milk)} dilewati")
            milk = None
        line["milk"] = milk if (milk in MILKS and item["milk"]) else ("regular" if item["milk"] else None)
        line["addons"] = sorted({a for a in (addons or []) if a in ADDONS})
        line["sugar"] = sugar if sugar in SUGAR_LEVELS else "normal"
    price_line(line)
    return line, notes


def price_line(line: dict) -> dict:
    item = MENU_BY_ID[line["item_id"]]
    unit = item["price"]
    if line["kind"] == "drink":
        unit += SIZES.get(line.get("size") or "regular", 0)
        unit += MILKS.get(line.get("milk") or "regular", 0)
        unit += sum(ADDONS[a][1] for a in line.get("addons", []))
    line["unit_price"] = unit
    line["line_total"] = unit * line["qty"]
    return line


def describe_line(line: dict) -> str:
    """'2x Caffe Latte besar dingin (susu oat, tambah shot espresso, kurang manis)'."""
    parts = [f"{line['qty']}x", line["name"]]
    if line["kind"] == "drink":
        if line.get("size") == "large":
            parts.append("besar")
        temps = MENU_BY_ID[line["item_id"]]["temps"]
        if len(temps) > 1 and line.get("temperature"):
            parts.append(LABEL[line["temperature"]])
    extras = []
    if line.get("milk") and line["milk"] != "regular":
        extras.append(LABEL[line["milk"]])
    extras += [ADDONS[a][0].lower() for a in line.get("addons", [])]
    if line.get("sugar") and line["sugar"] != "normal":
        extras.append(LABEL[line["sugar"]])
    s = " ".join(parts)
    return f"{s} ({', '.join(extras)})" if extras else s


# ---------------------------------------------------------------- combos
def _units(cart: list[dict]) -> list[dict]:
    """Expand lines into single units so one unit can belong to only one combo."""
    out = []
    for line in cart:
        for _ in range(line["qty"]):
            out.append({"item_id": line["item_id"], "unit_price": line["unit_price"]})
    return out


def apply_combos(cart: list[dict]) -> list[dict]:
    """Greedy: biggest discount first, each unit used once."""
    units = _units(cart)
    used = [False] * len(units)
    applied: list[dict] = []
    for combo in sorted(COMBOS, key=lambda c: -c["discount"]):
        while True:
            picks: list[int] = []
            for slot in combo["slots"]:
                idx = next((i for i, u in enumerate(units)
                            if not used[i] and i not in picks and u["item_id"] in slot), None)
                if idx is None:
                    break
                picks.append(idx)
            if len(picks) != len(combo["slots"]):
                break
            for i in picks:
                used[i] = True
            applied.append({"combo_id": combo["id"], "name": combo["name"], "discount": combo["discount"],
                            "items": [MENU_BY_ID[units[i]["item_id"]]["name"] for i in picks]})
    return applied


def totals(cart: list[dict]) -> dict:
    subtotal = sum(l["line_total"] for l in cart)
    combos = apply_combos(cart)
    discount = sum(c["discount"] for c in combos)
    return {"subtotal": subtotal, "discount": discount, "total": subtotal - discount,
            "combos": combos, "item_count": sum(l["qty"] for l in cart)}


def find_upsell(cart: list[dict], already_offered: list[str]) -> dict | None:
    """A combo the customer is ONE item away from (has the drink, is missing the food)."""
    if not cart:
        return None
    base = len(apply_combos(cart))
    for cid in _UPSELL_ORDER:
        if cid in already_offered:
            continue
        combo = COMBO_BY_ID[cid]
        trial = cart + [build_line(combo["upsell_food"])[0]]
        if len(apply_combos(trial)) > base:
            food = MENU_BY_ID[combo["upsell_food"]]
            return {"combo_id": cid, "combo_name": combo["name"], "add_item_id": food["id"],
                    "add_item_name": food["name"], "add_item_price": food["price"],
                    "discount": combo["discount"],
                    "pitch": f"Mau tambah {food['name']} ({money(food['price'])}) supaya jadi "
                             f"{combo['name']} dan hemat {money(combo['discount'])}"}
    return None


def cart_summary(cart: list[dict]) -> str:
    if not cart:
        return "Pesanan masih kosong."
    t = totals(cart)
    lines = [f"- {describe_line(l)} = {money(l['line_total'])}" for l in cart]
    for c in t["combos"]:
        lines.append(f"- potongan {c['name']} -{money(c['discount'])}")
    lines.append(f"Total: {money(t['total'])}")
    return "\n".join(lines)
