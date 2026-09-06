import Link from "next/link";
import PageHeader from "@/components/PageHeader";
import AnalysisUnavailable from "@/components/AnalysisUnavailable";
import ArcGauge from "@/components/ArcGauge";
import BiasMetricCard from "@/components/BiasMetricCard";
import DataSourceBadge from "@/components/DataSourceBadge";
import SynthDisclaimer from "@/components/SynthDisclaimer";
import WarningBanner from "@/components/WarningBanner";
import { getDiagnosisReport } from "@/lib/api";
import { getServerSession } from "@/lib/session.server";

const GRADE_TONE = {
  안정: "safe",
  주의: "warn",
  위험: "risk",
} as const;

export default async function DashboardPage() {
  const session = await getServerSession();
  const { data: report, source, sessionExpired } = await getDiagnosisReport(session);

  /**
   * 분석 대상 거래가 0건이면 점수·게이지·지표 카드를 아예 그리지 않는다.
   * 이때 서버가 주는 값은 전부 0 이라, 그대로 그리면 "안정 0점"으로 보여서
   * 거래를 한 건도 못 읽은 상태가 정상 진단과 구분되지 않는다.
   */
  if (report.overallGrade === "분석 불가") {
    return (
      <>
        <DataSourceBadge
          source={source}
          tradeCount={report.totalTrades}
          sessionExpired={sessionExpired}
        />
        <WarningBanner warnings={report.warnings ?? []} />
        <PageHeader
          eyebrow="편향 건강검진"
          title="진단을 만들지 못했습니다"
          caption={report.periodLabel}
        />
        <AnalysisUnavailable
          title="분석 가능한 거래가 없습니다"
          detail={`업로드한 파일에서 국내 주식 체결 ${report.totalTrades.toLocaleString("ko-KR")}건이 종목코드 미해결로 제외됐습니다. 다른 파일을 올리거나 데모 페르소나로 먼저 둘러보세요.`}
        />
        <SynthDisclaimer source={source} />
      </>
    );
  }

  const tone = GRADE_TONE[report.overallGrade];

  return (
    <>
      <DataSourceBadge
        source={source}
        tradeCount={report.totalTrades}
        sessionExpired={sessionExpired}
      />

      {/* 진단 숫자보다 먼저 보여야 한다 — 어떤 데이터로 계산된 점수인지가 먼저다 */}
      <WarningBanner warnings={report.warnings ?? []} />

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

        {/*
          백분위 기준선은 업로드 세션이든 데모 페르소나든 항상 합성 표본이다.
          SynthDisclaimer 는 source === "persona" 일 때만 뜨므로 업로드 세션에서는
          이 사실이 어디에도 안 남는다 — 그래서 지표 카드 바로 아래에 항상 붙인다.
        */}
        <p className="pt-1 text-xs leading-relaxed text-ink-600">
          * 합성 페르소나 20개 표본 기준이며 실제 투자자 분포가 아닙니다.
        </p>
      </section>

      <section className="px-5 pb-8">
        <Link
          href="/backtest"
          className="flex w-full items-center justify-center rounded-xl border border-ink-600 bg-ink-800 py-4 text-sm font-semibold text-ink-100 transition-colors hover:bg-ink-700"
        >
          이 습관을 막았다면 얼마를 지켰을까? →
        </Link>
      </section>

      <SynthDisclaimer source={source} />
    </>
  );
}
