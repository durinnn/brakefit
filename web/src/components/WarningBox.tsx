import { BIAS_LABEL } from "@/lib/bias";
import type { BiasKey, PatternWarning } from "@/lib/types";

/**
 * averageReturn 이 실제로 무엇의 평균인지는 지배 편향마다 다르다
 * (api/service.py `_average_return` → 각 metric 의 evidence.return_pct).
 * - 추격매수: 매수 시점의 전일 종가 대비 급등률
 * - 물타기: 추가매수 시점의 평가손익률
 * - 처분효과: 근거로 뽑힌 episode 의 손익률(실현 또는 현재 미실현)
 * 셋 다 "그 이후 실제 수익률"이 아니므로 "평균 수익률"로 뭉뚱그리면 거짓 표기가 된다.
 *
 * 지배 편향은 여기서 추정하지 않고 서버 판정(dominantKey)을 그대로 받는다 —
 * 이유는 lib/bias.ts 주석 참조(기여 최댓값으로 되짚으면 규칙·라벨이 바뀔 때
 * 프론트만 조용히 틀린다).
 */
const AVERAGE_RETURN_LABEL: Record<BiasKey, string> = {
  chasing: "매수 시점 평균 급등률",
  averaging_down: "매수 시점 평균 평가손익률",
  disposition: "사례 평균 손익률",
};

/** 과거 패턴 기반 붉은색 경고 박스. 개입 화면의 최종 설득 장치. */
export default function WarningBox({
  warning,
  dominantKey = null,
}: {
  warning: PatternWarning;
  /**
   * 이번 판정을 주도한 편향(서버 판정). 배지와 평균값 레이블에 함께 쓴다.
   * 모르면 배지를 안 그리고 레이블도 중립 문구로 둔다.
   */
  dominantKey?: BiasKey | null;
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
        {dominantKey ? (
          <span className="rounded-full bg-risk/20 px-2 py-0.5 text-[11px] font-semibold text-risk-soft">
            {BIAS_LABEL[dominantKey]}
          </span>
        ) : null}
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
            {dominantKey ? AVERAGE_RETURN_LABEL[dominantKey] : "평균 손익률"}
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
