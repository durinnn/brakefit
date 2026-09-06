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

      {/* 종목이 하나도 없는 경우(= 판정할 대상 없음)의 안내도 OrderForm 안에 있다 —
          같은 상황의 문구가 두 파일에 갈라져 있으면 한쪽만 고치게 된다 */}
      <OrderForm
        universe={universe}
        source={source}
        sessionExpired={sessionExpired}
      />

      <SynthDisclaimer source={source} />
    </>
  );
}
