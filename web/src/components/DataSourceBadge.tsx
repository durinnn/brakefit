"use client";

import Link from "next/link";
import { useEffect } from "react";
import type { DataSource } from "@/lib/api";
import { clearClientSession } from "@/lib/session";

interface DataSourceBadgeProps {
  source: DataSource;
  /** source === "session" 일 때 표시할 거래 건수 */
  tradeCount: number;
  /** 세션이 만료돼 데모로 폴백했는지 (쿠키를 정리해야 함) */
  sessionExpired: boolean;
}

/**
 * 지금 보고 있는 데이터가 데모인지 내 거래내역인지 한 줄로 알려준다.
 *
 * 서버 컴포넌트는 쿠키를 지울 수 없어서(응답 헤더를 못 건드림) 만료된 세션 쿠키
 * 정리를 여기서 한다 — 서버는 이미 페르소나로 폴백해 렌더를 마친 상태다.
 */
export default function DataSourceBadge({
  source,
  tradeCount,
  sessionExpired,
}: DataSourceBadgeProps) {
  useEffect(() => {
    if (sessionExpired) clearClientSession();
  }, [sessionExpired]);

  function resetToDemo() {
    clearClientSession();
    // 서버 컴포넌트가 쿠키 없는 상태로 다시 렌더되도록 전체 이동
    window.location.assign("/dashboard");
  }

  return (
    <div className="flex items-center justify-between gap-3 border-b border-ink-800 bg-ink-900 px-5 py-2.5">
      <span className="flex items-center gap-2 text-xs text-ink-300">
        <span
          className={[
            "h-1.5 w-1.5 rounded-full",
            source === "session" ? "bg-safe" : "bg-ink-500",
          ].join(" ")}
        />
        {source === "session" ? (
          <span className="tabular">
            내 거래내역 · {tradeCount.toLocaleString("ko-KR")}건
          </span>
        ) : (
          <span>
            데모 페르소나
            {sessionExpired ? " (업로드 세션 만료됨)" : ""}
          </span>
        )}
      </span>

      {source === "session" ? (
        <button
          type="button"
          onClick={resetToDemo}
          className="shrink-0 text-xs text-ink-500 underline underline-offset-4 hover:text-ink-300"
        >
          데모로 되돌리기
        </button>
      ) : (
        <Link
          href="/upload"
          className="shrink-0 text-xs text-ink-500 underline underline-offset-4 hover:text-ink-300"
        >
          내 거래내역 올리기
        </Link>
      )}
    </div>
  );
}
