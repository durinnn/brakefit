"use client";

import Link from "next/link";
import { clearClientSession } from "@/lib/session";

interface AnalysisUnavailableProps {
  /** 제목. 화면마다 문장이 조금 다르다(진단/백테스트) */
  title: string;
  /** 왜 분석이 안 됐는지 한 문단. 상세 사유는 WarningBanner 가 따로 나열한다 */
  detail: string;
}

/**
 * 분석 대상 거래가 0건일 때 점수·차트 대신 띄우는 안내 카드.
 *
 * 이게 없으면 종합 0점이 "안정" 게이지로 그려져서, 거래를 한 건도 못 읽은 상태가
 * 화면상 정상 진단과 구분되지 않는다(백엔드는 overallGrade="분석 불가" 로 내려준다).
 *
 * 클라이언트 컴포넌트인 이유: "데모로 보기" 가 세션 쿠키를 지우고 다시 들어가는
 * 동작이라(DataSourceBadge.resetToDemo 와 같다) 쿠키를 못 건드리는 서버 컴포넌트
 * 에서는 링크만으로 안 된다 — 쿠키가 남아 있으면 같은 0건 화면으로 되돌아온다.
 */
export default function AnalysisUnavailable({
  title,
  detail,
}: AnalysisUnavailableProps) {
  function showDemo() {
    clearClientSession();
    // 서버 컴포넌트가 쿠키 없는 상태로 다시 렌더되도록 전체 이동
    window.location.assign("/dashboard");
  }

  return (
    <section className="space-y-3 px-5 py-6">
      <div className="rounded-2xl border border-warn/40 bg-ink-900 p-5">
        <p className="text-base font-bold text-ink-100">{title}</p>
        <p className="mt-2 text-sm leading-relaxed text-ink-300">{detail}</p>
      </div>

      <Link
        href="/upload"
        className="flex w-full items-center justify-center rounded-xl border border-ink-600 bg-ink-800 py-4 text-sm font-semibold text-ink-100 transition-colors hover:bg-ink-700"
      >
        다른 파일 올리기 →
      </Link>
      <button
        type="button"
        onClick={showDemo}
        className="flex w-full items-center justify-center rounded-xl border border-ink-700 py-3.5 text-sm font-semibold text-ink-300 transition-colors hover:bg-ink-800"
      >
        데모로 보기
      </button>
    </section>
  );
}
