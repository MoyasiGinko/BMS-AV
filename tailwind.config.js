// Used with the Tailwind standalone CLI (no Node needed): tailwindcss -c tailwind.config.js -i static/css/input.css -o static/css/app.css --minify
module.exports = {
  content: ["./templates/**/*.html", "./apps/**/templates/**/*.html", "./static/js/**/*.js"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        brand: { 50: "var(--brand-50)", 100: "var(--brand-100)", 500: "var(--brand-500)", 600: "var(--brand-600)", 700: "var(--brand-700)", 900: "var(--brand-900)" },
        surface: "var(--surface)", "surface-2": "var(--surface-2)", app: "var(--bg)", line: "var(--border)", ink: "var(--text)", muted: "var(--text-muted)",
        success: "var(--success)", warning: "var(--warning)", danger: "var(--danger)", info: "var(--info)",
      },
      fontFamily: { sans: "var(--font-sans)", mono: "var(--font-mono)" },
      borderRadius: { sm: "var(--radius-sm)", md: "var(--radius-md)" },
      boxShadow: { sm: "var(--shadow-sm)", lg: "var(--shadow-lg)" },
    },
  },
  plugins: [],
};
