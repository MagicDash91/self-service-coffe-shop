"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Assistant } from "@/components/Assistant";
import { CustomizeSheet, type Opts } from "@/components/CustomizeSheet";
import { MenuGrid } from "@/components/MenuGrid";
import { OrderPanel } from "@/components/OrderPanel";
import { api } from "@/lib/api";
import type { KioskView, Menu, MenuItem, Msg } from "@/lib/types";
import { usePlayer, useRecorder } from "@/lib/useVoice";

const GREETING = "Halo Kak, selamat datang! Aku Kopi. Ketuk menu, atau tekan tombol mikrofon lalu sebutkan pesanan Kakak.";
const EMPTY: KioskView = { cart: [], totals: { subtotal: 0, discount: 0, total: 0, item_count: 0, combos: [] },
  stage: "ordering", pending_offer: null, order: null };

export default function Kiosk() {
  const [menu, setMenu] = useState<Menu | null>(null);
  const [sid, setSid] = useState<string>("");
  const [view, setView] = useState<KioskView>(EMPTY);
  const [messages, setMessages] = useState<Msg[]>([{ role: "kiosk", text: GREETING }]);
  const [suggestions, setSuggestions] = useState<string[]>(["Minta rekomendasi", "Es latte besar", "Kuenya ada apa aja?"]);
  const [understood, setUnderstood] = useState<{ intent?: string; source?: string; ms?: number } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string>("");
  const [picked, setPicked] = useState<MenuItem | null>(null);
  const [voiceOn, setVoiceOn] = useState(true);
  const [models, setModels] = useState<{ llm: string; stt: string; tts: string } | null>(null);
  const player = usePlayer();
  const voiceRef = useRef(voiceOn);
  voiceRef.current = voiceOn;

  const start = useCallback(async () => {
    try {
      const s = await api.newSession();
      setSid(s.session_id);
      setView(s);
      setMessages([{ role: "kiosk", text: GREETING }]);
      setUnderstood(null);
      setSuggestions(["Minta rekomendasi", "Es latte besar", "Kuenya ada apa aja?"]);
      setError("");
    } catch (e) { setError((e as Error).message); }
  }, []);

  useEffect(() => {
    api.menu().then(setMenu).catch((e) => setError(e.message));
    api.health().then(setModels).catch(() => {});
    start();
  }, [start]);

  const speak = useCallback(async (text: string) => {
    if (!voiceRef.current || !text) return;
    try { player.play(await api.tts(text)); } catch { /* voice is optional */ }
  }, [player]);

  const apply = useCallback((v: KioskView) => {
    setView(v);
    if (v.reply) {
      const ms = v.timings ? (v.timings.understand_ms || 0) + (v.timings.respond_ms || 0) : undefined;
      setMessages((m) => [...m, { role: "kiosk", text: v.reply! }]);
      speak(v.reply);
      if (v.nlu) setUnderstood({ intent: String(v.nlu.intent), source: v.nlu_source, ms });
    }
    if (v.suggestions) setSuggestions(v.suggestions);
  }, [speak]);

  const run = useCallback(async (label: string, fn: () => Promise<KioskView>) => {
    setBusy(label);
    setError("");
    try { apply(await fn()); } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }, [apply]);

  const send = useCallback((text: string, voice = false) => {
    if (!sid) return;
    player.cancel();
    setMessages((m) => [...m, { role: "customer", text, voice }]);
    run("thinking", () => api.chat(sid, text));
  }, [sid, run, player]);

  const onAudio = useCallback(async (blob: Blob) => {
    setBusy("transcribing");
    try {
      const r = await api.stt(blob);
      setBusy(null);
      if (!r.text) {
        setMessages((m) => [...m, { role: "kiosk", text: "Maaf Kak, suaranya kurang jelas. Bisa diulang?" }]);
        return;
      }
      send(r.text, true);
    } catch (e) { setError((e as Error).message); setBusy(null); }
  }, [send]);

  const rec = useRecorder(onAudio);
  const onMic = async () => {
    if (rec.recording) { rec.stop(); return; }
    player.cancel();
    try { await rec.start(); } catch { setError("Mikrofon diblokir. Izinkan akses mikrofon di browser, atau ketik saja pesanannya."); }
  };

  const addItem = (item: MenuItem, o?: Opts) => {
    setPicked(null);
    setMessages((m) => [...m, { role: "customer", text: `Pilih: ${item.name}${o && o.qty > 1 ? ` ×${o.qty}` : ""}` }]);
    run("thinking", () => api.add(sid, { item_id: item.id, ...(o || {}) }));
  };

  return (
    <div className="flex min-h-screen flex-col lg:h-screen">
      <header className="flex items-center justify-between gap-4 px-6 py-4">
        <div className="flex items-baseline gap-3">
          <h1 className="font-display text-3xl text-bean">Kopi&nbsp;Pagi</h1>
          <span className="hidden text-sm text-roast/60 sm:inline">Pesan mandiri</span>
        </div>
        <div className="flex items-center gap-2">
          {models && (
            <span className="hidden rounded-full bg-white/70 px-3 py-1 font-mono text-[11px] text-roast/70 md:inline">
              {models.llm} · {models.stt} · {models.tts}
            </span>
          )}
          <Link href="/barista" className="rounded-full px-3 py-1.5 text-sm text-roast hover:bg-white/70">Layar barista</Link>
          <button onClick={start} className="rounded-full bg-white px-4 py-1.5 text-sm font-medium text-bean hover:bg-crema">
            Pesanan baru
          </button>
        </div>
      </header>

      {error && (
        <div role="alert" className="mx-6 mb-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-800">
          {error}
        </div>
      )}

      <main className="grid min-h-0 flex-1 gap-4 px-6 pb-6 lg:grid-cols-[minmax(0,1fr)_minmax(340px,420px)_minmax(300px,360px)]">
        {menu ? <MenuGrid menu={menu} onPick={(it) => (it.kind === "drink" ? setPicked(it) : addItem(it))} />
          : <div className="grid place-items-center text-roast/50">Memuat menu…</div>}
        <div className="flex min-h-[520px] flex-col lg:min-h-0 [&>section]:flex-1">
          <Assistant messages={messages} suggestions={suggestions} busy={rec.recording ? "listening" : busy}
            recording={rec.recording} level={rec.level} speaking={player.speaking} voiceOn={voiceOn}
            understood={understood} onSend={(t) => send(t)} onMic={onMic}
            onToggleVoice={() => { setVoiceOn((v) => !v); player.cancel(); }} />
        </div>
        <div className="flex min-h-[420px] flex-col lg:min-h-0 [&>section]:flex-1">
          <OrderPanel view={view} busy={!!busy}
            onLine={(id, d) => run("thinking", () => api.line(sid, id, d))}
            onOffer={(yes) => { setMessages((m) => [...m, { role: "customer", text: yes ? "Iya, tambahkan" : "Nggak, makasih" }]);
              run("thinking", () => api.offer(sid, yes)); }}
            onCheckout={() => { setMessages((m) => [...m, { role: "customer", text: "Sudah, lanjut bayar" }]);
              run("thinking", () => api.checkout(sid)); }}
            onPay={(m) => { setMessages((x) => [...x, { role: "customer", text: `Bayar pakai ${({ qris: "QRIS", card: "kartu", cash: "tunai" } as Record<string, string>)[m]}` }]);
              run("thinking", () => api.pay(sid, m)); }}
            onConfirmPay={() => run("thinking", () => api.confirmPay(sid))}
            onNewOrder={start} />
        </div>
      </main>

      {picked && menu && (
        <CustomizeSheet item={picked} menu={menu} onClose={() => setPicked(null)} onAdd={(o) => addItem(picked, o)} />
      )}
    </div>
  );
}
