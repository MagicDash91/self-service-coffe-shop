export type MenuItem = {
  id: string; name: string; category: "coffee" | "non-coffee" | "food"; kind: "drink" | "food";
  price: number; desc: string; temps?: string[]; milk?: boolean;
};
export type Menu = {
  currency: string; items: MenuItem[]; sizes: Record<string, number>; milks: Record<string, number>;
  addons: Record<string, { label: string; price: number }>; sugar_levels: string[];
  combos: { id: string; name: string; discount: number; desc: string }[];
};
export type CartLine = {
  line_id: string; item_id: string; name: string; kind: string; qty: number; size?: string;
  temperature?: string; milk?: string | null; addons?: string[]; sugar?: string;
  unit_price: number; line_total: number; label: string;
};
export type Offer = { combo_id: string; combo_name: string; add_item_name: string; add_item_price: number;
  discount: number; pitch: string };
export type Order = { id: string; number: string; method: "qris" | "card" | "cash"; status: string;
  total: number; subtotal: number; discount: number; combos: string[]; items: Partial<CartLine>[];
  created_at_local: string };
export type Totals = { subtotal: number; discount: number; total: number; item_count: number;
  combos: { combo_id: string; name: string; discount: number; items: string[] }[] };
export type Stage = "ordering" | "confirming" | "paying" | "done";
export type KioskView = {
  cart: CartLine[]; totals: Totals; stage: Stage; pending_offer: Offer | null; order: Order | null;
  reply?: string; suggestions?: string[]; nlu?: Record<string, unknown>; nlu_source?: string;
  timings?: Record<string, number>; session_id?: string;
};
export type Msg = { role: "customer" | "kiosk"; text: string; meta?: string; voice?: boolean };
