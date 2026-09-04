import Link from "next/link";
import OrderForm from "./OrderForm";
import PageHeader from "@/components/PageHeader";
import SynthDisclaimer from "@/components/SynthDisclaimer";
import { getUniverse } from "@/lib/api";
import { getServerSession } from "@/lib/session.server";

/**
 * 모의 주문 화면.
 *
 * 서버 컴포넌트는 **종목 목록만** 가져온다. 판정(POST /api/simulate-order)은
 * 사용자가 주문 버튼을 누른 뒤에 일어나야 하므로 OrderForm(클라이언트)이 맡는다.
 */
export default async function TradePage() {
  const session = await getServerSession();
  const { data: universe, source, sessionExpired } = await getUniverse(session);

  return (
    <>
      <PageHeader
        eyebrow="모의 주문"
        title="주문을 넣기 직전입니다"
        caption={
          source === "session"
            ? "내 거래내역에 있는 종목으로 주문을 넣어보세요. 과거 패턴과 겹치면 브레이크가 걸립니다."
            : "데모 페르소나의 거래 종목으로 주문을 넣어보세요. 과거 패턴과 겹치면 브레이크가 걸립니다."
        }
      />

      {universe.length > 0 ? (
        <OrderForm
          universe={universe}
          source={source}
          sessionExpired={sessionExpired}
        />
      ) : (
        /* 종목이 하나도 없으면 판정할 대상이 없다 — 룰은 timeline 이 있는 종목만 본다 */
        <section className="space-y-4 px-5 py-6">
          <div className="rounded-2xl border border-warn/40 bg-ink-900 p-5">
            <p className="text-base font-bold text-ink-100">
              주문할 수 있는 종목이 없습니다
            </p>
            <p className="mt-2 text-sm leading-relaxed text-ink-300">
              브레이크는 과거에 거래한 적 있는 종목만 판정합니다. 거래내역을
              올리거나 데모 페르소나로 둘러보세요.
            </p>
          </div>
          <Link
            href="/upload"
            className="flex w-full items-center justify-center rounded-xl border border-ink-600 bg-ink-800 py-4 text-sm font-semibold text-ink-100 transition-colors hover:bg-ink-700"
          >
            거래내역 올리기 →
          </Link>
        </section>
      )}

      <SynthDisclaimer source={source} />
    </>
  );
}
