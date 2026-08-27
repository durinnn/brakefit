import { formatWon } from "@/lib/format";

interface NetResultCardProps {
  netBenefit: number;
  netBenefitRate: number;
  interventionCount: number;
  hitRate: number;
}

/** 최종 방어 순수익을 화면에서 가장 크게 강조하는 카드. */
export default function NetResultCard({
  netBenefit,
  netBenefitRate,
  interventionCount,
  hitRate,
}: NetResultCardProps) {
  return (
    <section className="rounded-2xl border border-safe/40 bg-gradient-to-b from-safe-dim/70 to-ink-900 p-6 text-center">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-safe-soft">
        Net · 방어한 순수익
      </p>

      <p className="tabular mt-4 text-[44px] font-extrabold leading-none text-safe">
        +{formatWon(netBenefit)}
      </p>

      <p className="tabular mt-3 text-sm text-ink-300">
        투입 원금 대비{" "}
        <span className="font-semibold text-safe-soft">+{netBenefitRate}%</span>
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
