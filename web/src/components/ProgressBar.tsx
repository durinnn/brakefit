import { clamp } from "@/lib/format";

type Tone = "risk" | "safe" | "neutral" | "warn";

const FILL: Record<Tone, string> = {
  risk: "bg-risk",
  safe: "bg-safe",
  warn: "bg-warn",
  neutral: "bg-ink-300",
};

interface ProgressBarProps {
  /** 0~100 */
  value: number;
  tone?: Tone;
  /** 눈금(25/50/75) 표시 여부 */
  showTicks?: boolean;
  className?: string;
}

/** 0~100 점수를 나타내는 가로 프로그레스 바. */
export default function ProgressBar({
  value,
  tone = "neutral",
  showTicks = true,
  className = "",
}: ProgressBarProps) {
  const pct = clamp(value);

  return (
    <div
      className={`relative h-2.5 w-full overflow-hidden rounded-full bg-ink-700 ${className}`}
      role="meter"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={`h-full rounded-full transition-[width] duration-500 ${FILL[tone]}`}
        style={{ width: `${pct}%` }}
      />
      {showTicks
        ? [25, 50, 75].map((tick) => (
            <span
              key={tick}
              className="absolute top-0 h-full w-px bg-ink-950/60"
              style={{ left: `${tick}%` }}
            />
          ))
        : null}
    </div>
  );
}
