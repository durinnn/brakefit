import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // 무채색 베이스 (신뢰감)
        ink: {
          950: "#0B0C0E",
          900: "#121417",
          800: "#191C21",
          700: "#232830",
          600: "#333A45",
          500: "#4A525F",
          400: "#6B7484",
          300: "#98A1AF",
          200: "#C6CCD5",
          100: "#E6E9ED",
        },
        // 포인트 컬러: 위험(적), 안전(청록)
        risk: {
          DEFAULT: "#E0484A",
          soft: "#F0787A",
          dim: "#5C2325",
        },
        safe: {
          DEFAULT: "#2FB6A0",
          soft: "#6FD4C3",
          dim: "#17403A",
        },
        warn: {
          DEFAULT: "#E0A030",
        },
      },
      fontFamily: {
        sans: [
          "var(--font-sans)",
          "Pretendard",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
