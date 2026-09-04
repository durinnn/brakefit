import Link from "next/link";

/** 없는 경로로 들어온 경우. 데모 중 오타 URL 로 영어 404 가 뜨는 걸 막는다. */
export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center px-5 text-center">
      <p className="label">404</p>
      <h1 className="mt-3 text-xl font-bold leading-snug text-ink-100">
        페이지를 찾을 수 없습니다.
      </h1>
      <p className="mt-3 max-w-[300px] text-sm leading-relaxed text-ink-400">
        주소가 바뀌었거나 삭제된 화면입니다.
      </p>
      <Link
        href="/dashboard"
        className="mt-8 w-full max-w-[280px] rounded-xl border border-ink-600 bg-ink-800 py-3.5 text-sm font-semibold text-ink-100 transition-colors hover:bg-ink-700"
      >
        진단 화면으로 가기
      </Link>
    </div>
  );
}
