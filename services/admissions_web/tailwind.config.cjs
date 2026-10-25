/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        sky: { DEFAULT: "#EEF3FF", deep: "#DDE6FF" },
        paper: "#FFFFFF",
        ink: { DEFAULT: "#1C1946", soft: "#4A4874", faint: "#7D7BA3" },
        violet: { DEFAULT: "#5B3DF5", soft: "#ECE8FF", dark: "#4127D9" },
        sun: { DEFAULT: "#FFB21E", soft: "#FFF1CC", glow: "#FFD36B" },
        coral: { DEFAULT: "#FF6B57", soft: "#FFE7E2", dark: "#D9442F" },
        lagoon: { DEFAULT: "#0FA897", soft: "#D8F5F1", dark: "#0B7F72" },
        line: "#D9E0F5"
      },
      fontFamily: {
        display: ['"Bricolage Grotesque Variable"', "system-ui", "sans-serif"],
        sans: ['"Atkinson Hyperlegible"', "system-ui", "sans-serif"]
      },
      borderRadius: { panel: "18px", chip: "999px" },
      boxShadow: { lift: "0 1px 0 rgba(28,25,70,0.04), 0 8px 24px -12px rgba(28,25,70,0.18)" }
    }
  },
  plugins: []
};
