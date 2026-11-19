import type { MenuItem } from "@/lib/types";

// Tiny illustrated tiles (no image assets needed): a cup for drinks, a plate for food.
const TINT: Record<string, string> = {
  espresso: "#3B2416", americano: "#4A2E1E", cappuccino: "#A9805E", cafe_latte: "#C49A74",
  caramel_macchiato: "#C8873A", mocha: "#6B4130", kopi_susu_aren: "#9C6B45", cold_brew: "#2F1E14",
  matcha_latte: "#7FA36B", chocolate: "#5B3524", lemon_tea: "#D9A441",
  croissant: "#D9A25B", banana_bread: "#8E5B33", choco_muffin: "#4E2E1F", cinnamon_roll: "#C68B52",
  chicken_sandwich: "#B98A54",
};

export function ItemArt({ item, small = false }: { item: MenuItem; small?: boolean }) {
  const c = TINT[item.id] || "#8B5E3C";
  const iced = item.temps?.[0] === "iced";
  const size = small ? "h-9 w-9" : "h-16 w-16";
  const art =
    item.kind === "drink" ? (
      <svg viewBox="0 0 64 64" className={`${size} transition group-hover:scale-105`} aria-hidden>
        {iced ? (
          <>
            <path d="M18 14h28l-3 40a4 4 0 0 1-4 4H25a4 4 0 0 1-4-4z" fill="#fff" stroke="#E6DACB" strokeWidth="2" />
            <path d="M20 26h24l-2 27a3 3 0 0 1-3 3H25a3 3 0 0 1-3-3z" fill={c} />
            <rect x="26" y="30" width="7" height="7" rx="1.5" fill="#fff" opacity=".55" />
            <rect x="34" y="38" width="6" height="6" rx="1.5" fill="#fff" opacity=".45" />
            <path d="M36 6l-4 20" stroke="#C8873A" strokeWidth="3" strokeLinecap="round" />
          </>
        ) : (
          <>
            <path d="M14 24h32v14a14 14 0 0 1-14 14h-4a14 14 0 0 1-14-14z" fill="#fff" stroke="#E6DACB" strokeWidth="2" />
            <ellipse cx="30" cy="25" rx="15" ry="4" fill={c} />
            <path d="M46 29h3a6 6 0 0 1 0 12h-4" fill="none" stroke="#E6DACB" strokeWidth="3" />
            <path d="M24 8c-2 3 2 5 0 8M32 6c-2 3 2 5 0 8" stroke="#C9B8A6" strokeWidth="2" fill="none" strokeLinecap="round" />
            <ellipse cx="30" cy="56" rx="20" ry="3" fill="#E6DACB" />
          </>
        )}
      </svg>
    ) : (
      <svg viewBox="0 0 64 64" className={`${size} transition group-hover:scale-105`} aria-hidden>
        <ellipse cx="32" cy="46" rx="26" ry="7" fill="#fff" stroke="#E6DACB" strokeWidth="2" />
        <path d="M12 42c2-14 12-22 20-22s18 8 20 22z" fill={c} />
        <path d="M20 34c4-4 8-6 12-6M34 30c4 0 8 2 10 6" stroke="#fff" strokeOpacity=".35" strokeWidth="2"
          fill="none" strokeLinecap="round" />
      </svg>
    );
  if (small) return art;
  return <div className="flex h-24 items-center justify-center rounded-xl bg-crema">{art}</div>;
}
