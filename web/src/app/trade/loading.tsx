/** /trade 로딩 스켈레톤 — 주문 요약 · 위험 게이지 · 워터폴 · 경고 박스 골격. */
export default function TradeLoading() {
  return (
    <div className="animate-pulse">
      {/* 주문 요약 헤더 자리 */}
      <div className="border-b border-ink-800 px-5 pb-4 pt-8">
        <div className="h-3 w-24 rounded bg-ink-800" />
        <div className="mt-3 flex items-baseline justify-between">
          <div>
            <div className="h-6 w-28 rounded bg-ink-700" />
            <div className="mt-2 h-3 w-16 rounded bg-ink-800" />
          </div>
          <div className="h-5 w-16 rounded bg-ink-700" />
        </div>
        <div className="mt-4 flex justify-between rounded-xl bg-ink-900 px-4 py-3">
          <div className="h-4 w-40 rounded bg-ink-800" />
          <div className="h-4 w-20 rounded bg-ink-800" />
        </div>
      </div>

      {/* 위험 게이지 자리 */}
      <div className="flex flex-col items-center border-b border-ink-800 px-5 py-8">
        <div className="h-[140px] w-[260px] rounded-t-full bg-ink-800" />
        <div className="mt-4 h-4 w-44 rounded bg-ink-800" />
      </div>

      {/* 워터폴 자리 */}
      <div className="border-b border-ink-800 px-5 py-6">
        <div className="h-3 w-48 rounded bg-ink-800" />
        <div className="mt-4 space-y-3">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="h-3 w-20 shrink-0 rounded bg-ink-800" />
              <div className="h-5 flex-1 rounded bg-ink-800" />
            </div>
          ))}
        </div>
      </div>

      {/* 경고 박스 + 액션 자리 */}
      <div className="space-y-5 px-5 py-6">
        <div className="space-y-3 rounded-2xl border border-ink-700 bg-ink-900 p-5">
          <div className="h-4 w-32 rounded bg-ink-700" />
          <div className="h-3 w-full rounded bg-ink-800" />
          <div className="h-3 w-4/5 rounded bg-ink-800" />
        </div>
        <div className="space-y-3">
          <div className="h-[52px] w-full rounded-xl bg-ink-800" />
          <div className="h-[52px] w-full rounded-xl bg-ink-800" />
        </div>
      </div>
    </div>
  );
}
