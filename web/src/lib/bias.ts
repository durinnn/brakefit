/**
 * 편향 키 관련 표시 유틸.
 *
 * "이번 판정을 주도한 편향"을 프론트에서 추정하지 않는 것이 요점이다. 지배 편향
 * 규칙("발동한 룰 중 기여 최대")은 개입 조건과 붙어 있어서 core/rules 에만 있어야
 * 하는데, contributions 의 value 최댓값으로 되짚으면 (1) 과거 점수만 높고 이번
 * 주문에선 발동하지 않은 룰이 뽑히고 (2) 라벨 문자열이 바뀌는 순간 조용히 틀린다.
 * 그래서 서버가 dominantKey 로 내려주고, 여기서는 그게 없을 때(구버전 응답)만
 * 예전 방식으로 물러선다.
 */

import type { BiasKey, InterventionReport } from "@/lib/types";

export const BIAS_LABEL: Record<BiasKey, string> = {
  disposition: "처분효과",
  averaging_down: "물타기",
  chasing: "추격매수",
};

/** 라벨 → 키 역인덱스. 폴백 경로에서만 쓴다. */
const KEY_BY_LABEL = Object.fromEntries(
  Object.entries(BIAS_LABEL).map(([key, label]) => [label, key as BiasKey]),
) as Record<string, BiasKey | undefined>;

/**
 * 이번 판정의 지배 편향. 개입이 아니거나 알 수 없으면 null.
 *
 * 1순위: 서버가 내려준 dominantKey
 * 2순위(폴백): 기여도(value)가 가장 큰 항목의 라벨을 키로 되짚기
 */
export function dominantBias(report: InterventionReport): BiasKey | null {
  if (report.dominantKey) return report.dominantKey;
  if (!report.shouldIntervene) return null;

  let top: { key: BiasKey; value: number } | null = null;
  for (const item of report.contributions) {
    const key = KEY_BY_LABEL[item.label];
    if (!key) continue;
    if (!top || item.value > top.value) top = { key, value: item.value };
  }
  return top?.key ?? null;
}
