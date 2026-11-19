"""
FastAPI app for the self-service coffee kiosk.

Run:  .venv\\Scripts\\python -m uvicorn app.main:app --port 8020
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import agent, config, device, orders, speech
from .cart import build_line, describe_line, find_upsell, price_line, totals
from .menu import MENU_BY_ID, public_menu

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("kiosk")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # load the LLM and speech models in the background so the first customer doesn't wait
    threading.Thread(target=agent.warm_up, daemon=True).start()
    threading.Thread(target=speech.preload, daemon=True).start()
    yield


app = FastAPI(title="Self-Service Coffee Kiosk", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"],
                   allow_headers=["*"], expose_headers=["X-Status", "X-Transcript", "X-Reply", "X-Stage",
                                                        "X-Total", "X-Order-Number", "X-Items"])
app.include_router(device.router)  # ESP32 voice units: /api/device/...


# ---------------------------------------------------------------- helpers
def _view(state: dict, extra: dict | None = None) -> dict:
    """What the UI needs after every turn or action."""
    cart = state.get("cart") or []
    order = state.get("order")
    if order:
        order = orders.get_order(order["id"]) or order
    view = {
        "cart": [{**l, "label": describe_line(l)} for l in cart],
        "totals": totals(cart),
        "stage": state.get("stage", "ordering"),
        "pending_offer": state.get("pending_offer"),
        "order": order,
    }
    if extra:
        view.update(extra)
    return view


def _state_or_404(session_id: str) -> dict:
    try:
        return agent.get_state(session_id)
    except KeyError:
        raise HTTPException(404, "Sesi tidak ditemukan. Mulai pesanan baru.")


def _turn(session_id: str, text: str) -> dict:
    """One conversational turn through the LangGraph agent."""
    _state_or_404(session_id)
    state = agent.chat(session_id, text)
    return _view(state, {"reply": state["reply"], "suggestions": state.get("suggestions", []),
                         "nlu": {k: v for k, v in state["nlu"].items() if not k.startswith("_")},
                         "nlu_source": state.get("nlu_source"), "timings": state.get("timings", {})})


# ---------------------------------------------------------------- models
class ChatIn(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=500)


class AddIn(BaseModel):
    session_id: str
    item_id: str
    qty: int = Field(1, ge=1, le=20)
    size: str | None = None
    temperature: str | None = None
    milk: str | None = None
    addons: list[str] = []
    sugar: str | None = None


class LineIn(BaseModel):
    session_id: str
    line_id: str
    delta: int = Field(ge=-20, le=20)


class SessionIn(BaseModel):
    session_id: str


class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=1500)


# ---------------------------------------------------------------- routes
@app.get("/api/health")
def health():
    return {"ok": True, "llm": config.OLLAMA_MODEL, "stt": f"faster-whisper/{config.WHISPER_MODEL}",
            "tts": f"piper/{config.PIPER_VOICE}" if config.TTS_ENGINE == "piper" else config.TTS_ENGINE}


@app.get("/api/menu")
def menu():
    return public_menu()


@app.post("/api/session")
def new_session():
    sid = agent.new_session()
    return {"session_id": sid, **_view(agent.get_state(sid))}


@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    return _view(_state_or_404(session_id))


@app.post("/api/chat")
async def chat(body: ChatIn):
    return await run_in_threadpool(_turn, body.session_id, body.text.strip())


@app.post("/api/cart/add")
def cart_add(body: AddIn):
    """Tap-to-order from the menu grid. Writes through the same LangGraph checkpoint as voice orders."""
    state = _state_or_404(body.session_id)
    if body.item_id not in MENU_BY_ID:
        raise HTTPException(400, "Unknown item")
    stage = state.get("stage", "ordering")
    cart = [] if stage == "done" else [dict(l) for l in state.get("cart") or []]
    if stage == "paying" and state.get("order"):
        orders.cancel_order(state["order"]["id"])
    line, notes = build_line(body.item_id, body.qty, body.size, body.temperature, body.milk, body.addons, body.sugar)
    cart.append(line)
    pending = state.get("pending_offer") if stage != "done" else None
    offered = list(state.get("offered") or [])
    new_offer = None
    if not pending:
        new_offer = find_upsell(cart, offered)
        if new_offer:
            offered.append(new_offer["combo_id"])
    new = agent.patch_state(body.session_id, {
        "cart": cart, "stage": "ordering", "order": None, "last_line_id": line["line_id"],
        "pending_offer": pending or new_offer, "offered": offered})
    reply = f"Siap Kak, {describe_line(line)} sudah masuk pesanan." + (" " + ". ".join(notes) + "." if notes else "")
    if new_offer:
        reply += f" {new_offer['pitch']}, Kak?"
    return _view(new, {"reply": reply})


@app.post("/api/cart/line")
def cart_line(body: LineIn):
    """+ / - buttons on a cart line."""
    state = _state_or_404(body.session_id)
    if state.get("stage") in ("paying", "done"):
        raise HTTPException(409, "Pesanan sudah masuk tahap pembayaran")
    cart = [dict(l) for l in state.get("cart") or []]
    line = next((l for l in cart if l["line_id"] == body.line_id), None)
    if not line:
        raise HTTPException(404, "Line not found")
    line["qty"] += body.delta
    if line["qty"] <= 0:
        cart.remove(line)
    else:
        line["qty"] = min(line["qty"], 20)
        price_line(line)
    return _view(agent.patch_state(body.session_id, {"cart": cart, "stage": "ordering"}))


@app.post("/api/offer/{decision}")
def offer(decision: str, body: SessionIn):
    """Yes/No buttons on the combo offer card — handled by the agent like a spoken yes/no."""
    if decision not in ("accept", "decline"):
        raise HTTPException(400, "decision must be accept or decline")
    return _turn(body.session_id, "iya, boleh" if decision == "accept" else "nggak, makasih")


@app.post("/api/checkout")
def checkout(body: SessionIn):
    return _turn(body.session_id, "sudah itu aja")


@app.post("/api/pay/confirm")
def pay_confirm(body: SessionIn):
    """Simulated payment gateway callback (QRIS scanned / card approved / cash acknowledged)."""
    state = _state_or_404(body.session_id)
    order = state.get("order")
    if not order or state.get("stage") != "paying":
        raise HTTPException(409, "Tidak ada pesanan yang menunggu pembayaran")
    if order["method"] != "cash":
        orders.mark_paid(order["id"])
    order = orders.get_order(order["id"])
    reply = (f"Pembayaran berhasil, terima kasih Kak! Nomor pesanan Kakak {order['number']}. "
             "Nanti kami panggil kalau sudah siap ya." if order["method"] != "cash"
             else f"Terima kasih Kak! Pesanan {order['number']} sudah masuk antrean. Silakan bayar di kasir ya.")
    new = agent.patch_state(body.session_id, {"stage": "done", "order": order, "pending_offer": None})
    return _view(new, {"reply": reply})


@app.post("/api/pay/{method}")
def pay(method: str, body: SessionIn):
    if method not in ("qris", "card", "cash"):
        raise HTTPException(400, "method must be qris, card or cash")
    return _turn(body.session_id, {"qris": "bayar pakai qris", "card": "bayar pakai kartu", "cash": "bayar tunai"}[method])


@app.get("/api/orders/queue")
def order_queue():
    return {"orders": orders.queue()}


@app.post("/api/orders/{order_id}/{status}")
def order_status(order_id: str, status: str):
    if status not in ("preparing", "ready", "collected"):
        raise HTTPException(400, "status must be preparing, ready or collected")
    o = orders.set_status(order_id, status)
    if not o:
        raise HTTPException(404, "Order not found")
    return o


@app.post("/api/stt")
async def stt(audio: UploadFile = File(...)):
    data = await audio.read()
    if len(data) < 800:
        raise HTTPException(400, "Rekaman terlalu pendek")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Rekaman terlalu panjang")
    try:
        return await run_in_threadpool(speech.transcribe, data)
    except Exception as exc:
        log.exception("STT failed")
        raise HTTPException(500, f"Pengenalan suara gagal: {exc}")


@app.post("/api/tts")
async def tts(body: TTSIn):
    try:
        audio, media = await run_in_threadpool(speech.synthesize, body.text)
    except Exception as exc:
        log.exception("TTS failed")
        raise HTTPException(500, f"Suara gagal dibuat: {exc}")
    return Response(audio, media_type=media, headers={"Cache-Control": "no-store"})
