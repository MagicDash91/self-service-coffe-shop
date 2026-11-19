"use client";
import { useMemo, useState } from "react";
import type { Menu, MenuItem } from "@/lib/types";
import { rp } from "@/lib/api";

export type Opts = { size: string; temperature: string; milk: string; addons: string[]; sugar: string; qty: number };

function Seg({ label, options, value, onChange }: {
  label: string; options: { v: string; t: string }[]; value: string; onChange: (v: string) => void;
}) {
  return (
    <fieldset className="mt-4">
      <legend className="mb-2 text-xs font-semibold uppercase tracking-wider text-roast/60">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => (
          <button key={o.v} type="button" onClick={() => onChange(o.v)} aria-pressed={value === o.v}
            className={`rounded-xl border px-3 py-2 text-sm transition ${value === o.v
              ? "border-bean bg-bean text-foam" : "border-line bg-white text-bean hover:border-caramel"}`}>
            {o.t}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

export function CustomizeSheet({ item, menu, onClose, onAdd }: {
  item: MenuItem; menu: Menu; onClose: () => void; onAdd: (o: Opts) => void;
}) {
  const [o, setO] = useState<Opts>({ size: "regular", temperature: item.temps?.[0] || "hot", milk: "regular",
    addons: [], sugar: "normal", qty: 1 });
  const unit = useMemo(() => item.kind !== "drink" ? item.price
    : item.price + (menu.sizes[o.size] || 0) + (item.milk ? menu.milks[o.milk] || 0 : 0)
      + o.addons.reduce((s, a) => s + menu.addons[a].price, 0), [o, item, menu]);
  const set = <K extends keyof Opts>(k: K, v: Opts[K]) => setO((p) => ({ ...p, [k]: v }));

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-bean/40 sm:items-center sm:p-6"
      onClick={onClose} role="dialog" aria-modal aria-label={`Atur ${item.name}`}>
      <div className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-3xl bg-foam p-6 sm:rounded-3xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-display text-2xl text-bean">{item.name}</h2>
            <p className="mt-1 text-sm text-roast/70">{item.desc}</p>
          </div>
          <button onClick={onClose} className="rounded-full p-2 text-roast hover:bg-crema" aria-label="Tutup">✕</button>
        </div>

        {item.kind === "drink" && (
          <>
            <Seg label="Ukuran" value={o.size} onChange={(v) => set("size", v)}
              options={[{ v: "regular", t: "Reguler" }, { v: "large", t: `Besar +${rp(menu.sizes.large)}` }]} />
            {(item.temps?.length || 0) > 1 && (
              <Seg label="Suhu" value={o.temperature} onChange={(v) => set("temperature", v)}
                options={(item.temps || []).map((t) => ({ v: t, t: t === "iced" ? "Dingin" : "Panas" }))} />
            )}
            {item.milk && (
              <Seg label="Susu" value={o.milk} onChange={(v) => set("milk", v)}
                options={Object.entries(menu.milks).map(([k, p]) => ({ v: k, t: p ? `Susu ${cap(k)} +${rp(p)}` : "Susu biasa" }))} />
            )}
            <fieldset className="mt-4">
              <legend className="mb-2 text-xs font-semibold uppercase tracking-wider text-roast/60">Tambahan</legend>
              <div className="flex flex-wrap gap-2">
                {Object.entries(menu.addons).map(([k, a]) => {
                  const on = o.addons.includes(k);
                  return (
                    <button key={k} type="button" aria-pressed={on}
                      onClick={() => set("addons", on ? o.addons.filter((x) => x !== k) : [...o.addons, k])}
                      className={`rounded-xl border px-3 py-2 text-sm transition ${on
                        ? "border-caramel bg-caramel/15 text-bean" : "border-line bg-white text-bean hover:border-caramel"}`}>
                      {a.label} +{rp(a.price)}
                    </button>
                  );
                })}
              </div>
            </fieldset>
            <Seg label="Gula" value={o.sugar} onChange={(v) => set("sugar", v)}
              options={menu.sugar_levels.map((s) => ({ v: s, t: s === "none" ? "Tanpa gula" : s === "less" ? "Kurang manis" : "Normal" }))} />
          </>
        )}

        <div className="mt-6 flex items-center gap-3">
          <div className="flex items-center rounded-xl border border-line bg-white">
            <button className="px-4 py-3 text-lg" onClick={() => set("qty", Math.max(1, o.qty - 1))} aria-label="Kurangi">−</button>
            <span className="w-8 text-center font-semibold" aria-live="polite">{o.qty}</span>
            <button className="px-4 py-3 text-lg" onClick={() => set("qty", Math.min(20, o.qty + 1))} aria-label="Tambah">+</button>
          </div>
          <button onClick={() => onAdd(o)}
            className="flex-1 rounded-xl bg-bean px-5 py-3.5 font-semibold text-foam transition hover:bg-roast">
            Tambah ke pesanan · {rp(unit * o.qty)}
          </button>
        </div>
      </div>
    </div>
  );
}
