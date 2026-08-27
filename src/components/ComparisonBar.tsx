import { formatManwon } from "@/lib/format";

interface ComparisonBarProps {
  /** 회피한 손실 (양수) */
  avoidedLoss: number;
  /** 놓친 이익 (양수) */
  missedGain: number;
}

/** '회피한 손실'과 '놓친 이익'을 나란히 비교하는 대칭 막대. */
export default function ComparisonBar({
  avoidedLoss,
  missedGain,
}: ComparisonBarProps) {
  const max = Math.max(avoidedLoss, missedGain, 1);
  const avoidedPct = (avoidedLoss / max) * 100;
  const missedPct = (missedGain / max) * 100;

  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="card flex flex-col justify-between">
        <div>
          <p className="label">회피한 손실</p>
          <p className="tabular mt-2 text-2xl font-bold text-safe">
            +{formatManwon(avoidedLoss)}
          </p>
          <p className="tabular mt-1 text-xs text-ink-500">
            {avoidedLoss.toLocaleString("ko-KR")}원
          </p>
        </div>
        <div className="mt-4 h-24 w-full rounded-lg bg-ink-800 p-1">
          <div className="flex h-full flex-col justify-end">
            <div
              className="w-full rounded-md bg-safe"
              style={{ height: `${avoidedPct}%` }}
            />
          </div>
        </div>
      </div>

      <div className="card flex flex-col justify-between">
        <div>
          <p className="label">놓친 이익</p>
          <p className="tabular mt-2 text-2xl font-bold text-ink-300">
            −{formatManwon(missedGain)}
          </p>
          <p className="tabular mt-1 text-xs text-ink-500">
            {missedGain.toLocaleString("ko-KR")}원
          </p>
        </div>
        <div className="mt-4 h-24 w-full rounded-lg bg-ink-800 p-1">
          <div className="flex h-full flex-col justify-end">
            <div
              className="w-full rounded-md bg-ink-500"
              style={{ height: `${missedPct}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
