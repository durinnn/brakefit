/** /backtest 로딩 스켈레톤 — 순수익 카드 · 비교 막대 · 개입 사례 목록 골격. */
export default function BacktestLoading() {
  return (
    <div className="animate-pulse">
      {/* PageHeader 자리 */}
      <div className="border-b border-ink-800 px-5 pb-5 pt-8">
        <div className="h-3 w-20 rounded bg-ink-800" />
        <div className="mt-3 h-6 w-48 rounded bg-ink-700" />
        <div className="mt-3 h-4 w-44 rounded bg-ink-800" />
      </div>

      {/* NetResultCard 자리 */}
      <div className="px-5 py-6">
        <div className="card space-y-4">
          <div className="h-3 w-24 rounded bg-ink-800" />
          <div className="h-9 w-48 rounded bg-ink-700" />
          <div className="flex gap-3">
            <div className="h-4 w-24 rounded bg-ink-800" />
            <div className="h-4 w-24 rounded bg-ink-800" />
          </div>
        </div>
      </div>

      {/* 비교 막대 자리 */}
      <div className="px-5 pb-6">
        <div className="mb-3 h-3 w-40 rounded bg-ink-800" />
        <div className="space-y-3">
          <div className="h-7 w-full rounded-lg bg-ink-800" />
          <div className="h-7 w-2/3 rounded-lg bg-ink-800" />
        </div>
        <div className="mx-auto mt-4 h-4 w-56 rounded bg-ink-800" />
      </div>

      {/* 개입 사례 목록 자리 */}
      <div className="px-5 pb-8">
        <div className="mb-3 h-3 w-28 rounded bg-ink-800" />
        <div className="divide-y divide-ink-800 overflow-hidden rounded-2xl border border-ink-700 bg-ink-900">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex items-center justify-between px-4 py-3.5">
              <div className="space-y-2">
                <div className="h-4 w-24 rounded bg-ink-700" />
                <div className="h-3 w-32 rounded bg-ink-800" />
              </div>
              <div className="space-y-2 text-right">
                <div className="ml-auto h-4 w-20 rounded bg-ink-700" />
                <div className="ml-auto h-3 w-14 rounded bg-ink-800" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
