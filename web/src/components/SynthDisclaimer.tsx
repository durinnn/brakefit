import type { DataSource } from "@/lib/api";

interface SynthDisclaimerProps {
  /** 지금 화면이 보고 있는 데이터 출처 */
  source: DataSource;
}

/**
 * 합성 페르소나 데이터로 계산된 화면에 붙는 각주.
 *
 * AGENTS.md 절대규칙 6 — "합성 페르소나 결과에는 '실사용자 분포 아님' 각주를
 * 반드시 단다". 심사위원이 데모 숫자를 실사용자 통계로 오해하면 안 되기 때문에,
 * 페르소나 소스일 때는 페이지마다 예외 없이 이 문구가 붙어야 한다.
 *
 * 업로드 세션(source === "session")은 사용자가 올린 실제 거래내역이라
 * 이 각주가 오히려 거짓말이 되므로 렌더하지 않는다.
 */
export default function SynthDisclaimer({ source }: SynthDisclaimerProps) {
  if (source !== "persona") return null;

  return (
    <p className="px-5 pb-8 text-xs leading-relaxed text-ink-600">
      * 합성 페르소나 데이터 기반 결과입니다. 실사용자 분포가 아닙니다.
    </p>
  );
}
