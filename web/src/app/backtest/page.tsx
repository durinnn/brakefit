import PageHeader from "@/components/PageHeader";
import ComparisonBar from "@/components/ComparisonBar";
import NetResultCard from "@/components/NetResultCard";
import { getBacktestResult } from "@/lib/api";
import { getServerSession } from "@/lib/session.server";
import { formatWon } from "@/lib/format";
import type { BiasKey } from "@/lib/types";

const BIAS_LABEL: Record<BiasKey, string> = {
  disposition: "처분효과",
  averaging_down: "물타기",
  chasing: "추격매수",
};

export default async function BacktestPage() {
  const session = await getServerSession();
  const { data: result } = await getBacktestResult(session);

  return (
    <>
      <PageHeader
        eyebrow="백테스트 증명"
        title="브레이크를 걸었다면?"
        caption={`${result.periodLabel} · 개입 대상 ${result.interventionCount}건`}
      />

      {/* 1. 최종 순수익을 가장 크게 강조 */}
      <section className="px-5 py-6">
        <NetResultCard
          netBenefit={result.netBenefit}
          netBenefitRate={result.netBenefitRate}
          interventionCount={result.interventionCount}
          hitRate={result.hitRate}
        />
      </section>

      {/* 2. 회피한 손실 vs 놓친 이익 나란히 비교 */}
      <section className="px-5 pb-6">
        <h2 className="label mb-3">순수익은 이렇게 나왔습니다</h2>
        <ComparisonBar
          avoidedLoss={result.avoidedLoss}
          missedGain={result.missedGain}
        />
        <p className="tabular mt-3 text-center text-sm text-ink-400">
          {formatWon(result.avoidedLoss)} −{" "}
          {formatWon(result.missedGain)} ={" "}
          <span className="font-bold text-safe">
            {formatWon(result.netBenefit)}
          </span>
        </p>
      </section>

      {/* 3. 개별 개입 사례 */}
      <section className="px-5 pb-8">
        <h2 className="label mb-3">주요 개입 사례</h2>
        <ul className="divide-y divide-ink-800 overflow-hidden rounded-2xl border border-ink-700 bg-ink-900">
          {result.cases.map((item) => {
            const positive = item.impact >= 0;
            return (
              <li
                key={`${item.date}-${item.name}`}
                className="flex items-center justify-between px-4 py-3.5"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink-100">
                    {item.name}
                  </p>
                  <p className="tabular mt-0.5 text-xs text-ink-500">
                    {item.date} · {BIAS_LABEL[item.biasKey]}
                  </p>
                </div>
                <div className="pl-3 text-right">
                  <p
                    className={`tabular text-sm font-bold ${
                      positive ? "text-safe" : "text-ink-400"
                    }`}
                  >
                    {positive ? "+" : "−"}
                    {Math.abs(item.impact).toLocaleString("ko-KR")}원
                  </p>
                  <p className="text-[11px] text-ink-600">
                    {positive ? "손실 회피" : "이익 기회 상실"}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>

        <p className="mt-4 text-xs leading-relaxed text-ink-600">
          * 과거 체결 데이터를 기준으로 한 시뮬레이션 결과이며, 미래 수익을
          보장하지 않습니다.
        </p>
      </section>
    </>
  );
}
