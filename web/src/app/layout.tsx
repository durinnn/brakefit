import type { Metadata, Viewport } from "next";
import "./globals.css";
import BottomNav from "@/components/BottomNav";

export const metadata: Metadata = {
  title: "매매 브레이크",
  description: "무리한 매매 직전에 개입하는 행동 편향 방어 시스템",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0B0C0E",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body className="min-h-screen bg-ink-950 font-sans antialiased">
        {/* 모바일 MTS 채널 타겟: 컨텐츠 폭을 모바일 기준으로 고정 */}
        <div className="mx-auto flex min-h-screen w-full max-w-[430px] flex-col border-x border-ink-800 bg-ink-950">
          <main className="flex-1 pb-24">{children}</main>
          <BottomNav />
        </div>
      </body>
    </html>
  );
}
