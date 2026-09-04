import ArcGauge from "@/components/ArcGauge";
import WaterfallChart from "@/components/WaterfallChart";
import WarningBox from "@/components/WarningBox";
import InterventionActions from "@/components/InterventionActions";
import { getInterventionReport } from "@/lib/api";
import { formatWon } from "@/lib/format";

const LEVEL_TONE = {
  LOW: "safe",
  MEDIUM: "warn",
  HIGH: "risk",
} as const;

const LEVEL_LABEL = {
  LOW: "낮음",
  MEDIUM: "주의",
  HIGH: "매우 위험",
} as const;

export default async function TradePage() {
  const report = await getInterventionReport();
  const { order } = report;
  const tone = LEVEL_TONE[report.riskLevel];
  const amount = order.price * order.quantity;

  return (
    <>
      {/* 상단: 개입 대상 주문 요약 */}
      <header className="border-b border-ink-800 px-5 pb-4 pt-8">
        <p className="label">주문 실행 직전</p>
        <div className="mt-3 flex items-baseline justify-between">
          <div>
            <h1 className="text-xl font-bold text-ink-100">{order.name}</h1>
            <p className="tabular mt-0.5 text-xs text-ink-500">
              {order.ticker}
            </p>
          </div>
          <p className="tabular text-lg font-bold text-risk">
            +{order.changeRate}%
          </p>
        </div>
        <div className="tabular mt-4 flex justify-between rounded-xl bg-ink-900 px-4 py-3 text-sm">
          <span className="text-ink-400">
            {order.side === "BUY" ? "매수" : "매도"} {order.quantity}주 ·{" "}
            {order.price.toLocaleString("ko-KR")}원
          </span>
          <span className="font-semibold text-ink-100">
            {formatWon(amount)}
          </span>
        </div>
      </header>

      {/* 상단: 위험 게이지 크게 노출 */}
      <section className="flex flex-col items-center border-b border-ink-800 px-5 py-8">
        <ArcGauge
          value={report.riskScore}
          tone={tone}
          caption={`이 거래의 위험도 · ${LEVEL_LABEL[report.riskLevel]}`}
          size={260}
        />
      </section>

      {/* 중단: 기여도 워터폴 */}
      <section className="border-b border-ink-800 px-5 py-6">
        <h2 className="label">위험 점수는 이렇게 계산됐습니다</h2>
        <div className="mt-4">
          <WaterfallChart
            baseScore={report.baseScore}
            contributions={report.contributions}
            total={report.riskScore}
          />
        </div>
      </section>

      {/* 하단: 붉은색 경고 박스 + 액션 */}
      <section className="space-y-5 px-5 py-6">
        <WarningBox warning={report.warning} />
        <InterventionActions
          suggestions={report.suggestions}
          riskScore={report.riskScore}
        />
      </section>
    </>
  );
}
