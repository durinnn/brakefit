import type { RiskContribution } from "@/lib/types";
import { clamp, formatSigned } from "@/lib/format";

interface WaterfallChartProps {
  /** 워터폴 시작점 (기준 위험도) */
  baseScore: number;
  contributions: RiskContribution[];
  /** 최종 위험 점수 */
  total: number;
}

type Row = {
  label: string;
  detail?: string;
  /** 막대 시작 위치 (0~100) */
  start: number;
  /** 막대 길이 (0~100) */
  length: number;
  kind: "base" | "increase" | "decrease" | "total";
  valueLabel: string;
};

const BAR_STYLE: Record<Row["kind"], string> = {
  base: "bg-ink-500",
  increase: "bg-risk",
  decrease: "bg-safe",
  total: "bg-ink-100",
};

/**
 * 위험 점수 산출 근거를 보여주는 기여도 워터폴 차트.
 * 차트 라이브러리 없이 CSS 절대 위치 막대로 구현했다.
 */
export default function WaterfallChart({
  baseScore,
  contributions,
  total,
}: WaterfallChartProps) {
  const rows: Row[] = [];

  rows.push({
    label: "기준 위험도",
    start: 0,
    length: clamp(baseScore),
    kind: "base",
    valueLabel: String(baseScore),
  });

  let cursor = baseScore;
  for (const item of contributions) {
    const next = cursor + item.value;
    rows.push({
      label: item.label,
      detail: item.detail,
      start: clamp(Math.min(cursor, next)),
      length: clamp(Math.abs(item.value)),
      kind: item.value >= 0 ? "increase" : "decrease",
      valueLabel: formatSigned(item.value),
    });
    cursor = next;
  }

  rows.push({
    label: "최종 위험 점수",
    start: 0,
    length: clamp(total),
    kind: "total",
    valueLabel: String(total),
  });

  return (
    <div className="space-y-3">
      {rows.map((row, index) => {
        const isTotal = row.kind === "total";
        return (
          <div
            key={`${row.label}-${index}`}
            className={isTotal ? "border-t border-ink-700 pt-3" : undefined}
          >
            <div className="flex items-baseline justify-between text-sm">
              <span
                className={
                  isTotal
                    ? "font-semibold text-ink-100"
                    : "text-ink-300"
                }
              >
                {row.label}
              </span>
              <span
                className={[
                  "tabular font-semibold",
                  row.kind === "increase"
                    ? "text-risk-soft"
                    : row.kind === "decrease"
                      ? "text-safe-soft"
                      : "text-ink-100",
                ].join(" ")}
              >
                {row.valueLabel}
              </span>
            </div>

            <div className="relative mt-1.5 h-3 w-full rounded-sm bg-ink-800">
              <div
                className={`absolute top-0 h-full rounded-sm ${BAR_STYLE[row.kind]}`}
                style={{
                  left: `${row.start}%`,
                  width: `${Math.max(row.length, 1)}%`,
                }}
              />
            </div>

            {row.detail ? (
              <p className="mt-1 text-xs text-ink-500">{row.detail}</p>
            ) : null}
          </div>
        );
      })}

      <div className="flex justify-between pt-1 text-[11px] tabular text-ink-600">
        <span>0</span>
        <span>50</span>
        <span>100</span>
      </div>
    </div>
  );
}
