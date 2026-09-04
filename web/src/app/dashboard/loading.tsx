/**
 * /dashboard 로딩 스켈레톤.
 *
 * 서버 컴포넌트가 FastAPI 를 기다리는 동안(Render free 플랜은 콜드스타트가 길다)
 * 흰/검은 백지 대신 실제 레이아웃 골격을 보여준다. layout.tsx 의 BottomNav 는
 * 그대로 남으므로 탭 이동은 로딩 중에도 가능하다.
 */
export default function DashboardLoading() {
  return (
    <div className="animate-pulse">
      {/* 데이터 소스 배지 자리 */}
      <div className="flex items-center justify-between border-b border-ink-800 bg-ink-900 px-5 py-2.5">
        <div className="h-3 w-28 rounded bg-ink-700" />
        <div className="h-3 w-20 rounded bg-ink-800" />
      </div>

      {/* PageHeader 자리 */}
      <div className="border-b border-ink-800 px-5 pb-5 pt-8">
        <div className="h-3 w-20 rounded bg-ink-800" />
        <div className="mt-3 h-6 w-56 rounded bg-ink-700" />
        <div className="mt-3 h-4 w-40 rounded bg-ink-800" />
      </div>

      {/* ArcGauge 자리 */}
      <div className="flex flex-col items-center border-b border-ink-800 px-5 py-8">
        <div className="h-[130px] w-[240px] rounded-t-full bg-ink-800" />
        <div className="mt-4 h-4 w-64 rounded bg-ink-800" />
        <div className="mt-2 h-4 w-48 rounded bg-ink-800" />
      </div>

      {/* 3대 편향 지표 카드 자리 */}
      <div className="space-y-3 px-5 py-6">
        <div className="h-3 w-24 rounded bg-ink-800" />
        {[0, 1, 2].map((i) => (
          <div key={i} className="card space-y-3">
            <div className="flex items-center justify-between">
              <div className="h-4 w-24 rounded bg-ink-700" />
              <div className="h-4 w-12 rounded bg-ink-700" />
            </div>
            <div className="h-2 w-full rounded-full bg-ink-800" />
            <div className="h-3 w-3/4 rounded bg-ink-800" />
          </div>
        ))}
      </div>

      {/* 하단 CTA 자리 */}
      <div className="px-5 pb-8">
        <div className="h-[52px] w-full rounded-xl bg-ink-800" />
      </div>
    </div>
  );
}
