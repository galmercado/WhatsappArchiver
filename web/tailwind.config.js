/** WhatsApp Web look: every colour is a CSS variable so light/dark share one set of utilities. */
const v = (name) => `var(--${name})`;
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        app: v("app-bg"),
        sidebar: v("sidebar-bg"),
        panel: v("panel-header-bg"),
        chat: v("chat-bg"),
        hover: v("hover-bg"),
        selected: v("selected-bg"),
        line: v("border"),
        ink: v("text-primary"),
        ink2: v("text-secondary"),
        icon: v("icon"),
        accent: v("accent"),
        "accent-strong": v("accent-strong"),
        unread: v("unread"),
        tick: v("tick-blue"),
        "bubble-in": v("bubble-in"),
        "bubble-out": v("bubble-out"),
        input: v("input-bg"),
        chip: v("chip-bg"),
      },
      fontFamily: {
        sans: ['"Segoe UI"', '"Helvetica Neue"', "Helvetica", '"Lucida Grande"', "Arial", "Ubuntu", "Cantarell", '"Fira Sans"', "sans-serif"],
      },
      fontSize: { msg: ["14.2px", "19px"], meta: ["11px", "15px"], list: ["17px", "21px"], sub: ["14px", "20px"] },
      keyframes: {
        flash: { "0%,60%": { backgroundColor: "var(--flash)" }, "100%": { backgroundColor: "transparent" } },
        pop: { from: { opacity: "0", transform: "scale(.96)" }, to: { opacity: "1", transform: "scale(1)" } },
      },
      animation: { flash: "flash 2s ease-out", pop: "pop .12s ease-out" },
    },
  },
  plugins: [],
};
