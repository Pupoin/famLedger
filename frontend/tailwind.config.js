/** @type {import('tailwindcss').Config} */

function colorVar(name) {
  return `rgb(var(--color-${name}))`;
}

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        "primary": colorVar("primary"),
        "on-primary": colorVar("on-primary"),
        "primary-container": colorVar("primary-container"),
        "on-primary-container": colorVar("on-primary-container"),
        "primary-dim": colorVar("primary-dim"),
        "primary-fixed": colorVar("primary-fixed"),
        "primary-fixed-dim": colorVar("primary-fixed-dim"),
        "on-primary-fixed": colorVar("on-primary-fixed"),
        "on-primary-fixed-variant": colorVar("on-primary-fixed-variant"),
        "secondary": colorVar("secondary"),
        "on-secondary": colorVar("on-secondary"),
        "secondary-container": colorVar("secondary-container"),
        "on-secondary-container": colorVar("on-secondary-container"),
        "secondary-dim": colorVar("secondary-dim"),
        "secondary-fixed": colorVar("secondary-fixed"),
        "secondary-fixed-dim": colorVar("secondary-fixed-dim"),
        "on-secondary-fixed": colorVar("on-secondary-fixed"),
        "on-secondary-fixed-variant": colorVar("on-secondary-fixed-variant"),
        "tertiary": colorVar("tertiary"),
        "on-tertiary": colorVar("on-tertiary"),
        "tertiary-container": colorVar("tertiary-container"),
        "on-tertiary-container": colorVar("on-tertiary-container"),
        "tertiary-dim": colorVar("tertiary-dim"),
        "tertiary-fixed": colorVar("tertiary-fixed"),
        "tertiary-fixed-dim": colorVar("tertiary-fixed-dim"),
        "on-tertiary-fixed": colorVar("on-tertiary-fixed"),
        "on-tertiary-fixed-variant": colorVar("on-tertiary-fixed-variant"),
        "error": colorVar("error"),
        "on-error": colorVar("on-error"),
        "error-container": colorVar("error-container"),
        "on-error-container": colorVar("on-error-container"),
        "error-dim": colorVar("error-dim"),
        "background": colorVar("background"),
        "on-background": colorVar("on-background"),
        "surface": colorVar("surface"),
        "on-surface": colorVar("on-surface"),
        "surface-variant": colorVar("surface-variant"),
        "on-surface-variant": colorVar("on-surface-variant"),
        "surface-dim": colorVar("surface-dim"),
        "surface-bright": colorVar("surface-bright"),
        "surface-container-lowest": colorVar("surface-container-lowest"),
        "surface-container-low": colorVar("surface-container-low"),
        "surface-container": colorVar("surface-container"),
        "surface-container-high": colorVar("surface-container-high"),
        "surface-container-highest": colorVar("surface-container-highest"),
        "surface-tint": colorVar("surface-tint"),
        "outline": colorVar("outline"),
        "outline-variant": colorVar("outline-variant"),
        "inverse-surface": colorVar("inverse-surface"),
        "inverse-on-surface": colorVar("inverse-on-surface"),
        "inverse-primary": colorVar("inverse-primary"),
      },
      fontFamily: {
        headline: [
          "Plus Jakarta Sans",
          "-apple-system",
          "BlinkMacSystemFont",
          "PingFang SC",
          "MiSans",
          "Samsung Sans",
          "Noto Sans SC",
          "Microsoft YaHei",
          "sans-serif",
        ],
        body: [
          "Public Sans",
          "-apple-system",
          "BlinkMacSystemFont",
          "PingFang SC",
          "MiSans",
          "Samsung Sans",
          "Noto Sans SC",
          "Microsoft YaHei",
          "sans-serif",
        ],
        label: [
          "Public Sans",
          "-apple-system",
          "BlinkMacSystemFont",
          "PingFang SC",
          "MiSans",
          "Samsung Sans",
          "Noto Sans SC",
          "sans-serif",
        ],
        mono: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "PingFang SC",
          "MiSans",
          "Noto Sans SC",
          "sans-serif",
        ],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "0.875rem" }], // 11px / 14px
        "xs": ["0.75rem", { lineHeight: "1rem" }],        // 12px / 16px
        "sm": ["0.875rem", { lineHeight: "1.25rem" }],     // 14px / 20px
        "base": ["1rem", { lineHeight: "1.375rem" }],      // 16px / 22px
        "lg": ["1.125rem", { lineHeight: "1.5rem" }],      // 18px / 24px
        "xl": ["1.25rem", { lineHeight: "1.625rem" }],     // 20px / 26px
        "2xl": ["1.5rem", { lineHeight: "1.875rem" }],     // 24px / 30px
        "3xl": ["1.75rem", { lineHeight: "2.125rem" }],    // 28px / 34px
      },
      borderRadius: {
        DEFAULT: "0.25rem",
        lg: "0.5rem",
        xl: "0.75rem",
        "2xl": "1rem",
        "3xl": "1.5rem",
        full: "9999px",
      },
    },
  },
  plugins: [],
};
