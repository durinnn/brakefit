/**
 * 계산 과정에서 생긴 경고를 화면 맨 위에 한 줄씩 쌓아 보여준다.
 *
 * 이게 없으면 "보유수량보다 많이 판 기록이라 일부만 반영됨" / "종목코드를 못 찾아
 * 그 종목은 제외됨" 같은 사실이 서버 로그에만 남아서, 사용자 눈에는 잘려나간 결과와
 * 온전한 결과가 똑같이 보인다. 숫자를 못 믿게 만드는 게 아니라, 어디까지 믿을 수
 * 있는지 알려주는 게 목적이라 붉은 경고(WarningBox)가 아니라 노란색을 쓴다.
 */
export default function WarningBanner({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;

  return (
    <section
      role="status"
      className="border-b border-warn/30 bg-warn/10 px-5 py-3"
    >
      <div className="flex items-center gap-2">
        <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-warn text-[10px] font-bold text-ink-950">
          !
        </span>
        <span className="text-xs font-semibold text-warn">
          분석에 사용된 거래내역에 확인할 점이 있습니다
        </span>
      </div>

      <ul className="mt-2 space-y-1.5 pl-6">
        {warnings.map((warning) => (
          <li
            key={warning}
            className="text-xs leading-relaxed text-ink-300 before:mr-1.5 before:text-ink-500 before:content-['·']"
          >
            {warning}
          </li>
        ))}
      </ul>
    </section>
  );
}
