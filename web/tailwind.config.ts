import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "1.25rem",
      screens: {
        "2xl": "1380px",
      },
    },
    extend: {
      colors: {
        border: "var(--ghost-outline)",
        input: "var(--surface-container-low)",
        ring: "var(--accent)",
        outline: "var(--ghost-outline)",
        background: "var(--background)",
        foreground: "var(--text-primary)",
        surface: {
          DEFAULT: "var(--surface)",
          container: "var(--surface-container)",
          "container-low": "var(--surface-container-low)",
          "container-high": "var(--surface-container-high)",
          "container-highest": "var(--surface-container-highest)",
          "container-lowest": "var(--surface-container-lowest)",
          ghost: "var(--surface-ghost)",
          glass: "var(--surface-glass)",
        },
        primary: {
          DEFAULT: "var(--accent)",
          foreground: "var(--accent-ink)",
        },
        secondary: {
          DEFAULT: "var(--surface-container-highest)",
          foreground: "var(--text-primary)",
        },
        muted: {
          DEFAULT: "var(--surface-container-low)",
          foreground: "var(--text-muted)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          strong: "var(--accent-strong)",
          deep: "var(--accent-deep)",
          ink: "var(--accent-ink)",
          foreground: "var(--accent-ink)",
        },
        destructive: {
          DEFAULT: "var(--danger)",
          foreground: "var(--text-primary)",
        },
        card: {
          DEFAULT: "var(--surface-container-highest)",
          foreground: "var(--text-primary)",
        },
        popover: {
          DEFAULT: "var(--surface-container-highest)",
          foreground: "var(--text-primary)",
        },
        text: {
          primary: "var(--text-primary)",
          secondary: "var(--text-secondary)",
          muted: "var(--text-muted)",
          disabled: "var(--text-muted)",
        },
        success: {
          DEFAULT: "var(--success)",
          text: "var(--success)",
        },
        warning: {
          DEFAULT: "var(--warning)",
          text: "var(--warning)",
        },
        danger: {
          DEFAULT: "var(--danger)",
          text: "var(--danger)",
        },
      },
      borderRadius: {
        xl: "0.75rem",
        lg: "0.5rem",
        md: "0.375rem",
        sm: "0.25rem",
      },
      boxShadow: {
        soft: "var(--shadow-soft)",
        float: "var(--shadow-float)",
      },
      backgroundImage: {
        "page-gradient": "var(--page-gradient)",
      },
      fontFamily: {
        sans: ["Inter", '"Noto Sans SC"', '"PingFang SC"', '"Microsoft YaHei"', "sans-serif"],
        display: ["Inter", '"Noto Sans SC"', '"PingFang SC"', '"Microsoft YaHei"', "sans-serif"],
        mono: ['"Geist Mono"', '"SFMono-Regular"', "ui-monospace", "monospace"],
      },
      keyframes: {
        float: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-8px)" },
        },
        pulseLine: {
          "0%": { opacity: "0.55" },
          "50%": { opacity: "1" },
          "100%": { opacity: "0.55" },
        },
      },
      animation: {
        float: "float 7s ease-in-out infinite",
        pulseLine: "pulseLine 2.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
