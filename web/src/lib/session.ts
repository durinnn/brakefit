/**
 * 업로드 세션 식별자 보관 규약 (클라이언트 측).
 *
 * localStorage 가 아니라 쿠키를 쓴다 — /dashboard · /trade · /backtest 가 전부
 * async 서버 컴포넌트라서 렌더 시점에 세션을 알아야 하는데, 서버에서는
 * localStorage 를 읽을 수 없기 때문이다. 쿠키면 next/headers 의 cookies() 로
 * 서버가 그대로 읽는다(session.server.ts).
 *
 * 서버 전용 읽기는 session.server.ts 에 따로 뒀다. 이 파일은 next/headers 를
 * import 하지 않으므로 클라이언트 컴포넌트에서 안전하게 쓸 수 있다.
 */

export const SESSION_COOKIE = "bf_session";

/** 데모 중 브라우저를 닫았다 켜도 유지되도록 넉넉히. (백엔드 세션이 먼저 만료될 수 있음) */
const MAX_AGE_SECONDS = 60 * 60 * 24 * 7;

export function readClientSession(): string | null {
  if (typeof document === "undefined") return null;
  const hit = document.cookie
    .split("; ")
    .find((entry) => entry.startsWith(`${SESSION_COOKIE}=`));
  if (!hit) return null;
  const value = decodeURIComponent(hit.slice(SESSION_COOKIE.length + 1));
  return value || null;
}

export function writeClientSession(sessionId: string): void {
  if (typeof document === "undefined") return;
  // 배포(https)에서만 Secure 를 붙인다 — localhost(http) 에 붙이면 쿠키가 저장 안 됨
  const secure =
    typeof location !== "undefined" && location.protocol === "https:"
      ? "; Secure"
      : "";
  document.cookie =
    `${SESSION_COOKIE}=${encodeURIComponent(sessionId)}` +
    `; path=/; max-age=${MAX_AGE_SECONDS}; SameSite=Lax${secure}`;
}

export function clearClientSession(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${SESSION_COOKIE}=; path=/; max-age=0; SameSite=Lax`;
}
