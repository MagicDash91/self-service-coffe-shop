import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        crema: "#F6EFE6",
        foam: "#FBF7F1",
        bean: "#2B1D16",
        roast: "#5A3A2A",
        caramel: "#C8873A",
        leaf: "#3F6B4E",
        line: "#E6DACB",
      },
      fontFamily: {
        display: ["var(--font-display)", "Georgia", "serif"],
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
export default config;
