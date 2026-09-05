"use client";

import { useState } from "react";

export type InterventionDecision = "stopped" | "forced";

interface InterventionActionsProps {
  suggestions: string[];
  riskScore: number;
  /**
   * 결정이 내려졌을 때 부모에게 알린다. 넘기면 아래 결과 패널을 이 컴포넌트가
   * 직접 띄우지 않는다 — /trade 는 결정 즉시 개입 모달을 닫고 주문 폼 쪽에서
   * 결과를 보여주기 때문에, 사라질 패널을 한 프레임 그리는 걸 피한다.
   */
  onDecision?: (decision: InterventionDecision) => void;
  /** 강행 확인 버튼 문구. 매도 주문이면 "그래도 매도" 처럼 바꿔 넘긴다. */
  confirmLabel?: string;
}

/**
 * 개입 화면 하단 액션. 브레이크의 핵심 UX:
 * '멈추기'를 기본값(강조)으로 두고, 강행은 2단계 확인을 거치게 한다.
 */
export default function InterventionActions({
  suggestions,
  riskScore,
  onDecision,
  confirmLabel = "그래도 매수",
}: InterventionActionsProps) {
  const [confirming, setConfirming] = useState(false);
  const [decision, setDecision] = useState<"none" | InterventionDecision>(
    "none",
  );

  function decide(next: InterventionDecision) {
    if (onDecision) {
      onDecision(next);
      return;
    }
    setDecision(next);
  }

  if (decision === "stopped") {
    return (
      <div className="rounded-2xl border border-safe/40 bg-safe-dim/50 p-5 text-center">
        <p className="text-base font-bold text-safe-soft">주문을 멈췄습니다</p>
        {/* 재알림 스케줄러가 없으므로 "24시간 뒤 알려드릴게요" 같은 약속은 하지 않는다. */}
        <p className="mt-2 text-sm text-ink-300">내일 다시 판단해 보세요.</p>
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
        {/* 결정은 이 컴포넌트의 로컬 state 일 뿐 서버에 남지 않는다 —
            "다음 진단에 반영" 같은 미구현 기능을 문구로 약속하지 않는다. */}
        <p className="mt-2 text-sm text-ink-400">
          경고를 확인하고 진행한 것으로 이번 세션에 기록됩니다.
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
        onClick={() => decide("stopped")}
        className="w-full rounded-xl bg-ink-100 py-4 text-base font-bold text-ink-950 transition-opacity hover:opacity-90"
      >
        멈추기
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
              onClick={() => decide("forced")}
              className="flex-1 rounded-lg bg-risk py-2.5 text-sm font-semibold text-ink-950"
            >
              {confirmLabel}
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
