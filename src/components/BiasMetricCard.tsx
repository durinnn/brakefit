import type { BiasMetric } from "@/lib/types";
import { formatSigned } from "@/lib/format";
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
            {metric.score}
          </span>
          <span className="text-xs text-ink-500">/ 100</span>
        </div>
      </div>

      <ProgressBar value={metric.score} tone={tone} className="mt-3" />

      <div className="mt-3 flex items-center gap-2 text-xs text-ink-400">
        <span className="rounded-md bg-ink-800 px-2 py-1 tabular">
          상위 {metric.percentile}%
        </span>
        <span className="tabular">{metric.sampleCount}건 기준</span>
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
