import type { Config } from 'tailwindcss';
const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: { 950: '#0b1220', 900: '#111a2e', 800: '#1a2540', 700: '#26324f', 500: '#5b6787', 300: '#a9b2c8' },
        paper: { DEFAULT: '#f6f4ef', 100: '#fbfaf7', 200: '#ece8de', 300: '#ddd7c8' },
        seal: { DEFAULT: '#0f7a55', 50: '#e7f5ee', 600: '#0b6646' },
        saffron: { DEFAULT: '#e0861a', 50: '#fdf1e2' },
        alarm: { DEFAULT: '#c2362b', 50: '#fbe9e7' },
      },
      fontFamily: {
        display: ['"Iowan Old Style"', '"Palatino Linotype"', 'Palatino', 'Georgia', 'serif'],
        sans: ['ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', '"SF Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: { card: '0 1px 0 rgba(11,18,32,.04), 0 1px 3px rgba(11,18,32,.08)' },
    },
  },
  plugins: [],
};
export default config;
