"use client";

import { useRef, useState } from "react";
import PageHeader from "@/components/PageHeader";
import { uploadTrades } from "@/lib/api";
import { writeClientSession } from "@/lib/session";
import type { UploadResult } from "@/lib/types";

const ACCEPT = ".csv,.xlsx,.xls";

const SOURCE_LABEL: Record<UploadResult["source"], string> = {
  kb_export: "KB증권 거래내역",
  standard_csv: "표준 CSV",
};

export default function UploadPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);

  async function handleUpload() {
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    try {
      const uploaded = await uploadTrades(file);
      writeClientSession(uploaded.sessionId);
      setResult(uploaded);
    } catch (e) {
      setError(e instanceof Error ? e.message : "업로드에 실패했습니다");
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setFile(null);
    setResult(null);
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  /* 진단 화면은 서버 컴포넌트라 쿠키를 렌더 시점에 읽는다. 방금 심은 쿠키가 확실히
     반영되도록 클라이언트 라우팅 대신 전체 이동을 쓴다(데모 중 캐시 사고 방지). */
  function goToDashboard() {
    window.location.assign("/dashboard");
  }

  return (
    <>
      <PageHeader
        eyebrow="거래내역 업로드"
        title="내 거래로 진단받기"
        caption="증권사에서 내려받은 거래내역 파일을 올리면 데모 페르소나 대신 내 데이터로 분석합니다."
      />

      {result ? (
        <section className="space-y-4 px-5 py-6">
          <div className="rounded-2xl border border-safe/40 bg-safe-dim/50 p-5">
            <p className="text-base font-bold text-safe-soft">
              업로드가 끝났습니다
            </p>
            <p className="tabular mt-2 text-sm text-ink-200">
              거래 {result.tradeCount.toLocaleString("ko-KR")}건 · {result.period}
            </p>
            <p className="mt-1 text-xs text-ink-400">
              {SOURCE_LABEL[result.source]} 형식으로 인식
              {result.skippedCount > 0
                ? ` · ${result.skippedCount.toLocaleString("ko-KR")}행 제외`
                : ""}
            </p>
          </div>

          {result.warnings.length > 0 ? (
            <div className="rounded-2xl border border-warn/40 bg-ink-900 p-4">
              <p className="label text-warn">확인이 필요한 항목</p>
              <ul className="mt-2 space-y-1.5">
                {result.warnings.map((item) => (
                  <li
                    key={item}
                    className="flex items-start gap-2 text-sm leading-relaxed text-ink-300"
                  >
                    <span className="mt-0.5 text-warn">!</span>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <button
            type="button"
            onClick={goToDashboard}
            className="w-full rounded-xl bg-ink-100 py-4 text-base font-bold text-ink-950 transition-opacity hover:opacity-90"
          >
            진단 보기
          </button>
          <button
            type="button"
            onClick={reset}
            className="w-full py-2 text-sm text-ink-500 underline underline-offset-4"
          >
            다른 파일 올리기
          </button>
        </section>
      ) : (
        <section className="space-y-4 px-5 py-6">
          <label
            htmlFor="trade-file"
            className="flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-ink-600 bg-ink-900 px-5 py-10 text-center transition-colors hover:border-ink-500"
          >
            <span className="text-sm font-semibold text-ink-100">
              {file ? file.name : "파일 선택"}
            </span>
            <span className="tabular mt-1.5 text-xs text-ink-500">
              {file
                ? `${(file.size / 1024).toFixed(0)} KB`
                : "CSV · XLSX · XLS"}
            </span>
          </label>
          <input
            ref={inputRef}
            id="trade-file"
            type="file"
            accept={ACCEPT}
            className="sr-only"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setError(null);
            }}
          />

          {error ? (
            <div className="rounded-xl border border-risk/40 bg-risk-dim/40 p-4">
              <p className="text-sm font-semibold text-risk-soft">
                업로드 실패
              </p>
              <p className="mt-1 text-sm leading-relaxed text-ink-300">
                {error}
              </p>
            </div>
          ) : null}

          <button
            type="button"
            onClick={handleUpload}
            disabled={!file || busy}
            className="w-full rounded-xl bg-ink-100 py-4 text-base font-bold text-ink-950 transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "분석 중…" : "업로드하고 진단하기"}
          </button>

          <p className="text-xs leading-relaxed text-ink-600">
            * 국내 주식 체결 내역만 분석합니다. 해외 주식·파생 행은 건너뜁니다.
            <br />* 업로드하지 않아도 데모 페르소나로 모든 화면을 볼 수 있습니다.
          </p>
        </section>
      )}
    </>
  );
}
