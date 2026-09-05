import type { PatternWarning, RiskContribution } from "@/lib/types";

/**
 * averageReturn 이 실제로 무엇의 평균인지는 지배 편향마다 다르다
 * (api/service.py `_average_return` → 각 metric 의 evidence.return_pct).
 * - 추격매수: 매수 시점의 전일 종가 대비 급등률
 * - 물타기: 추가매수 시점의 평가손익률
 * - 처분효과: 근거로 뽑힌 episode 의 손익률(실현 또는 현재 미실현)
 * 셋 다 "그 이후 실제 수익률"이 아니므로 "평균 수익률"로 뭉뚱그리면 거짓 표기가 된다.
 */
const AVERAGE_RETURN_LABEL: Record<string, string> = {
  추격매수: "매수 시점 평균 급등률",
  물타기: "매수 시점 평균 평가손익률",
  처분효과: "사례 평균 손익률",
};

/**
 * 지배 편향 = 기여 점수가 가장 큰 룰. 백엔드는 "발동한 룰 중 최대"를 쓰지만
 * 응답의 RiskContribution 에 triggered 가 없다 — 발동하지 않은 룰의 기여는
 * 항상 0 점이라(core/rules/*_rule.py) 최대값을 고르면 실질적으로 같은 결과다.
 */
function averageReturnLabel(contributions?: RiskContribution[]): string {
  if (!contributions?.length) return "평균 손익률";
  const dominant = contributions.reduce((a, b) => (b.value > a.value ? b : a));
  if (dominant.value <= 0) return "평균 손익률";
  return AVERAGE_RETURN_LABEL[dominant.label] ?? "평균 손익률";
}

/** 과거 패턴 기반 붉은색 경고 박스. 개입 화면의 최종 설득 장치. */
export default function WarningBox({
  warning,
  contributions,
}: {
  warning: PatternWarning;
  /** 평균값 레이블을 지배 편향에 맞추기 위해 받는다. 없으면 중립 레이블. */
  contributions?: RiskContribution[];
}) {
  return (
    <section
      role="alert"
      className="rounded-2xl border border-risk/50 bg-risk-dim/60 p-5"
    >
      <div className="flex items-center gap-2">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-risk text-xs font-bold text-ink-950">
          !
        </span>
        <span className="text-xs font-semibold uppercase tracking-wider text-risk-soft">
          과거 패턴 경고
        </span>
      </div>

      <p className="mt-3 text-lg font-bold leading-snug text-risk-soft">
        {warning.headline}
      </p>

      <div className="mt-4 flex gap-3">
        <div className="flex-1 rounded-xl bg-ink-950/50 px-3 py-2.5">
          <p className="text-[11px] text-ink-400">유사 사례</p>
          <p className="tabular mt-0.5 text-xl font-bold text-ink-100">
            {warning.caseCount}건
          </p>
        </div>
        <div className="flex-1 rounded-xl bg-ink-950/50 px-3 py-2.5">
          <p className="text-[11px] text-ink-400">
            {averageReturnLabel(contributions)}
          </p>
          <p className="tabular mt-0.5 text-xl font-bold text-risk">
            {warning.averageReturn}%
          </p>
        </div>
      </div>

      <p className="mt-4 text-sm leading-relaxed text-ink-300">
        {warning.description}
      </p>
    </section>
  );
}
