import { clamp } from "@/lib/format";

type Tone = "risk" | "safe" | "warn" | "neutral";

const STROKE: Record<Tone, string> = {
  risk: "#E0484A",
  safe: "#2FB6A0",
  warn: "#E0A030",
  neutral: "#98A1AF",
};

interface ArcGaugeProps {
  /** 0~100 */
  value: number;
  tone?: Tone;
  /** 게이지 하단 라벨 (예: HIGH RISK) */
  caption?: string;
  size?: number;
}

/**
 * 반원형 게이지. 위험 점수를 크게 노출하기 위한 컴포넌트.
 * 외부 차트 라이브러리 없이 SVG stroke-dasharray 로만 구현.
 */
export default function ArcGauge({
  value,
  tone = "risk",
  caption,
  size = 240,
}: ArcGaugeProps) {
  const pct = clamp(value);
  const radius = 100;
  const circumference = Math.PI * radius; // 반원 길이
  const filled = (pct / 100) * circumference;

  return (
    <div className="flex flex-col items-center" style={{ width: size }}>
      <svg
        viewBox="0 0 240 132"
        width={size}
        height={size * 0.55}
        role="meter"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        {/* 트랙 */}
        <path
          d="M 20 120 A 100 100 0 0 1 220 120"
          fill="none"
          stroke="#232830"
          strokeWidth="18"
          strokeLinecap="round"
        />
        {/* 채워진 구간 */}
        <path
          d="M 20 120 A 100 100 0 0 1 220 120"
          fill="none"
          stroke={STROKE[tone]}
          strokeWidth="18"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
        />
        <text
          x="120"
          y="104"
          textAnchor="middle"
          className="tabular"
          fill="#E6E9ED"
          fontSize="52"
          fontWeight="700"
        >
          {pct}
        </text>
        <text
          x="120"
          y="126"
          textAnchor="middle"
          fill="#6B7484"
          fontSize="13"
          letterSpacing="1.5"
        >
          / 100
        </text>
      </svg>
      {caption ? (
        <p
          className="mt-1 text-sm font-semibold tracking-wide"
          style={{ color: STROKE[tone] }}
        >
          {caption}
        </p>
      ) : null}
    </div>
  );
}
