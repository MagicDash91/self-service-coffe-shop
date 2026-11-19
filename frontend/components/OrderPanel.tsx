"use client";
import type { KioskView } from "@/lib/types";
import { rp } from "@/lib/api";

type Props = {
  view: KioskView;
  busy: boolean;
  onLine: (lineId: string, delta: number) => void;
  onOffer: (accept: boolean) => void;
  onCheckout: () => void;
  onPay: (method: string) => void;
  onConfirmPay: () => void;
  onNewOrder: () => void;
};

/** Deterministic fake QR so the demo looks like a real QRIS screen. */
function FakeQR({ seed }: { seed: string }) {
  let h = 2166136261;
  for (const ch of seed) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  const n = 25;
  const cells: JSX.Element[] = [];
  const finder = (x: number, y: number) => (x < 7 && y < 7) || (x >= n - 7 && y < 7) || (x < 7 && y >= n - 7);
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    let on: boolean;
    if (finder(x, y)) {
      const fx = x < 7 ? x : x - (n - 7), fy = y < 7 ? y : y - (n - 7);
      on = fx === 0 || fx === 6 || fy === 0 || fy === 6 || (fx >= 2 && fx <= 4 && fy >= 2 && fy <= 4);
    } else {
      h = Math.imul(h ^ (x * 31 + y), 16777619);
      on = ((h >>> 7) & 1) === 1;
    }
    if (on) cells.push(<rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" />);
  }
  return (
    <svg viewBox={`-2 -2 ${n + 4} ${n + 4}`} className="mx-auto h-44 w-44 rounded-lg bg-white" shapeRendering="crispEdges"
      role="img" aria-label="Kode pembayaran QRIS (demo)">
      <g fill="#2B1D16">{cells}</g>
    </svg>
  );
}

export function OrderPanel({ view, busy, onLine, onOffer, onCheckout, onPay, onConfirmPay, onNewOrder }: Props) {
  const { cart, totals, stage, pending_offer: offer, order } = view;

  if (stage === "done" && order) {
    return (
      <section className="flex flex-col items-center justify-center rounded-3xl border border-line bg-white p-8 text-center"
        aria-label="Pesanan diterima">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-leaf">
          {order.method === "cash" ? "Pesanan dicatat" : "Lunas"}
        </p>
        <p className="mt-3 text-sm text-roast/70">Nomor pesanan Kakak</p>
        <p className="font-display text-7xl leading-none text-bean">{order.number}</p>
        <p className="mt-4 max-w-[16rem] text-sm text-roast/70">
          {order.method === "cash" ? `Silakan bayar ${rp(order.total)} di kasir.`
            : "Nomor Kakak akan dipanggil kalau pesanan sudah siap."}
        </p>
        <button onClick={onNewOrder} className="mt-8 rounded-xl bg-bean px-6 py-3 font-semibold text-foam hover:bg-roast">
          Mulai pesanan baru
        </button>
      </section>
    );
  }

  return (
    <section className="flex min-h-0 flex-col rounded-3xl border border-line bg-white" aria-label="Pesanan Kakak">
      <header className="flex items-baseline justify-between border-b border-line px-5 py-4">
        <h2 className="font-display text-2xl text-bean">Pesanan Kakak</h2>
        <span className="text-sm text-roast/60">{totals.item_count} item</span>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
        {cart.length === 0 ? (
          <p className="py-10 text-center text-sm text-roast/50">Belum ada pesanan. Ketuk menu atau langsung sebutkan pesanan Kakak.</p>
        ) : (
          <ul className="divide-y divide-line">
            {cart.map((l) => {
              const detail = l.label.replace(/^\d+x\s*/, "").replace(l.name, "").replace(/\s+/g, " ").trim();
              return (
                <li key={l.line_id} className="flex items-start gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-bean">{l.name}</p>
                    {detail && <p className="text-xs text-roast/60">{detail}</p>}
                    <p className="mt-0.5 text-sm text-roast">{rp(l.line_total)}</p>
                  </div>
                  {stage !== "paying" && (
                    <div className="flex items-center rounded-lg border border-line">
                      <button disabled={busy} onClick={() => onLine(l.line_id, -1)} className="px-2.5 py-1 text-roast disabled:opacity-40"
                        aria-label={`Kurangi ${l.name}`}>−</button>
                      <span className="w-6 text-center text-sm font-semibold">{l.qty}</span>
                      <button disabled={busy} onClick={() => onLine(l.line_id, 1)} className="px-2.5 py-1 text-roast disabled:opacity-40"
                        aria-label={`Tambah ${l.name}`}>+</button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {offer && stage === "ordering" && (
          <div className="mt-3 rounded-2xl border border-caramel/40 bg-caramel/10 p-4">
            <p className="text-xs font-semibold uppercase tracking-wider text-caramel">Promo paket</p>
            <p className="mt-1 text-sm text-bean">{offer.pitch}.</p>
            <div className="mt-3 flex gap-2">
              <button disabled={busy} onClick={() => onOffer(true)}
                className="rounded-lg bg-bean px-3 py-2 text-sm font-semibold text-foam hover:bg-roast disabled:opacity-50">
                Iya, tambahkan
              </button>
              <button disabled={busy} onClick={() => onOffer(false)}
                className="rounded-lg px-3 py-2 text-sm text-roast hover:bg-crema disabled:opacity-50">Nggak, makasih</button>
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-line px-5 py-4">
        <dl className="space-y-1 text-sm">
          <div className="flex justify-between text-roast/70"><dt>Subtotal</dt><dd>{rp(totals.subtotal)}</dd></div>
          {totals.combos.map((c, i) => (
            <div key={i} className="flex justify-between text-leaf"><dt>{c.name}</dt><dd>−{rp(c.discount)}</dd></div>
          ))}
          <div className="flex justify-between pt-1 text-lg font-semibold text-bean"><dt>Total</dt><dd>{rp(totals.total)}</dd></div>
        </dl>

        {stage === "ordering" && (
          <button disabled={busy || cart.length === 0} onClick={onCheckout}
            className="mt-4 w-full rounded-xl bg-bean py-3.5 font-semibold text-foam transition hover:bg-roast disabled:opacity-40">
            Lanjut bayar
          </button>
        )}

        {stage === "confirming" && (
          <div className="mt-4">
            <p className="mb-2 text-sm font-medium text-bean">Mau bayar pakai apa?</p>
            <div className="grid grid-cols-3 gap-2">
              {[["qris", "QRIS"], ["card", "Kartu"], ["cash", "Tunai"]].map(([m, t]) => (
                <button key={m} disabled={busy} onClick={() => onPay(m)}
                  className="rounded-xl border border-line bg-foam py-3 font-semibold text-bean transition hover:border-caramel disabled:opacity-50">
                  {t}
                </button>
              ))}
            </div>
          </div>
        )}

        {stage === "paying" && order && (
          <div className="mt-4 rounded-2xl bg-crema p-4 text-center">
            {order.method === "qris" && <><FakeQR seed={order.id} /><p className="mt-2 text-sm text-roast">Scan pakai e-wallet atau aplikasi bank apa saja</p></>}
            {order.method === "card" && (
              <div className="py-4">
                <div className="mx-auto h-24 w-36 animate-pulse rounded-xl bg-gradient-to-br from-roast to-bean shadow-lg" />
                <p className="mt-3 text-sm text-roast">Tempel, masukkan, atau gesek kartu di mesin</p>
              </div>
            )}
            {order.method === "cash" && <p className="py-3 text-sm text-roast">Pesanan {order.number}: bayar {rp(order.total)} di kasir.</p>}
            <p className="mt-1 text-xs text-roast/50">Demo: tidak ada pembayaran sungguhan</p>
            <button disabled={busy} onClick={onConfirmPay}
              className="mt-3 w-full rounded-xl bg-leaf py-3 font-semibold text-white transition hover:brightness-110 disabled:opacity-50">
              {order.method === "cash" ? "Kirim pesanan ke barista" : "Simulasikan pembayaran berhasil"}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
