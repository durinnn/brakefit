"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/dashboard", label: "진단" },
  { href: "/trade", label: "주문" },
  { href: "/backtest", label: "증명" },
] as const;

export default function BottomNav() {
  const pathname = usePathname();

  return (
    <nav className="fixed bottom-0 z-20 w-full max-w-[430px] border-t border-ink-800 bg-ink-900/95 backdrop-blur">
      <ul className="grid grid-cols-3">
        {TABS.map((tab) => {
          const active = pathname === tab.href;
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                className={[
                  "flex flex-col items-center gap-1 py-4 text-sm transition-colors",
                  active
                    ? "font-semibold text-ink-100"
                    : "text-ink-400 hover:text-ink-200",
                ].join(" ")}
              >
                <span
                  className={[
                    "h-1 w-8 rounded-full",
                    active ? "bg-risk" : "bg-transparent",
                  ].join(" ")}
                />
                {tab.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
