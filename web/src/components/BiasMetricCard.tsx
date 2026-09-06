import type { BiasMetric } from "@/lib/types";
import { formatScore, formatSigned } from "@/lib/format";
import ProgressBar from "./ProgressBar";

function toneOf(score: number): "safe" | "warn" | "risk" {
  if (score < 40) return "safe";
  if (score < 70) return "warn";
  return "risk";
}

export default function BiasMetricCard({ metric }: { metric: BiasMetric }) {
  const tone = toneOf(metric.score);
  const toneText =
    tone === "risk" ? "text-risk" : tone === "warn" ? "text-warn" : "text-safe";

  return (
    <article className="card">
      <div className="flex items-baseline justify-between">
        <h3 className="text-base font-semibold text-ink-100">{metric.name}</h3>
        <div className="flex items-baseline gap-1.5">
          <span className={`tabular text-2xl font-bold ${toneText}`}>
            {formatScore(metric.score)}
          </span>
          <span className="text-xs text-ink-500">/ 100</span>
        </div>
      </div>

      <ProgressBar value={metric.score} tone={tone} className="mt-3" />

      {/* 배지 문구가 "합성 기준선 상위 N%" 로 길어져서 360px 폭에서는 한 줄에 못 들어간다.
          배지 안이 어중간하게 끊기지 않도록 배지는 nowrap 으로 두고, 줄바꿈은 행에서 받는다 */}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink-400">
        <span className="rounded-md bg-ink-800 px-2 py-1 tabular whitespace-nowrap">
          {/* API 의 percentile 은 "기준선 표본 중 이 점수 이하 비율" — 편향이 심할수록 커진다.
              "상위 N%" 는 반대 방향이라 100 − p 로 뒤집어 표기.
              기준선이 합성 페르소나 표본이라는 걸 배지에 박아둔다 — 실사용자 분포로 오해되면 안 된다 */}
          합성 기준선 상위 {Math.round((100 - metric.percentile) * 10) / 10}%
        </span>
        <span className="tabular whitespace-nowrap">{metric.sampleCount}건 기준</span>
        {metric.delta !== null ? (
          <span
            className={`tabular ml-auto ${
              metric.delta > 0 ? "text-risk-soft" : "text-safe-soft"
            }`}
          >
            직전 대비 {formatSigned(metric.delta)}
          </span>
        ) : null}
      </div>

      <p className="mt-3 border-t border-ink-800 pt-3 text-sm leading-relaxed text-ink-300">
        {metric.summary}
      </p>
    </article>
  );
}
