/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          navy: "#0B1F3A",
          primary: "#16B8A6"
        },
        bg: {
          app: "#F7F9FB",
          card: "#FFFFFF"
        },
        border: {
          subtle: "#E8EDF2"
        },
        text: {
          strong: "#0F172A",
          body: "#334155",
          muted: "#7C8B9C"
        },
        status: {
          critical: "#E5484D",
          high: "#F2851F",
          elevated: "#F5B82E",
          optimal: "#16B8A6",
          good: "#2FA36B"
        }
      },
      boxShadow: {
        card: "0 12px 30px rgba(15, 23, 42, 0.06)"
      },
      borderRadius: {
        card: "18px"
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"]
      }
    }
  },
  plugins: []
};
