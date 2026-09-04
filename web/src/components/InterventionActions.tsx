"use client";

import { useState } from "react";

interface InterventionActionsProps {
  suggestions: string[];
  riskScore: number;
}

/**
 * 개입 화면 하단 액션. 브레이크의 핵심 UX:
 * '멈추기'를 기본값(강조)으로 두고, 강행은 2단계 확인을 거치게 한다.
 */
export default function InterventionActions({
  suggestions,
  riskScore,
}: InterventionActionsProps) {
  const [confirming, setConfirming] = useState(false);
  const [decision, setDecision] = useState<"none" | "stopped" | "forced">(
    "none",
  );

  if (decision === "stopped") {
    return (
      <div className="rounded-2xl border border-safe/40 bg-safe-dim/50 p-5 text-center">
        <p className="text-base font-bold text-safe-soft">주문을 멈췄습니다</p>
        <p className="mt-2 text-sm text-ink-300">
          24시간 뒤 같은 종목을 다시 검토할지 알려드릴게요.
        </p>
        <button
          type="button"
          onClick={() => setDecision("none")}
          className="mt-4 text-xs text-ink-500 underline"
        >
          되돌리기
        </button>
      </div>
    );
  }

  if (decision === "forced") {
    return (
      <div className="rounded-2xl border border-ink-600 bg-ink-800 p-5 text-center">
        <p className="text-base font-bold text-ink-100">주문이 접수되었습니다</p>
        <p className="mt-2 text-sm text-ink-400">
          이 거래는 &lsquo;경고 후 강행&rsquo;으로 기록되어 다음 진단에
          반영됩니다.
        </p>
        <button
          type="button"
          onClick={() => setDecision("none")}
          className="mt-4 text-xs text-ink-500 underline"
        >
          되돌리기
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <p className="label">대신 이렇게 해보세요</p>
        <ul className="mt-2 space-y-2">
          {suggestions.map((item) => (
            <li
              key={item}
              className="flex items-start gap-2 rounded-xl border border-ink-700 bg-ink-900 px-4 py-3 text-sm text-ink-200"
            >
              <span className="mt-0.5 text-safe">✓</span>
              {item}
            </li>
          ))}
        </ul>
      </div>

      <button
        type="button"
        onClick={() => setDecision("stopped")}
        className="w-full rounded-xl bg-ink-100 py-4 text-base font-bold text-ink-950 transition-opacity hover:opacity-90"
      >
        멈추기 · 24시간 뒤 다시 보기
      </button>

      {confirming ? (
        <div className="rounded-xl border border-risk/40 bg-risk-dim/40 p-4">
          <p className="text-sm font-semibold text-risk-soft">
            정말 이 주문을 진행하시겠습니까?
          </p>
          <p className="mt-1 text-xs text-ink-400">
            위험 점수 {riskScore}점 상태의 주문입니다.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="flex-1 rounded-lg border border-ink-600 py-2.5 text-sm text-ink-200"
            >
              취소
            </button>
            <button
              type="button"
              onClick={() => setDecision("forced")}
              className="flex-1 rounded-lg bg-risk py-2.5 text-sm font-semibold text-ink-950"
            >
              그래도 매수
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="w-full py-2 text-sm text-ink-500 underline underline-offset-4"
        >
          경고를 무시하고 주문 진행
        </button>
      )}
    </div>
  );
}
