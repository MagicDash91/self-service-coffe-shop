"""Order book: simulated payments and the barista queue, persisted to data/orders.json."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from . import config

_FILE = config.DATA_DIR / "orders.json"
_LOCK = threading.RLock()
_ORDERS: list[dict] = json.loads(_FILE.read_text(encoding="utf-8")) if _FILE.exists() else []


def _save() -> None:
    _FILE.write_text(json.dumps(_ORDERS[-500:], indent=1), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _next_number() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    n = sum(1 for o in _ORDERS if o["created_at_local"].startswith(today)) + 1
    return f"A{n:03d}"


def create_order(cart: list[dict], totals: dict, method: str) -> dict:
    """QRIS / card wait for payment; cash is queued straight away and paid at the counter."""
    with _LOCK:
        order = {
            "id": uuid.uuid4().hex[:12], "number": _next_number(), "method": method,
            "status": "pay_at_counter" if method == "cash" else "awaiting_payment",
            "items": [{k: l.get(k) for k in ("name", "qty", "size", "temperature", "milk", "addons", "sugar",
                                             "unit_price", "line_total")} for l in cart],
            "subtotal": totals["subtotal"], "discount": totals["discount"], "total": totals["total"],
            "combos": [c["name"] for c in totals["combos"]],
            "created_at": _now(), "created_at_local": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _ORDERS.append(order)
        _save()
        return order


def get_order(order_id: str) -> dict | None:
    return next((o for o in _ORDERS if o["id"] == order_id), None)


def set_status(order_id: str, status: str) -> dict | None:
    with _LOCK:
        o = get_order(order_id)
        if o:
            o["status"] = status
            o[f"{status}_at"] = _now()
            _save()
        return o


def mark_paid(order_id: str) -> dict | None:
    return set_status(order_id, "preparing")


def cancel_order(order_id: str) -> dict | None:
    o = get_order(order_id)
    if o and o["status"] in ("awaiting_payment", "pay_at_counter"):
        return set_status(order_id, "cancelled")
    return o


def queue() -> list[dict]:
    """Orders the baristas should see."""
    return [o for o in _ORDERS if o["status"] in ("preparing", "pay_at_counter", "ready")][-30:]
