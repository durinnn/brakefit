/** 화면 표기용 포맷 유틸. 데이터 계층과 무관하므로 백엔드 연동과 상관없이 유지된다. */

export function formatWon(value: number): string {
  return `${value < 0 ? "-" : ""}${Math.abs(value).toLocaleString("ko-KR")}원`;
}

/** 만원 단위 축약 (예: 8,420,000 → 842만) */
export function formatManwon(value: number): string {
  const sign = value < 0 ? "-" : "";
  const man = Math.round(Math.abs(value) / 10_000);
  return `${sign}${man.toLocaleString("ko-KR")}만`;
}

/** 소수점 둘째 자리까지, 셋째 자리에서 반올림 (예: 33.33333333333333 → 33.33) */
export function formatScore(value: number): string {
  return value.toFixed(2);
}

export function formatSigned(value: number, unit = ""): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("ko-KR")}${unit}`;
}

export function clamp(value: number, min = 0, max = 100): number {
  return Math.min(max, Math.max(min, value));
}
