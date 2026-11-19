"""
LangGraph ordering agent for the self-service kiosk (Bahasa Indonesia).

    understand ──► cart_ops ──► upsell ──► respond
        │      ├─► checkout ─────────────► respond
        │      ├─► payment ──────────────► respond
        │      ├─► info ─────────────────► respond
        │      └─► cancel ───────────────► respond
        └─────────────────────────────────► respond   (sapaan / obrolan)

* understand: cheap regex rules first (iya/nggak to an offer, payment method,
  "sudah itu saja"), otherwise ONE Phi-4-mini call in JSON mode. Its output is
  validated against the menu, so a hallucinated item never reaches the cart.
* Every price, combo and total is computed in cart.py, never by the model.
* respond: templated Indonesian text for transactional turns (fast, exact
  numbers); Phi-4-mini only writes free-form replies (recommendations, chat).

Conversation state is kept by LangGraph's checkpointer, one thread per kiosk
session, so tap-to-order in the UI and voice/text orders share one cart.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
import uuid
from typing import Any, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from . import config, orders
from .cart import build_line, cart_summary, describe_line, find_upsell, price_line, totals
from .menu import (LABEL, MENU, MENU_BY_ID, find_items_in_text, match_addon, match_item, menu_for_prompt,
                   money)

log = logging.getLogger("kiosk.agent")

INTENTS = ["add_items", "remove_items", "modify_item", "view_cart", "checkout", "choose_payment",
           "cancel_order", "browse_menu", "ask_item_info", "recommendation", "accept_offer",
           "decline_offer", "greeting", "other"]
Stage = Literal["ordering", "confirming", "paying", "done"]
CATEGORY_ID = {"coffee": "kopi", "non-coffee": "non-kopi", "food": "makanan"}


class KioskState(TypedDict, total=False):
    # input for this turn
    text: str
    # persistent across turns (checkpointed)
    cart: list[dict]
    stage: Stage
    pending_offer: dict | None
    offered: list[str]
    last_line_id: str | None
    order: dict | None
    history: list[dict]
    # per-turn scratch
    nlu: dict
    nlu_source: str
    events: list[str]
    reply: str
    suggestions: list[str]
    timings: dict


# ---------------------------------------------------------------- LLMs
def _llm(json_mode: bool) -> ChatOllama:
    kw: dict[str, Any] = dict(model=config.OLLAMA_MODEL, base_url=config.OLLAMA_URL,
                              keep_alive=config.OLLAMA_KEEP_ALIVE,
                              client_kwargs={"timeout": config.LLM_TIMEOUT_S})
    if json_mode:
        return ChatOllama(format="json", temperature=0, num_predict=220, **kw)
    return ChatOllama(temperature=0.4, num_predict=120, **kw)


NLU_LLM = _llm(json_mode=True)
CHAT_LLM = _llm(json_mode=False)

# Instructions stay in English (small models follow English instructions best); the customer speaks Indonesian.
NLU_SYSTEM = """You are the order-understanding module of a coffee shop self-service kiosk in Indonesia.
The customer speaks Indonesian (sometimes mixed with English). Read the message and return ONLY a JSON object:
{"intent": one of %s,
 "items": [{"name": str, "qty": int, "size": "regular"|"large"|null, "temp": "hot"|"iced"|null,
            "milk": "regular"|"oat"|"almond"|null, "addons": [str], "sugar": "normal"|"less"|"none"|null}],
 "target": str|null,
 "changes": {"size":..,"temp":..,"milk":..,"addons":[..],"sugar":..,"qty":..}|null,
 "payment": "qris"|"card"|"cash"|null,
 "category": "coffee"|"non-coffee"|"food"|null}

Intent guide:
- add_items: customer orders something ("pesan", "mau", "minta", "beli", "tambah"). Put every product in "items".
- remove_items: remove something ("hapus", "nggak jadi", "batalin <item>", "kurangi"). "target" = product name.
- modify_item: change an item already ordered ("ganti", "ubah", "jadiin", "yang ... dibikin ..."). "target" = product or null for the last item, "changes" = only what changes.
- view_cart: wants to hear the order or total ("pesanan saya apa aja", "totalnya berapa").
- checkout: finished ordering ("sudah", "itu aja", "cukup", "bayar").
- choose_payment: says how to pay. Set "payment" (QRIS/e-wallet = qris, kartu/debit = card, tunai = cash).
- cancel_order: cancel everything / start over ("batalkan pesanan", "ulang dari awal").
- browse_menu: asks what is available ("ada apa aja", "menunya apa"). Set "category" if mentioned (kopi = coffee, non-kopi = non-coffee, makanan/kue/roti/pastry = food).
- ask_item_info: asks about one product (apa itu, harganya berapa, isinya apa). "target" = product.
- recommendation: asks for a suggestion ("rekomendasi", "yang enak apa", "saran dong").
- accept_offer / decline_offer: yes / no to the combo the kiosk just offered.
- greeting: halo / pagi. other: anything else.
Word meanings: besar/large/gede = large, kecil/sedang/reguler = regular, es/dingin/ice = iced, panas/hangat/hot = hot,
susu oat = oat, susu almond = almond, kurang manis/gula sedikit/less sugar = less, tanpa gula/no sugar = none,
tambah shot/extra shot, sirup vanila/karamel/hazelnut, whipped cream. Numbers: satu=1, dua=2, tiga=3, empat=4, lima=5.
Only include products the customer actually said. Use null for anything not mentioned.

Examples:
"saya mau dua es latte pakai susu oat sama satu croissant" -> {"intent":"add_items","items":[{"name":"latte","qty":2,"size":null,"temp":"iced","milk":"oat","addons":[],"sugar":null},{"name":"croissant","qty":1,"size":null,"temp":null,"milk":null,"addons":[],"sugar":null}],"target":null,"changes":null,"payment":null,"category":null}
"lattenya dibikin besar ya, kurang manis" -> {"intent":"modify_item","items":[],"target":"latte","changes":{"size":"large","sugar":"less"},"payment":null,"category":null}
"croissantnya nggak jadi deh" -> {"intent":"remove_items","items":[],"target":"croissant","changes":null,"payment":null,"category":null}
"yang nggak terlalu manis apa ya? ada rekomendasi?" -> {"intent":"recommendation","items":[],"target":null,"changes":null,"payment":null,"category":null}
"kuenya ada apa aja?" -> {"intent":"browse_menu","items":[],"target":null,"changes":null,"payment":null,"category":"food"}
""" % json.dumps(INTENTS)


# ---------------------------------------------------------------- rules
_YES = re.compile(r"^\s*(iya+|iy[ae]|ia|ya+|yoi|bole[hn]g?|mau|oke+|ok|okay|sip|siap|gas|setuju|tentu|yes|yeah|sure|please)\b",
                  re.I)
_NO = re.compile(r"^\s*(tidak|enggak|nggak|ngga|gak|ga|nope|no|nah|skip|engga|tidak usah|nggak usah|gak usah|"
                 r"ga usah|udah cukup|sudah cukup)\b", re.I)
_DONE = re.compile(r"\b(sudah (itu )?(saja|aja)|udah (itu )?(aja|saja)|itu (saja|aja)|cukup|sudah|udah|selesai|"
                   r"checkout|check out|bayar|that'?s all|i'?m done|done)\b", re.I)
_CANCEL = re.compile(r"\b(batal(kan|in)? (semua|pesanan|order)|batalkan|ulang dari awal|mulai (lagi|ulang)|"
                     r"hapus semua|cancel( (my|the))? order|start over)\b", re.I)
_CART = re.compile(r"\b(pesanan (saya|aku|ku)|pesananku|total(nya)? (berapa|jadi berapa)|berapa total(nya)?|"
                   r"jadi berapa|lihat pesanan|cek pesanan|my order|show (my )?order)\b", re.I)
_PAY = {"qris": re.compile(r"\b(qris|qr|kyuris|scan|gopay|ovo|dana|shopee ?pay|e-?wallet|dompet digital)\b", re.I),
        "card": re.compile(r"\b(kartu|debit|kredit|credit|card|visa|master ?card|gesek|tap kartu)\b", re.I),
        "cash": re.compile(r"\b(tunai|cash|kes|uang tunai|bayar di kasir|di kasir)\b", re.I)}
_HELLO = re.compile(r"^\s*(hai|halo|hallo|helo|hi|hello|permisi|pagi|siang|sore|malam|"
                    r"selamat (pagi|siang|sore|malam))\W*(kak|mas|mbak|min)?\W*$", re.I)
_QUESTION = re.compile(r"\?|\b(apa|apakah|berapa|gimana|bagaimana|yang mana|ada (gak|nggak|ga|tidak))\b", re.I)


_RECO = re.compile(r"\b(rekomendasi|rekomen|saran|sarankan|enaknya|yang enak|cocok|lapar|laper|haus|seger|segar|"
                   r"kenyang|nggak terlalu|gak terlalu|ga terlalu|tidak terlalu|yang manis|yang pahit|yang ringan|"
                   r"recommend|suggest)\b", re.I)


def _payment_in(text: str) -> str | None:
    for method, rx in _PAY.items():
        if rx.search(text):
            return method
    return None


def _rule_nlu(text: str, state: KioskState) -> dict | None:
    t = text.strip()
    has_items = bool(find_items_in_text(t))
    stage = state.get("stage", "ordering")
    if state.get("pending_offer") and not has_items:
        if _NO.search(t):
            return {"intent": "decline_offer"}
        if _YES.search(t):
            return {"intent": "accept_offer"}
    if stage in ("confirming", "paying") and (pm := _payment_in(t)) and not has_items:
        return {"intent": "choose_payment", "payment": pm}
    if stage == "confirming" and _YES.search(t) and not has_items:
        return {"intent": "checkout"}
    if _CANCEL.search(t) and not has_items:
        return {"intent": "cancel_order"}
    if _CART.search(t) and not has_items:
        return {"intent": "view_cart"}
    if _DONE.search(t) and not has_items and not _QUESTION.search(t):
        pm = _payment_in(t)
        return {"intent": "choose_payment", "payment": pm} if pm else {"intent": "checkout"}
    if _HELLO.match(t):
        return {"intent": "greeting"}
    return None


_NUM_WORDS = {"satu": 1, "se": 1, "sebuah": 1, "secangkir": 1, "segelas": 1, "sepotong": 1, "dua": 2, "tiga": 3,
              "empat": 4, "lima": 5, "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9, "sepuluh": 10,
              "a": 1, "an": 1, "one": 1, "two": 2, "three": 3}


def _fallback_nlu(text: str) -> dict:
    """Used when the LLM is down or returns junk: keyword spotting with simple quantities."""
    ids = find_items_in_text(text)
    if not ids:
        return {"intent": "other"}
    low = text.lower()
    items = []
    for iid in ids:
        qty = 1
        m = MENU_BY_ID[iid]
        alias = next((a for a in [m["name"].lower(), *m["aliases"]] if a in low), "")
        if alias:
            for w in reversed(low[:low.find(alias)].split()[-3:]):
                if w.isdigit():
                    qty = int(w)
                    break
                if w in _NUM_WORDS:
                    qty = _NUM_WORDS[w]
                    break
        items.append({"name": iid, "qty": qty,
                      "temp": "iced" if re.search(r"dingin\b|\b(es|iced|ice)\b", low) else
                      ("hot" if re.search(r"panas\b|\b(hangat|hot)\b", low) else None),
                      "size": "large" if re.search(r"\b(besar|gede|large)\b", low) else None})
    return {"intent": "add_items", "items": items}


_SAID = {
    "size": re.compile(r"\b(besar|gede|kecil|sedang|reguler|regular|large|small|medium|big)\b", re.I),
    "temp": re.compile(r"dingin\b|panas\b|\b(es|hangat|iced|ice|cold|hot|warm)\b", re.I),
    "milk": re.compile(r"\b(oat|almond|susu|milk)\b", re.I),
    "sugar": re.compile(r"\b(gula|manis|sugar|sweet)\b", re.I),
}


def _drop_unsaid_options(item: dict, text: str) -> dict:
    """Small models copy options from the context ("dingin" from the previous drink). Keep only what was said."""
    item = dict(item)
    for key, rx in _SAID.items():
        if not rx.search(text):
            item[key] = None
            if key == "temp":
                item["temperature"] = None
    return item


def _fill_options_from_text(items: list[dict], text: str) -> None:
    """With a single drink in the order, options the customer clearly said are applied even if the model
    left them empty ("es caput cinau besar" -> iced, large)."""
    drinks = [i for i in items if (iid := match_item(str(i.get("name", "")))) and MENU_BY_ID[iid]["kind"] == "drink"]
    if len(drinks) != 1:
        return
    it = drinks[0]
    if not (it.get("temp") or it.get("temperature")):
        if re.search(r"dingin\b|\b(es|iced|ice|cold)\b", text, re.I):
            it["temp"] = "iced"
        elif re.search(r"panas\b|\b(hangat|hot|warm)\b", text, re.I):
            it["temp"] = "hot"
    if not it.get("size") and re.search(r"\b(besar|gede|large|big)\b", text, re.I):
        it["size"] = "large"
    if not it.get("milk"):
        if re.search(r"\boat\b", text, re.I):
            it["milk"] = "oat"
        elif re.search(r"\balmond\b", text, re.I):
            it["milk"] = "almond"
    if not it.get("sugar"):
        if re.search(r"\b(tanpa gula|no sugar|gak pakai gula|nggak pakai gula)\b", text, re.I):
            it["sugar"] = "none"
        elif re.search(r"\b(kurang manis|gula sedikit|less sugar|sedikit gula)\b", text, re.I):
            it["sugar"] = "less"


_NO_SUCH = re.compile(r"\b(?:ada|jual|punya|sedia|do you have)\s+(?!yang\b|apa\b)([a-z][a-z ]{1,30}?)\s*"
                      r"(?:\b(?:gak|nggak|ga|tidak|ngga|enggak|kak|mas|mbak|min|nggak sih|ya|kah|gk)\b\s*)*\??$", re.I)
_GENERIC = {"kopi", "makanan", "minuman", "kue", "roti", "pastry", "snack", "cemilan", "camilan", "menu",
            "promo", "paket", "teh", "apa", "apa aja", "apa saja", "yang", "non kopi", "coffee", "food"}


def _clean_nlu(raw: dict) -> dict:
    intent = raw.get("intent") if raw.get("intent") in INTENTS else "other"
    items = raw.get("items") if isinstance(raw.get("items"), list) else []
    return {"intent": intent, "items": [i for i in items if isinstance(i, dict) and i.get("name")],
            "target": raw.get("target") if isinstance(raw.get("target"), str) else None,
            "changes": raw.get("changes") if isinstance(raw.get("changes"), dict) else None,
            "payment": raw.get("payment") if raw.get("payment") in ("qris", "card", "cash") else None,
            "category": raw.get("category") if raw.get("category") in ("coffee", "non-coffee", "food") else None}


def _context_for_llm(state: KioskState) -> str:
    cart = state.get("cart") or []
    ctx = [f"Kiosk stage: {state.get('stage', 'ordering')}",
           "Current order: " + (", ".join(describe_line(l) for l in cart) if cart else "empty")]
    if state.get("pending_offer"):
        ctx.append(f"The kiosk just offered: {state['pending_offer']['pitch']}")
    hist = state.get("history") or []
    if hist:
        ctx.append("Last kiosk message: " + hist[-1].get("kiosk", ""))
    return "\n".join(ctx)


# ---------------------------------------------------------------- nodes
def understand(state: KioskState) -> dict:
    t0 = time.perf_counter()
    text = (state.get("text") or "").strip()
    nlu = _rule_nlu(text, state)
    source = "rules"
    if nlu is not None:
        nlu = _clean_nlu(nlu)
    else:
        try:
            msg = NLU_LLM.invoke([SystemMessage(NLU_SYSTEM),
                                  HumanMessage(f"{_context_for_llm(state)}\n\nCustomer: {text}")])
            nlu = _clean_nlu(json.loads(msg.content))
            source = config.OLLAMA_MODEL
            spotted = set(find_items_in_text(text))
            # guard against invented products (small models echo names from the context, e.g. the
            # best-seller line): an item the customer never said is re-pointed at a product they did say,
            # keeping the parsed options; leftovers are dropped
            if spotted and nlu["intent"] == "add_items":
                said = [match_item(str(i["name"])) for i in nlu["items"]]
                unused = [s for s in find_items_in_text(text) if s not in said]
                fixed = []
                low = " " + re.sub(r"[^a-z0-9 ]+", " ", text.lower()) + " "
                for item, iid in zip(nlu["items"], said):
                    name = re.sub(r"[^a-z0-9 ]+", " ", str(item["name"]).lower()).strip()
                    if iid in spotted or (iid and name and f" {name} " in low):
                        # exact alias, or a misheard spelling ("banana breat") the customer really said
                        fixed.append(item)
                    elif unused:
                        fixed.append({**item, "name": unused.pop(0)})
                nlu["items"] = fixed + [{"name": s, "qty": 1} for s in unused]
            if nlu["intent"] == "add_items":
                nlu["items"] = [_drop_unsaid_options(i, text) for i in nlu["items"]]
                _fill_options_from_text(nlu["items"], text)
            # "yang seger buat siang-siang?", "aku laper" describe a need, not a menu section
            if nlu["intent"] in ("browse_menu", "other", "greeting") and _RECO.search(text) \
                    and not find_items_in_text(text):
                nlu["intent"] = "recommendation"
            # yes/no to an offer only counts if the customer actually said yes/no
            if nlu["intent"] in ("accept_offer", "decline_offer") and not (_YES.search(text) or _NO.search(text)):
                nlu["intent"] = "recommendation" if _QUESTION.search(text) else "other"
            # the model said "other" but the customer clearly named products -> treat as an order
            if nlu["intent"] in ("other", "greeting") and spotted and not _QUESTION.search(text):
                nlu = _clean_nlu(_fallback_nlu(text))
                source += "+rules"
        except Exception as exc:  # LLM down / timeout / bad JSON
            log.warning("NLU LLM failed (%s); using keyword fallback", exc)
            nlu = _clean_nlu(_fallback_nlu(text))
            source = "fallback"
    return {"nlu": nlu, "nlu_source": source, "events": [], "suggestions": [],
            "timings": {"understand_ms": round((time.perf_counter() - t0) * 1000)}}


_OPT_ALIAS = {"big": "large", "l": "large", "besar": "large", "gede": "large", "medium": "regular",
              "small": "regular", "kecil": "regular", "sedang": "regular", "reguler": "regular",
              "ice": "iced", "es": "iced", "dingin": "iced", "cold": "iced", "warm": "hot", "panas": "hot",
              "hangat": "hot", "no": "none", "tanpa gula": "none", "less sugar": "less", "kurang manis": "less",
              "sedikit": "less", "no sugar": "none", "susu oat": "oat", "susu almond": "almond"}


def _norm_opt(v: Any, allowed: tuple) -> str | None:
    if not isinstance(v, str):
        return None
    v = _OPT_ALIAS.get(v.strip().lower(), v.strip().lower())
    return v if v in allowed else None


def _addons(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [a for a in (match_addon(str(x)) for x in raw) if a]


def _find_line(cart: list[dict], target: str | None, last_line_id: str | None) -> dict | None:
    if target:
        iid = match_item(target)
        hits = [l for l in cart if l["item_id"] == iid]
        return hits[-1] if hits else None
    return next((l for l in cart if l["line_id"] == last_line_id), cart[-1] if cart else None)


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def cart_ops(state: KioskState) -> dict:
    nlu = state["nlu"]
    intent = nlu["intent"]
    cart = [dict(l) for l in (state.get("cart") or [])]
    events: list[str] = []
    last = state.get("last_line_id")
    pending = state.get("pending_offer")
    stage, order = state.get("stage", "ordering"), state.get("order")
    if stage == "done":  # previous order was placed: anything new starts a fresh order
        cart, stage, order = [], "ordering", None
    elif stage == "paying":  # changing the order while a payment is pending voids that payment
        if order:
            orders.cancel_order(order["id"])
        stage, order = "ordering", None
    elif stage == "confirming":
        stage = "ordering"

    if intent == "accept_offer" and pending:
        line, _ = build_line(pending["add_item_id"])
        cart.append(line)
        last = line["line_id"]
        events.append(f"ADDED {describe_line(line)} untuk {pending['combo_name']}")
        pending = None
    elif intent == "decline_offer":
        events.append("DECLINED_OFFER")
        pending = None
    elif intent == "add_items":
        unknown = []
        for it in nlu["items"]:
            iid = match_item(str(it.get("name", "")))
            if not iid:
                unknown.append(str(it.get("name")))
                continue
            line, notes = build_line(
                iid, qty=_int(it.get("qty") or it.get("quantity")) or 1,
                size=_norm_opt(it.get("size"), ("regular", "large")),
                temperature=_norm_opt(it.get("temp") or it.get("temperature"), ("hot", "iced")),
                milk=_norm_opt(it.get("milk"), ("regular", "oat", "almond")),
                addons=_addons(it.get("addons")),
                sugar=_norm_opt(it.get("sugar"), ("normal", "less", "none")))
            same = next((l for l in cart if all(l.get(k) == line.get(k) for k in
                                                ("item_id", "size", "temperature", "milk", "addons", "sugar"))), None)
            if same:  # merge identical lines instead of duplicating them
                same["qty"] = min(same["qty"] + line["qty"], 20)
                price_line(same)
                last = same["line_id"]
            else:
                cart.append(line)
                last = line["line_id"]
            events.append(f"ADDED {describe_line(line)}")
            events += [f"NOTE {n}" for n in notes]
        if unknown:
            events.append(f"NOT_ON_MENU {', '.join(unknown)}")
        if not nlu["items"]:
            events.append("NOTHING_UNDERSTOOD")
        pending = None
    elif intent == "remove_items":
        target = nlu.get("target") or (str(nlu["items"][0].get("name")) if nlu.get("items") else None)
        line = _find_line(cart, target, None) if target else None
        if line:
            qty = _int((nlu.get("changes") or {}).get("qty"))
            if qty and 0 < qty < line["qty"]:
                line["qty"] -= qty
                price_line(line)
                events.append(f"REMOVED {qty}x {line['name']}")
            else:
                cart.remove(line)
                events.append(f"REMOVED {describe_line(line)}")
        else:
            events.append(f"NOT_IN_CART {target or 'item itu'}")
    elif intent == "modify_item":
        line = _find_line(cart, nlu.get("target"), last)
        ch = nlu.get("changes") or {}
        named = [i for i in find_items_in_text(state.get("text", "")) if MENU_BY_ID[i]["kind"] == "drink"
                 or MENU_BY_ID[i]["kind"] == "food"]
        if named and not any(l["item_id"] in named for l in cart):
            # the customer named a product that isn't in the order: don't silently change another line
            events.append(f"NOT_IN_CART {MENU_BY_ID[named[0]]['name']}")
        elif not line:
            events.append(f"NOT_IN_CART {nlu.get('target') or 'item itu'}")
        else:
            item = MENU_BY_ID[line["item_id"]]
            if (q := _int(ch.get("qty"))) and q > 0:
                line["qty"] = min(q, 20)
            if line["kind"] == "drink":
                if (s := _norm_opt(ch.get("size"), ("regular", "large"))):
                    line["size"] = s
                if (tp := _norm_opt(ch.get("temp") or ch.get("temperature"), ("hot", "iced"))):
                    if tp in item["temps"]:
                        line["temperature"] = tp
                    else:
                        events.append(f"NOTE {item['name']} hanya tersedia {LABEL[item['temps'][0]]}")
                if (m := _norm_opt(ch.get("milk"), ("regular", "oat", "almond"))):
                    if item["milk"]:
                        line["milk"] = m
                    else:
                        events.append(f"NOTE {item['name']} tidak pakai susu")
                if (adds := _addons(ch.get("addons"))):
                    line["addons"] = sorted(set(line.get("addons", [])) | set(adds))
                if (sg := _norm_opt(ch.get("sugar"), ("normal", "less", "none"))):
                    line["sugar"] = sg
            price_line(line)
            last = line["line_id"]
            events.append(f"UPDATED {describe_line(line)}")
    return {"cart": cart, "events": state.get("events", []) + events, "last_line_id": last,
            "pending_offer": pending, "stage": stage, "order": order}


def upsell(state: KioskState) -> dict:
    """Offer the closest combo, each combo at most once per session."""
    if state["nlu"]["intent"] != "add_items" or state.get("pending_offer"):
        return {}
    offer = find_upsell(state.get("cart") or [], state.get("offered") or [])
    if not offer:
        return {}
    return {"pending_offer": offer, "offered": (state.get("offered") or []) + [offer["combo_id"]]}


def checkout(state: KioskState) -> dict:
    if not state.get("cart") or state.get("stage") == "done":
        return {"events": state.get("events", []) + ["CART_EMPTY"]}
    return {"stage": "confirming", "pending_offer": None, "events": state.get("events", []) + ["CHECKOUT"]}


def payment(state: KioskState) -> dict:
    cart = state.get("cart") or []
    method = state["nlu"].get("payment")
    if not cart or state.get("stage") == "done":
        return {"events": state.get("events", []) + ["CART_EMPTY"]}
    if not method:
        return {"stage": "confirming", "events": state.get("events", []) + ["CHECKOUT"]}
    order = orders.create_order(cart, totals(cart), method)
    return {"stage": "paying", "order": order, "pending_offer": None,
            "events": state.get("events", []) + [f"PAYMENT {method}"]}


def info(state: KioskState) -> dict:
    nlu = dict(state["nlu"])
    events = list(state.get("events", []))
    m = _NO_SUCH.search(state.get("text", "").strip())
    if m and nlu["intent"] != "recommendation" and not match_item(m.group(1)) \
            and m.group(1).strip().lower() not in _GENERIC:
        # "ada pizza nggak?" -> just say no; don't list a category the model guessed
        events += [f"NOT_ON_MENU {m.group(1).strip()}", "SEE_MENU"]
        return {"events": events, "nlu": nlu}
    # "yang nggak terlalu manis apa ya?" names no product: it's a request for a recommendation,
    # even if the model filled "target" from the context
    if nlu["intent"] == "ask_item_info" and not find_items_in_text(state.get("text", "")):
        nlu["intent"] = "recommendation"
    if nlu["intent"] == "browse_menu":
        cat = nlu.get("category")
        nlu["_items"] = [x["id"] for x in MENU if not cat or x["category"] == cat]
        events.append("MENU " + (cat or "all"))
    elif nlu["intent"] == "ask_item_info":
        iid = match_item(nlu.get("target") or "") or next(iter(find_items_in_text(state.get("text", ""))), None)
        nlu["_item"] = iid
        events.append(f"INFO {iid}" if iid else "INFO_UNKNOWN")
    else:
        events.append("RECOMMEND")
    return {"events": events, "nlu": nlu}


def cancel(state: KioskState) -> dict:
    had = bool(state.get("cart"))
    order = state.get("order")
    if order and state.get("stage") == "paying":
        orders.cancel_order(order["id"])
    return {"cart": [], "stage": "ordering", "pending_offer": None, "order": None, "last_line_id": None,
            "events": state.get("events", []) + (["CANCELLED"] if had else ["CART_EMPTY"])}


# ---------------------------------------------------------------- reply
def _free_reply(state: KioskState, task: str) -> str:
    """Phi-4-mini writes a short, grounded Indonesian reply. Falls back to a canned line."""
    sys = ("Kamu adalah Kopi, suara ramah dari kios self-service sebuah kedai kopi di Indonesia. "
           "Selalu jawab dalam Bahasa Indonesia yang santai dan sopan (panggil pelanggan 'Kak'), "
           "1-3 kalimat pendek seperti diucapkan, tanpa daftar, tanpa emoji, tanpa markdown. "
           "Hanya sebut produk dan harga dari menu ini, jangan mengarang:\n" + menu_for_prompt())
    try:
        out = CHAT_LLM.invoke([SystemMessage(sys), HumanMessage(
            f"{_context_for_llm(state)}\nPelanggan bilang: {state.get('text', '')}\nTugas: {task}")])
        txt = re.sub(r"[*#_`]", "", out.content).strip()
        return txt or "Aku bisa bantu pesan minuman dan kue. Mau pesan apa, Kak?"
    except Exception as exc:
        log.warning("reply LLM failed: %s", exc)
        return "Maaf Kak, aku kurang tangkap. Kakak bisa sebut minuman atau kue, atau bilang 'minta rekomendasi'."


_REC_SYSTEM = """You recommend products at an Indonesian coffee shop kiosk. The customer writes in Indonesian.
Pick 1 or 2 products from this menu that best fit what the customer asked for (taste, sweetness, hot/cold,
hunger, time of day). Return ONLY JSON with the 1 or 2 menu NUMBERS you pick: {"picks": [<number>, <number>]}
Menu:
""" + "\n".join(f"{n}. {m['name']} ({m['category']}): {m['desc']}" for n, m in enumerate(MENU, 1)) + """
Hints: not sweet = Espresso, Americano, Cold Brew, Lemon Tea, Cappuccino. Sweet = Caramel Macchiato, Mocha,
Kopi Susu Gula Aren, Signature Chocolate, Cinnamon Roll, Chocolate Muffin. Refreshing for a hot day = Cold Brew,
Lemon Tea, Americano. Filling when hungry = Chicken Pesto Sandwich, Banana Bread.
Example: {"picks": [8, 11]}"""


def _recommend(state: KioskState) -> tuple[str, list[str]]:
    """The model only picks menu ids (validated). Names, prices and descriptions in the sentence come from
    the menu, because Phi-4-mini's free Indonesian text is clumsy and can contradict the request."""
    ids: list[str] = []
    if re.search(r"\b(lapar|laper|kenyang|makan|hungry)\b", state.get("text", ""), re.I):
        ids = ["chicken_sandwich", "banana_bread"]  # obvious need: no model call
    try:
        if ids:
            raise StopIteration
        out = NLU_LLM.invoke([SystemMessage(_REC_SYSTEM),
                              HumanMessage(f"{_context_for_llm(state)}\nCustomer: {state.get('text', '')}")])
        data = json.loads(out.content)
        picks = data.get("picks") or data.get("ids") or []
        if isinstance(picks, list) and 0 < len(picks) <= 3:  # a runaway list means the model got confused
            for p in picks:
                if isinstance(p, int) and 1 <= p <= len(MENU):
                    ids.append(MENU[p - 1]["id"])
                elif isinstance(p, str) and (iid := match_item(p)):
                    ids.append(iid)
        ids = list(dict.fromkeys(ids))[:2]
    except StopIteration:
        pass
    except Exception as exc:
        log.warning("recommend LLM failed: %s", exc)
    if not ids:
        ids = ["kopi_susu_aren", "matcha_latte"]
    first, *rest = [MENU_BY_ID[i] for i in ids]
    text = f"Aku rekomendasikan {first['name']} ({money(first['price'])}), {first['desc'][0].lower()}{first['desc'][1:]}"
    if rest:
        r = rest[0]
        text += f" Atau {r['name']} ({money(r['price'])}), {r['desc'][0].lower()}{r['desc'][1:]}"
    return text + " Mau coba yang mana, Kak?", ids


def respond(state: KioskState) -> dict:
    t0 = time.perf_counter()
    nlu, events = state["nlu"], state.get("events", [])
    intent = nlu["intent"]
    cart = state.get("cart") or []
    t = totals(cart)
    parts: list[str] = []
    sugg: list[str] = []

    added = [e[6:] for e in events if e.startswith("ADDED ")]
    if added:
        parts.append(random.choice(["Siap Kak,", "Oke Kak,", "Baik Kak,", "Pilihan mantap,"]) + " "
                     + "; ".join(added) + " sudah masuk pesanan.")
    for e in events:
        if e.startswith("NOTE "):
            parts.append(e[5:] + ".")
        elif e.startswith("NOT_ON_MENU "):
            parts.append(f"Maaf Kak, {e[12:]} belum ada di menu kami.")
        elif e.startswith("REMOVED "):
            parts.append(f"{e[8:]} sudah dihapus dari pesanan.")
        elif e.startswith("UPDATED "):
            parts.append(f"Sudah diubah jadi {e[8:]}.")
        elif e.startswith("NOT_IN_CART "):
            parts.append(f"Hmm, {e[12:]} nggak ada di pesanan Kakak.")
        elif e == "NOTHING_UNDERSTOOD":
            parts.append("Mau pesan yang mana, Kak? Bisa juga langsung ketuk di menu.")
        elif e == "SEE_MENU":
            parts.append("Coba lihat menu di layar ya, mungkin ada yang Kakak suka.")
        elif e == "DECLINED_OFFER":
            parts.append("Oke, nggak apa-apa Kak.")
        elif e == "CART_EMPTY":
            parts.append("Pesanannya masih kosong, Kak. Mau pesan apa?")
        elif e == "CANCELLED":
            parts.append("Pesanan sudah dibatalkan. Kita mulai lagi ya, mau pesan apa, Kak?")

    if intent == "greeting":
        if cart:
            parts.append(f"Halo lagi, Kak! Pesanan Kakak ada {t['item_count']} item, total {money(t['total'])}.")
        else:
            parts.append("Halo Kak, selamat datang! Aku Kopi. Mau pesan apa hari ini? "
                         "Kopi Susu Gula Aren kami paling laris lho.")
            sugg = ["Minta rekomendasi", "Es latte besar", "Kuenya ada apa aja?"]

    if "CHECKOUT" in events:
        lines = "; ".join(describe_line(l) for l in cart)
        combo_txt = (", sudah termasuk potongan " + " dan ".join(c["name"] for c in t["combos"])) if t["combos"] else ""
        parts.append(f"Pesanan Kakak: {lines}{combo_txt}. Totalnya {money(t['total'])}. "
                     "Mau bayar pakai QRIS, kartu, atau tunai?")
        sugg = ["QRIS", "Kartu", "Tunai", "Tambah pesanan"]
    if any(e.startswith("PAYMENT ") for e in events):
        o = state["order"]
        if o["method"] == "qris":
            parts.append(f"Silakan scan kode QRIS di layar untuk bayar {money(o['total'])} ya, Kak.")
        elif o["method"] == "card":
            parts.append(f"Silakan tempel atau masukkan kartu Kakak ke mesin. Totalnya {money(o['total'])}.")
        else:
            parts.append(f"Silakan bayar {money(o['total'])} di kasir dan sebutkan nomor pesanan {o['number']}.")

    if any(e.startswith("MENU ") for e in events):
        ids = nlu.get("_items") or []
        names = ", ".join(f"{MENU_BY_ID[i]['name']} {money(MENU_BY_ID[i]['price'])}" for i in ids[:6])
        cat = CATEGORY_ID.get(nlu.get("category") or "", "")
        parts.append(f"Untuk {cat} ada {names}." if cat else f"Kami punya {names}.")
        if len(ids) > 6:
            parts.append("Selengkapnya bisa dilihat di layar.")
    if nlu.get("_item"):
        m = MENU_BY_ID[nlu["_item"]]
        parts.append(f"{m['name']}: {m['desc']} Harganya {money(m['price'])}."
                     + (" Ada versi panas dan dingin." if len(m.get("temps", [])) > 1 else "")
                     + " Mau pesan satu, Kak?")
        sugg = [f"Satu {m['name']}", "Rekomendasi lain"]
    if "INFO_UNKNOWN" in events:
        parts.append(_free_reply(state, "Jawab pertanyaan pelanggan tentang menu."))
    if "RECOMMEND" in events:
        rec_text, rec_ids = _recommend(state)
        parts.append(rec_text)
        if rec_ids:
            sugg = [f"Satu {MENU_BY_ID[i]['name']}" for i in rec_ids]
    if intent == "other" and not parts and state.get("pending_offer"):
        # unclear answer to a combo offer (often a mis-heard "iya"/"nggak"): ask again, don't let the LLM improvise
        parts.append(f"Maaf Kak, aku kurang tangkap. {state['pending_offer']['pitch']}? Jawab iya atau nggak ya.")
        sugg = ["Iya, boleh", "Nggak, makasih"]
    elif intent == "other" and not parts:
        parts.append(_free_reply(state, "Tanggapi dengan ramah. Kalau tidak berhubungan dengan pesanan, "
                                        "arahkan kembali ke menu dengan sopan."))

    if intent == "view_cart":
        parts.append(f"Pesanan Kakak: {cart_summary(cart)}".replace("\n", " ") if cart
                     else "Pesanannya masih kosong, Kak.")

    offer = state.get("pending_offer")
    if offer and intent == "add_items":
        parts.append(offer["pitch"] + ", Kak?")
        sugg = ["Iya, boleh", "Nggak, makasih"]
    elif (added or intent in ("decline_offer", "remove_items", "modify_item")) and cart \
            and state.get("stage") == "ordering":
        parts.append(f"Totalnya sekarang {money(t['total'])}. Ada lagi, Kak?")

    if not sugg:
        stage = state.get("stage")
        if stage == "confirming":
            sugg = ["QRIS", "Kartu", "Tunai"]
        elif stage == "paying":
            sugg = []
        elif cart:
            sugg = ["Sudah, itu aja", "Dibikin besar", "Lihat pesanan"]
        else:
            sugg = ["Minta rekomendasi", "Lihat menu", "Es kopi susu"]

    reply = " ".join(p.strip() for p in parts if p.strip()) or "Mau pesan apa, Kak?"
    hist = (state.get("history") or [])[-20:] + [{"customer": state.get("text", ""), "kiosk": reply}]
    timings = dict(state.get("timings") or {})
    timings["respond_ms"] = round((time.perf_counter() - t0) * 1000)
    return {"reply": reply, "suggestions": sugg, "history": hist, "timings": timings}


# ---------------------------------------------------------------- graph
def route(state: KioskState) -> str:
    intent = state["nlu"]["intent"]
    if intent in ("add_items", "remove_items", "modify_item", "accept_offer", "decline_offer"):
        return "cart_ops"
    if intent == "checkout":
        return "checkout"
    if intent == "choose_payment":
        return "payment"
    if intent in ("browse_menu", "ask_item_info", "recommendation"):
        return "info"
    if intent == "cancel_order":
        return "cancel"
    return "respond"


def build_graph():
    g = StateGraph(KioskState)
    for name, fn in [("understand", understand), ("cart_ops", cart_ops), ("upsell", upsell),
                     ("checkout", checkout), ("payment", payment), ("info", info), ("cancel", cancel),
                     ("respond", respond)]:
        g.add_node(name, fn)
    g.add_edge(START, "understand")
    g.add_conditional_edges("understand", route,
                            ["cart_ops", "checkout", "payment", "info", "cancel", "respond"])
    g.add_edge("cart_ops", "upsell")
    for n in ("upsell", "checkout", "payment", "info", "cancel"):
        g.add_edge(n, "respond")
    g.add_edge("respond", END)
    return g.compile(checkpointer=MemorySaver())


GRAPH = build_graph()
NEW_SESSION: dict = {"cart": [], "stage": "ordering", "pending_offer": None, "offered": [],
                     "last_line_id": None, "order": None, "history": []}


def _cfg(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def new_session() -> str:
    sid = uuid.uuid4().hex
    GRAPH.update_state(_cfg(sid), dict(NEW_SESSION), as_node="respond")
    return sid


def get_state(session_id: str) -> dict:
    snap = GRAPH.get_state(_cfg(session_id))
    if not snap.values:
        raise KeyError(session_id)
    return snap.values


def chat(session_id: str, text: str) -> dict:
    get_state(session_id)
    return GRAPH.invoke({"text": text}, _cfg(session_id))


def patch_state(session_id: str, values: dict) -> dict:
    """Direct UI actions (tap-to-add, +/-, payment confirmation) write through the same checkpoint."""
    GRAPH.update_state(_cfg(session_id), values, as_node="respond")
    return get_state(session_id)


def warm_up() -> None:
    try:
        NLU_LLM.invoke([HumanMessage('Return {"ok": true}')])
        log.info("Ollama model %s is loaded", config.OLLAMA_MODEL)
    except Exception as exc:
        log.warning("Ollama warm-up failed: %s", exc)
