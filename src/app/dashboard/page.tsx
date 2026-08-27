import Link from "next/link";
import PageHeader from "@/components/PageHeader";
import ArcGauge from "@/components/ArcGauge";
import BiasMetricCard from "@/components/BiasMetricCard";
import { getDiagnosisReport } from "@/lib/mockData";

const GRADE_TONE = {
  안정: "safe",
  주의: "warn",
  위험: "risk",
} as const;

export default async function DashboardPage() {
  const report = await getDiagnosisReport();
  const tone = GRADE_TONE[report.overallGrade];

  return (
    <>
      <PageHeader
        eyebrow="편향 건강검진"
        title="당신의 매매 습관 진단 결과"
        caption={`${report.periodLabel} · 총 ${report.totalTrades.toLocaleString("ko-KR")}건 분석`}
      />

      <section className="flex flex-col items-center border-b border-ink-800 px-5 py-8">
        <ArcGauge
          value={report.overallScore}
          tone={tone}
          caption={`종합 편향 · ${report.overallGrade}`}
        />
        <p className="mt-4 max-w-[300px] text-center text-sm leading-relaxed text-ink-400">
          점수가 높을수록 감정적 매매 비중이 큽니다. 아래 3개 지표에서 어떤
          습관이 손실을 만들고 있는지 확인하세요.
        </p>
      </section>

      <section className="space-y-3 px-5 py-6">
        <h2 className="label">3대 편향 지표</h2>
        {report.metrics.map((metric) => (
          <BiasMetricCard key={metric.key} metric={metric} />
        ))}
      </section>

      <section className="px-5 pb-8">
        <Link
          href="/backtest"
          className="flex w-full items-center justify-center rounded-xl border border-ink-600 bg-ink-800 py-4 text-sm font-semibold text-ink-100 transition-colors hover:bg-ink-700"
        >
          이 습관을 막았다면 얼마를 지켰을까? →
        </Link>
      </section>
    </>
  );
}
