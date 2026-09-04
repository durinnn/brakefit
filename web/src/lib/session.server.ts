/**
 * 서버 컴포넌트에서 업로드 세션을 읽는다.
 *
 * next/headers 는 클라이언트 번들에 들어갈 수 없어서 session.ts 와 파일을 분리했다.
 * cookies() 를 호출하면 해당 라우트는 자동으로 동적 렌더링이 된다 — 어차피 세 화면
 * 모두 cache:"no-store" fetch 라 정적 프리렌더 대상이 아니었다.
 */

import { cookies } from "next/headers";
import { SESSION_COOKIE } from "./session";

export async function getServerSession(): Promise<string | null> {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value ?? null;
}
