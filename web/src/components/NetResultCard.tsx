import { formatWon } from "@/lib/format";

interface NetResultCardProps {
  netBenefit: number;
  netBenefitRate: number;
  interventionCount: number;
  hitRate: number;
}

/**
 * 개입의 순효과(회피 손실 − 놓친 이익)를 화면에서 가장 크게 강조하는 카드.
 *
 * 라벨이 "방어한 순수익" 이었는데, 이 값은 음수도 정상 결과다(§7 — 페르소나 5종
 * 전부 순손실). 음수 금액 위에 "방어한 순수익" 이 붙으면 "마이너스만큼 방어했다" 는
 * 말이 안 되는 문장이 된다. 부호와 무관하게 성립하는 "개입의 순효과" 로 바꿨다.
 */
export default function NetResultCard({
  netBenefit,
  netBenefitRate,
  interventionCount,
  hitRate,
}: NetResultCardProps) {
  const isPositive = netBenefit >= 0;
  const tone = isPositive ? "safe" : "risk";

  return (
    <section
      className={`rounded-2xl border p-6 text-center ${
        isPositive
          ? "border-safe/40 bg-gradient-to-b from-safe-dim/70 to-ink-900"
          : "border-risk/40 bg-gradient-to-b from-risk-dim/70 to-ink-900"
      }`}
    >
      <p
        className={`text-xs font-semibold uppercase tracking-[0.2em] ${
          isPositive ? "text-safe-soft" : "text-risk-soft"
        }`}
      >
        Net · 개입의 순효과
      </p>

      <p
        className={`tabular mt-4 text-[44px] font-extrabold leading-none text-${tone}`}
      >
        {formatWon(netBenefit)}
      </p>

      <p className="tabular mt-3 text-sm text-ink-300">
        투입 원금 대비{" "}
        <span className={`font-semibold text-${tone}-soft`}>
          {netBenefitRate >= 0 ? "+" : ""}
          {netBenefitRate}%
        </span>
      </p>

      <div className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-xl bg-ink-700">
        <div className="bg-ink-900 px-3 py-3">
          <p className="text-[11px] text-ink-400">개입 건수</p>
          <p className="tabular mt-1 text-lg font-bold text-ink-100">
            {interventionCount}건
          </p>
        </div>
        <div className="bg-ink-900 px-3 py-3">
          <p className="text-[11px] text-ink-400">개입 적중률</p>
          <p className="tabular mt-1 text-lg font-bold text-ink-100">
            {hitRate}%
          </p>
        </div>
      </div>
    </section>
  );
}
