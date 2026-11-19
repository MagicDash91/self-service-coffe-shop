"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, rp } from "@/lib/api";
import type { Order } from "@/lib/types";

const COLS = [
  { id: "todo", title: "Perlu dibuat", match: (o: Order) => o.status === "preparing" || o.status === "pay_at_counter" },
  { id: "ready", title: "Siap diambil", match: (o: Order) => o.status === "ready" },
];

function itemText(i: Order["items"][number]) {
  const bits = [i.name, i.size === "large" ? "besar" : "", i.temperature === "iced" ? "dingin" : ""].filter(Boolean).join(" ");
  const extras = [i.milk && i.milk !== "regular" ? `susu ${i.milk}` : "", ...(i.addons || []).map((a) => a.replace("_", " ")),
    i.sugar && i.sugar !== "normal" ? (i.sugar === "less" ? "kurang manis" : "tanpa gula") : ""].filter(Boolean);
  return `${i.qty}× ${bits}${extras.length ? ` (${extras.join(", ")})` : ""}`;
}

export default function Barista() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [err, setErr] = useState("");
  const load = useCallback(() => api.queue().then((r) => { setOrders(r.orders); setErr(""); })
    .catch((e) => setErr(e.message)), []);
  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t); }, [load]);

  const move = async (o: Order, status: string) => { await api.setStatus(o.id, status).catch(() => {}); load(); };

  return (
    <div className="min-h-screen px-6 py-5">
      <header className="mb-5 flex items-center justify-between">
        <h1 className="font-display text-3xl text-bean">Layar barista</h1>
        <Link href="/" className="rounded-full bg-white px-4 py-1.5 text-sm text-bean hover:bg-crema">Kembali ke kios</Link>
      </header>
      {err && <p role="alert" className="mb-4 rounded-xl bg-red-50 px-4 py-2 text-sm text-red-800">{err}</p>}
      <div className="grid gap-5 md:grid-cols-2">
        {COLS.map((c) => {
          const list = orders.filter(c.match);
          return (
            <section key={c.id} className="rounded-3xl border border-line bg-white/60 p-4">
              <h2 className="mb-3 font-semibold text-roast">{c.title} <span className="text-roast/50">({list.length})</span></h2>
              {list.length === 0 && <p className="py-8 text-center text-sm text-roast/40">Belum ada pesanan</p>}
              <div className="space-y-3">
                {list.map((o) => (
                  <article key={o.id} className="rounded-2xl border border-line bg-white p-4">
                    <div className="flex items-baseline justify-between">
                      <span className="font-display text-3xl text-bean">{o.number}</span>
                      <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${o.status === "pay_at_counter"
                        ? "bg-caramel/15 text-caramel" : "bg-leaf/10 text-leaf"}`}>
                        {o.status === "pay_at_counter" ? `Belum bayar · tunai ${rp(o.total)}` : `Lunas · ${o.method === "card" ? "KARTU" : o.method.toUpperCase()}`}
                      </span>
                    </div>
                    <ul className="mt-2 space-y-0.5 text-sm text-bean">
                      {o.items.map((i, k) => <li key={k}>{itemText(i)}</li>)}
                    </ul>
                    {o.combos.length > 0 && <p className="mt-1 text-xs text-leaf">{o.combos.join(", ")}</p>}
                    <p className="mt-1 text-xs text-roast/50">{o.created_at_local.slice(11, 16)}</p>
                    <div className="mt-3 flex gap-2">
                      {c.id === "todo" ? (
                        <button onClick={() => move(o, "ready")} className="rounded-lg bg-bean px-3 py-2 text-sm font-semibold text-foam hover:bg-roast">
                          Tandai siap
                        </button>
                      ) : (
                        <button onClick={() => move(o, "collected")} className="rounded-lg bg-leaf px-3 py-2 text-sm font-semibold text-white">
                          Sudah diambil
                        </button>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
