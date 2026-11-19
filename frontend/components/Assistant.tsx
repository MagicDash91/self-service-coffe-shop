"use client";
import { useEffect, useRef, useState } from "react";
import type { Msg } from "@/lib/types";

type Props = {
  messages: Msg[];
  suggestions: string[];
  busy: string | null;            // "listening" | "transcribing" | "thinking" | null
  recording: boolean;
  level: number;
  speaking: boolean;
  voiceOn: boolean;
  understood: { intent?: string; source?: string; ms?: number } | null;
  onSend: (text: string) => void;
  onMic: () => void;
  onToggleVoice: () => void;
};

export function Assistant(p: Props) {
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [p.messages, p.busy]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim() || p.busy) return;
    p.onSend(text.trim());
    setText("");
  };

  const ring = p.recording ? 1 + Math.min(p.level * 2.2, 0.9) : 1;

  return (
    <section className="flex min-h-0 flex-col rounded-3xl border border-line bg-white" aria-label="Asisten pemesanan">
      <header className="flex items-center justify-between border-b border-line px-5 py-3">
        <div className="flex items-center gap-3">
          <div className={`grid h-9 w-9 place-items-center rounded-full bg-bean font-display text-lg text-foam
            ${p.speaking ? "animate-pulse" : ""}`}>K</div>
          <div>
            <p className="font-semibold leading-tight text-bean">Kopi, asisten barista Kakak</p>
            <p className="text-xs text-roast/60">Bicara atau ketik. Contoh: "dua es latte, satu pakai susu oat".</p>
          </div>
        </div>
        <button onClick={p.onToggleVoice} aria-pressed={p.voiceOn}
          className={`shrink-0 whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-medium transition ${p.voiceOn
            ? "border-leaf/30 bg-leaf/10 text-leaf" : "border-line text-roast/60"}`}
          title="Bacakan balasan">
          {p.voiceOn ? "Suara aktif" : "Suara mati"}
        </button>
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4" aria-live="polite">
        {p.messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "customer" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed ${m.role === "customer"
              ? "rounded-br-md bg-caramel/15 text-bean" : "rounded-bl-md bg-crema text-bean"}`}>
              {m.voice && <span className="mr-1.5 text-xs text-roast/50" aria-label="lewat suara">🎙</span>}
              {m.text}
              {m.meta && <p className="mt-1.5 font-mono text-[10.5px] text-roast/45">{m.meta}</p>}
            </div>
          </div>
        ))}
        {p.busy && p.busy !== "listening" && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-2xl rounded-bl-md bg-crema px-4 py-3 text-sm text-roast/70">
              <span className="flex gap-1">
                {[0, 1, 2].map((d) => (
                  <span key={d} className="h-1.5 w-1.5 animate-bounce rounded-full bg-roast/50"
                    style={{ animationDelay: `${d * 120}ms` }} />
                ))}
              </span>
              {p.busy === "transcribing" ? "Mendengarkan…" : "Sedang berpikir…"}
            </div>
          </div>
        )}
        <div ref={end} />
      </div>

      {p.understood?.intent && (
        <div className="mx-5 mb-2 flex flex-wrap items-center gap-2 text-[11px] text-roast/60">
          <span className="font-semibold uppercase tracking-wider">Dipahami</span>
          <span className="rounded-md bg-crema px-2 py-0.5 font-mono text-roast">{p.understood.intent}</span>
          <span>lewat {p.understood.source}</span>
          {p.understood.ms !== undefined && <span>· {(p.understood.ms / 1000).toFixed(1)}s</span>}
        </div>
      )}

      {p.suggestions.length > 0 && (
        <div className="flex flex-wrap gap-2 px-5 pb-3">
          {p.suggestions.map((s) => (
            <button key={s} disabled={!!p.busy} onClick={() => p.onSend(s)}
              className="rounded-full border border-line bg-foam px-3 py-1.5 text-sm text-roast transition
                hover:border-caramel disabled:opacity-50">
              {s}
            </button>
          ))}
        </div>
      )}

      <form onSubmit={submit} className="flex items-center gap-3 border-t border-line p-4">
        <button type="button" onClick={p.onMic} disabled={!!p.busy && !p.recording}
          aria-label={p.recording ? "Berhenti merekam" : "Mulai pesan dengan suara"}
          className="relative grid h-14 w-14 shrink-0 place-items-center rounded-full disabled:opacity-50">
          <span className="absolute inset-0 rounded-full bg-caramel/30 transition-transform duration-75"
            style={{ transform: `scale(${ring})`, opacity: p.recording ? 1 : 0 }} />
          <span className={`relative grid h-14 w-14 place-items-center rounded-full text-foam transition ${p.recording
            ? "bg-red-600" : "bg-bean hover:bg-roast"}`}>
            {p.recording ? (
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor" aria-hidden><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
            ) : (
              <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" strokeLinecap="round" />
              </svg>
            )}
          </span>
        </button>
        <input value={text} onChange={(e) => setText(e.target.value)} disabled={!!p.busy}
          placeholder={p.recording ? "Mendengarkan… ketuk tombol kalau sudah selesai" : "Ketik pesanan Kakak…"}
          className="h-12 min-w-0 flex-1 rounded-xl border border-line bg-foam px-4 text-[15px] text-bean
            placeholder:text-roast/40 focus:border-caramel focus:outline-none" aria-label="Pesan" />
        <button type="submit" disabled={!text.trim() || !!p.busy}
          className="h-12 rounded-xl bg-bean px-5 font-semibold text-foam transition hover:bg-roast disabled:opacity-40">
          Kirim
        </button>
      </form>
    </section>
  );
}
