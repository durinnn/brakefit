/** /trade 로딩 스켈레톤 — 주문 입력 폼 골격 (종목 · 매수매도 · 수량/가격 · 주문 버튼). */
export default function TradeLoading() {
  return (
    <div className="animate-pulse">
      {/* PageHeader 자리 */}
      <div className="border-b border-ink-800 px-5 pb-5 pt-8">
        <div className="h-3 w-20 rounded bg-ink-800" />
        <div className="mt-3 h-7 w-56 rounded bg-ink-700" />
        <div className="mt-3 h-4 w-full max-w-[320px] rounded bg-ink-800" />
      </div>

      <div className="space-y-5 px-5 py-6">
        {/* 종목 select 자리 */}
        <div>
          <div className="h-3 w-10 rounded bg-ink-800" />
          <div className="mt-2 h-[52px] w-full rounded-xl bg-ink-900" />
          <div className="mt-2 h-3 w-40 rounded bg-ink-800" />
        </div>

        {/* 매수/매도 토글 자리 */}
        <div>
          <div className="h-3 w-16 rounded bg-ink-800" />
          <div className="mt-2 h-[56px] w-full rounded-xl bg-ink-900" />
        </div>

        {/* 수량 · 가격 자리 */}
        <div className="grid grid-cols-2 gap-3">
          {[0, 1].map((i) => (
            <div key={i}>
              <div className="h-3 w-20 rounded bg-ink-800" />
              <div className="mt-2 h-[52px] w-full rounded-xl bg-ink-900" />
            </div>
          ))}
        </div>

        {/* 주문 금액 자리 */}
        <div className="flex justify-between rounded-xl bg-ink-900 px-4 py-3">
          <div className="h-4 w-16 rounded bg-ink-800" />
          <div className="h-4 w-24 rounded bg-ink-800" />
        </div>

        {/* 주문 버튼 자리 */}
        <div className="h-[56px] w-full rounded-xl bg-ink-800" />
      </div>
    </div>
  );
}
