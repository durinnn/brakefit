"use client";

import Link from "next/link";
import { useEffect } from "react";

interface ErrorPageProps {
  error: Error & { digest?: string };
  reset: () => void;
}

/**
 * 라우트 세그먼트 공통 에러 화면.
 *
 * 서버 컴포넌트가 FastAPI 를 fetch 하다 실패하면(Render 콜드스타트·재시작 등)
 * Next 기본 화면은 영어 "Application error" 만 띄운다 — 데모 중에 그 화면이
 * 뜨면 설명할 방법이 없으므로 한국어 안내와 재시도 버튼으로 대체한다.
 */
export default function ErrorPage({ error, reset }: ErrorPageProps) {
  useEffect(() => {
    // 원인은 삼키지 않는다 — 화면 문구는 뭉뚱그려도 콘솔에는 남겨야 디버깅이 된다
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center px-5 text-center">
      <p className="label">연결 오류</p>
      <h1 className="mt-3 text-xl font-bold leading-snug text-ink-100">
        서버 연결에 실패했습니다.
        <br />
        잠시 후 다시 시도해 주세요.
      </h1>
      <p className="mt-3 max-w-[300px] text-sm leading-relaxed text-ink-400">
        진단 서버가 응답하지 않고 있습니다. 네트워크 상태를 확인한 뒤 아래
        버튼으로 다시 시도할 수 있습니다.
      </p>

      <div className="mt-8 flex w-full max-w-[280px] flex-col gap-3">
        <button
          type="button"
          onClick={reset}
          className="w-full rounded-xl border border-ink-600 bg-ink-800 py-3.5 text-sm font-semibold text-ink-100 transition-colors hover:bg-ink-700"
        >
          다시 시도
        </button>
        <Link
          href="/"
          className="w-full rounded-xl py-3 text-sm text-ink-400 transition-colors hover:text-ink-200"
        >
          홈으로 돌아가기
        </Link>
      </div>

      {error.digest ? (
        <p className="tabular mt-6 text-[11px] text-ink-600">
          오류 코드 {error.digest}
        </p>
      ) : null}
    </div>
  );
}
