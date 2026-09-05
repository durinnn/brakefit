import { BIAS_LABEL } from "@/lib/bias";
import type { BiasKey, PatternWarning } from "@/lib/types";

/** 과거 패턴 기반 붉은색 경고 박스. 개입 화면의 최종 설득 장치. */
export default function WarningBox({
  warning,
  dominantKey = null,
}: {
  warning: PatternWarning;
  /** 이번 판정을 주도한 편향(서버 판정). 모르면 배지를 안 그린다. */
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
          <p className="text-[11px] text-ink-400">평균 수익률</p>
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
