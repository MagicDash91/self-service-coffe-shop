import type { KioskView, Menu } from "./types";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers: init?.body instanceof FormData ? undefined
      : { "Content-Type": "application/json", ...(init?.headers || {}) } });
  } catch {
    throw new Error("Tidak bisa terhubung ke server kios.");
  }
  if (!res.ok) {
    let msg = `Permintaan gagal (${res.status})`;
    try { const j = await res.json(); msg = j.detail || msg; } catch { /* proxy error page */
      if (res.status >= 500) msg = "Server kios belum berjalan (port 8020)."; }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}
const post = <T,>(path: string, body: unknown) => call<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => call<{ llm: string; stt: string; tts: string }>("/api/health"),
  menu: () => call<Menu>("/api/menu"),
  newSession: () => call<KioskView & { session_id: string }>("/api/session", { method: "POST" }),
  chat: (session_id: string, text: string) => post<KioskView>("/api/chat", { session_id, text }),
  add: (session_id: string, item: Record<string, unknown>) => post<KioskView>("/api/cart/add", { session_id, ...item }),
  line: (session_id: string, line_id: string, delta: number) => post<KioskView>("/api/cart/line", { session_id, line_id, delta }),
  offer: (session_id: string, accept: boolean) => post<KioskView>(`/api/offer/${accept ? "accept" : "decline"}`, { session_id }),
  checkout: (session_id: string) => post<KioskView>("/api/checkout", { session_id }),
  pay: (session_id: string, method: string) => post<KioskView>(`/api/pay/${method}`, { session_id }),
  confirmPay: (session_id: string) => post<KioskView>("/api/pay/confirm", { session_id }),
  stt: (blob: Blob) => { const f = new FormData(); f.append("audio", blob, "speech.webm");
    return call<{ text: string; language: string; ms: number }>("/api/stt", { method: "POST", body: f }); },
  tts: async (text: string): Promise<Blob> => {
    const r = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }) });
    if (!r.ok) throw new Error("Suara gagal dibuat");
    return r.blob();
  },
  queue: () => call<{ orders: import("./types").Order[] }>("/api/orders/queue"),
  setStatus: (id: string, status: string) => post(`/api/orders/${id}/${status}`, {}),
};

export const rp = (n: number) => "Rp" + Math.round(n).toLocaleString("id-ID");
