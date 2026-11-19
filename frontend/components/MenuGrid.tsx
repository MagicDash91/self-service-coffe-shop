"use client";
import { useState } from "react";
import type { Menu, MenuItem } from "@/lib/types";
import { rp } from "@/lib/api";
import { ItemArt } from "./ItemArt";

const TABS = [
  { id: "coffee", label: "Kopi" },
  { id: "non-coffee", label: "Non-kopi" },
  { id: "food", label: "Roti & makanan" },
  { id: "combos", label: "Paket hemat" },
] as const;

export function MenuGrid({ menu, onPick }: { menu: Menu; onPick: (item: MenuItem) => void }) {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("coffee");
  const items = menu.items.filter((i) => i.category === tab);
  return (
    <section className="flex min-h-0 flex-col" aria-label="Menu">
      <div className="flex gap-2 overflow-x-auto pb-3" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
            className={`whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium transition ${
              tab === t.id ? "bg-bean text-foam" : "bg-white/70 text-roast hover:bg-white"}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "combos" ? (
        <div className="grid content-start gap-3 overflow-y-auto pr-1 sm:grid-cols-2">
          {menu.combos.map((c) => (
            <div key={c.id} className="rounded-2xl border border-line bg-white p-5">
              <div className="flex items-baseline justify-between gap-2">
                <h3 className="font-display text-xl text-bean">{c.name}</h3>
                <span className="whitespace-nowrap rounded-full bg-leaf/10 px-2.5 py-1 text-xs font-semibold text-leaf">
                  hemat {rp(c.discount)}
                </span>
              </div>
              <p className="mt-2 text-sm text-roast/80">{c.desc}</p>
              <p className="mt-3 text-xs text-roast/60">Otomatis dipakai kalau pesanan Kakak memenuhi syarat.</p>
            </div>
          ))}
        </div>
      ) : (
        <div className="grid content-start grid-cols-2 gap-3 overflow-y-auto pr-1 xl:grid-cols-3">
          {items.map((it) => (
            <button key={it.id} onClick={() => onPick(it)}
              className="group flex flex-col rounded-2xl border border-line bg-white p-3 text-left transition
                hover:-translate-y-0.5 hover:border-caramel hover:shadow-[0_8px_24px_-12px_rgba(90,58,42,.35)]
                focus-visible:outline focus-visible:outline-2 focus-visible:outline-caramel">
              <ItemArt item={it} />
              <div className="mt-3 flex items-start justify-between gap-2">
                <span className="font-medium leading-tight text-bean">{it.name}</span>
                <span className="shrink-0 text-sm font-semibold text-roast">{rp(it.price)}</span>
              </div>
              <span className="mt-1 line-clamp-2 text-xs text-roast/70">{it.desc}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
