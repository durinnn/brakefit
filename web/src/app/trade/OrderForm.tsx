"use client";

/**
 * 모의 주문 입력 폼 + 판정 결과.
 *
 * 원래 /trade 는 api.ts 의 DEMO_ORDER(삼성전자 10주) 를 서버 컴포넌트에서 한 번
 * POST 하고 개입 화면만 그렸다. 그러면 내 거래내역을 올려도 판정 대상이 늘 삼성전자라,
 * 데모의 핵심인 "주문을 넣으려는 순간 브레이크가 걸린다" 가 화면에 안 나온다.
 * 그래서 입력(폼) → 판정(POST) → 개입(모달) 을 한 화면에서 이어붙였다.
 *
 * 클라이언트 컴포넌트인 이유: 판정은 사용자가 버튼을 누른 뒤에 일어나야 하므로
 * 서버 렌더 시점에 호출할 수 없다. 세션은 쿠키에서 직접 읽는다(session.ts).
 */

import { useEffect, useMemo, useState } from "react";
import ArcGauge from "@/components/ArcGauge";
import InterventionActions from "@/components/InterventionActions";
import type { InterventionDecision } from "@/components/InterventionActions";
import WaterfallChart from "@/components/WaterfallChart";
import WarningBox from "@/components/WarningBox";
import { DEMO_ORDER, simulateOrder, type DataSource } from "@/lib/api";
import { formatWon } from "@/lib/format";
import { clearClientSession, readClientSession } from "@/lib/session";
import type { InterventionReport, OrderInput, UniverseItem } from "@/lib/types";

const LEVEL_TONE = {
  LOW: "safe",
  MEDIUM: "warn",
  HIGH: "risk",
} as const;

const LEVEL_LABEL = {
  LOW: "낮음",
  MEDIUM: "주의",
  HIGH: "매우 위험",
} as const;

const SIDE_LABEL = { BUY: "매수", SELL: "매도" } as const;

type Side = keyof typeof SIDE_LABEL;

interface OrderFormProps {
  universe: UniverseItem[];
  source: DataSource;
  /** 서버가 만료된 세션을 만나 페르소나로 폴백했는지 (쿠키 정리용) */
  sessionExpired: boolean;
}

/** 폼 초기값. 데모 편의상 페르소나 모드에서는 확실히 트리거되는 DEMO_ORDER 를 쓴다. */
function initialForm(universe: UniverseItem[], source: DataSource) {
  const demo =
    source === "persona"
      ? universe.find((u) => u.ticker === DEMO_ORDER.ticker)
      : undefined;
  if (demo) {
    return {
      ticker: demo.ticker,
      side: DEMO_ORDER.side as Side,
      quantity: String(DEMO_ORDER.quantity),
      price: String(DEMO_ORDER.price),
    };
  }
  const first = universe[0];
  return {
    ticker: first?.ticker ?? "",
    side: "BUY" as Side,
    quantity: "10",
    // 시세를 못 구한 종목은 빈칸으로 둔다 — 없는 가격을 지어내지 않는다
    price: first?.lastClose != null ? String(first.lastClose) : "",
  };
}

export default function OrderForm({
  universe,
  source,
  sessionExpired,
}: OrderFormProps) {
  const [form, setForm] = useState(() => initialForm(universe, source));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<InterventionReport | null>(null);
  const [decision, setDecision] = useState<InterventionDecision | null>(null);

  useEffect(() => {
    if (sessionExpired) clearClientSession();
  }, [sessionExpired]);

  const selected = useMemo(
    () => universe.find((u) => u.ticker === form.ticker) ?? null,
    [universe, form.ticker],
  );

  const quantity = Number(form.quantity);
  const price = Number(form.price);
  const valid =
    Boolean(selected) &&
    Number.isFinite(quantity) &&
    quantity >= 1 &&
    Number.isFinite(price) &&
    price > 0;
  const amount = valid ? quantity * price : 0;

  /** 종목을 바꾸면 예상 체결가를 그 종목의 최근 종가로 되돌린다 (MTS 와 같은 동작). */
  function selectTicker(ticker: string) {
    const next = universe.find((u) => u.ticker === ticker);
    setForm((prev) => ({
      ...prev,
      ticker,
      price: next?.lastClose != null ? String(next.lastClose) : "",
    }));
    setError(null);
  }

  async function submit() {
    if (!valid || !selected || busy) return;
    setBusy(true);
    setError(null);
    setDecision(null);
    const order: OrderInput = {
      ticker: selected.ticker,
      name: selected.name,
      side: form.side,
      quantity,
      price,
    };
    try {
      // 서버가 이미 페르소나로 폴백한 화면이면 죽은 세션을 다시 보내지 않는다
      const session = source === "session" ? readClientSession() : null;
      const { data } = await simulateOrder(order, session);
      setReport(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "주문 판정에 실패했습니다");
    } finally {
      setBusy(false);
    }
  }

  /**
   * ⚠ 개입 팝업 여부는 백엔드 판정(core/rules 의 should_intervene)만 따른다.
   *
   * 알려진 제약: 현재 임계값(INTERVENE_THRESHOLD=50) 기준으로는 데모 페르소나 5종 ×
   * DEMO_UNIVERSE 3종목 어떤 조합도 50점에 못 닿는다(실측 최대 29.57 — chasing_prone
   * 이 전일 종가 +8% 로 매수). 룰 기여가 "MAX_CONTRIBUTION × 과거 지표점수/100" 이라
   * 두 룰이 동시에 세게 걸려야 넘는 구조인데, 합성 페르소나는 한 축만 강하기 때문이다.
   * 임계값·기여식 조정은 core/rules 오너(C) 판단이라 여기서 riskLevel 로 우회하지
   * 않는다 — 화면이 룰보다 느슨하게 판정하면 그게 더 큰 버그다.
   */
  const intervening = report?.shouldIntervene === true;

  return (
    <>
      <section className="space-y-5 px-5 py-6">
        {/* 종목 */}
        <div>
          <label htmlFor="order-ticker" className="label">
            종목
          </label>
          <select
            id="order-ticker"
            value={form.ticker}
            onChange={(e) => selectTicker(e.target.value)}
            className="mt-2 w-full appearance-none rounded-xl border border-ink-700 bg-ink-900 px-4 py-3.5 text-base font-semibold text-ink-100 outline-none focus:border-ink-500"
          >
            {universe.map((item) => (
              <option key={item.ticker} value={item.ticker}>
                {item.name} ({item.ticker})
              </option>
            ))}
          </select>
          <p className="tabular mt-2 text-xs text-ink-500">
            {selected?.lastClose != null
              ? `기준 종가 ${selected.lastClose.toLocaleString("ko-KR")}원 · ${selected.lastDate}`
              : "기준 종가 없음 — 예상 체결가를 직접 입력하세요"}
          </p>
        </div>

        {/* 매수 / 매도 */}
        <div>
          <span className="label">주문 구분</span>
          <div className="mt-2 grid grid-cols-2 gap-2 rounded-xl border border-ink-700 bg-ink-900 p-1">
            {(["BUY", "SELL"] as const).map((side) => (
              <button
                key={side}
                type="button"
                aria-pressed={form.side === side}
                onClick={() => setForm((prev) => ({ ...prev, side }))}
                className={[
                  "rounded-lg py-3 text-sm font-bold transition-colors",
                  form.side === side
                    ? side === "BUY"
                      ? "bg-risk text-ink-950"
                      : "bg-safe text-ink-950"
                    : "text-ink-400 hover:text-ink-200",
                ].join(" ")}
              >
                {SIDE_LABEL[side]}
              </button>
            ))}
          </div>
        </div>

        {/* 수량 · 가격 */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="order-quantity" className="label">
              수량 (주)
            </label>
            <input
              id="order-quantity"
              type="number"
              inputMode="numeric"
              min={1}
              step={1}
              value={form.quantity}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, quantity: e.target.value }))
              }
              className="tabular mt-2 w-full rounded-xl border border-ink-700 bg-ink-900 px-4 py-3.5 text-right text-base font-semibold text-ink-100 outline-none focus:border-ink-500"
            />
          </div>
          <div>
            <label htmlFor="order-price" className="label">
              예상 체결가 (원)
            </label>
            <input
              id="order-price"
              type="number"
              inputMode="decimal"
              min={0}
              step={10}
              value={form.price}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, price: e.target.value }))
              }
              className="tabular mt-2 w-full rounded-xl border border-ink-700 bg-ink-900 px-4 py-3.5 text-right text-base font-semibold text-ink-100 outline-none focus:border-ink-500"
            />
          </div>
        </div>

        {/* 주문 금액 */}
        <div className="tabular flex items-center justify-between rounded-xl bg-ink-900 px-4 py-3 text-sm">
          <span className="text-ink-400">주문 금액</span>
          <span className="font-semibold text-ink-100">
            {valid ? formatWon(amount) : "-"}
          </span>
        </div>

        {error ? (
          <div className="rounded-xl border border-risk/40 bg-risk-dim/40 p-4">
            <p className="text-sm font-semibold text-risk-soft">판정 실패</p>
            <p className="mt-1 text-sm leading-relaxed text-ink-300">{error}</p>
          </div>
        ) : null}

        {/* 판정 결과: 개입이면 아래 모달, 아니면 통과 카드.
            통과일 때도 워터폴을 같이 보여준다 — 점수만 던지면 "아무 일도 안 일어났다"
            로 보여서, 브레이크가 실제로 주문을 채점했다는 사실이 화면에서 사라진다. */}
        {report && !intervening && !decision ? (
          <div className="space-y-4 rounded-2xl border border-safe/40 bg-safe-dim/50 p-5">
            <div>
              <p className="text-base font-bold text-safe-soft">
                브레이크 없음 · 주문 접수
              </p>
              <p className="tabular mt-2 text-sm text-ink-200">
                {report.order.name} {SIDE_LABEL[form.side]}{" "}
                {report.order.quantity}주 ·{" "}
                {report.order.price.toLocaleString("ko-KR")}원 · 기준 종가 대비{" "}
                {report.order.changeRate > 0 ? "+" : ""}
                {report.order.changeRate}%
              </p>
              <p className="tabular mt-2 text-sm leading-relaxed text-ink-300">
                위험 점수 {report.riskScore}점 ({LEVEL_LABEL[report.riskLevel]})
                — {report.warning.headline}
              </p>
            </div>

            <div className="rounded-xl bg-ink-950/40 p-4">
              <p className="label">위험 점수 계산 근거</p>
              <div className="mt-3">
                <WaterfallChart
                  baseScore={report.baseScore}
                  contributions={report.contributions}
                  total={report.riskScore}
                />
              </div>
            </div>
          </div>
        ) : null}

        {decision ? (
          <div
            className={[
              "rounded-2xl border p-5",
              decision === "stopped"
                ? "border-safe/40 bg-safe-dim/50"
                : "border-ink-600 bg-ink-800",
            ].join(" ")}
          >
            <p
              className={[
                "text-base font-bold",
                decision === "stopped" ? "text-safe-soft" : "text-ink-100",
              ].join(" ")}
            >
              {decision === "stopped"
                ? "주문을 멈췄습니다"
                : "경고를 무시하고 주문이 접수되었습니다"}
            </p>
            <p className="mt-2 text-sm leading-relaxed text-ink-300">
              {decision === "stopped"
                ? "24시간 뒤 같은 종목을 다시 검토할지 알려드릴게요."
                : "이 거래는 ‘경고 후 강행’으로 기록되어 다음 진단에 반영됩니다."}
            </p>
          </div>
        ) : null}

        {/* 하단 큰 버튼 */}
        <button
          type="button"
          onClick={submit}
          disabled={!valid || busy}
          className={[
            "w-full rounded-xl py-4 text-base font-bold text-ink-950 transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40",
            form.side === "BUY" ? "bg-risk" : "bg-safe",
          ].join(" ")}
        >
          {busy ? "판정 중…" : `${SIDE_LABEL[form.side]} 주문`}
        </button>

        <p className="text-xs leading-relaxed text-ink-600">
          * 실제 주문이 나가지 않는 모의 주문입니다. 주문을 넣기 직전 시점에 알 수
          있는 정보만으로 판정합니다.
        </p>
      </section>

      {report && intervening && !decision ? (
        <InterventionModal
          report={report}
          side={form.side}
          onClose={() => setReport(null)}
          onDecision={setDecision}
        />
      ) : null}
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* 개입 팝업 — 기존 개입 화면 구성(게이지·워터폴·경고·액션)을 그대로 담는다        */
/* -------------------------------------------------------------------------- */

function InterventionModal({
  report,
  side,
  onClose,
  onDecision,
}: {
  report: InterventionReport;
  side: Side;
  onClose: () => void;
  onDecision: (decision: InterventionDecision) => void;
}) {
  const { order } = report;
  const tone = LEVEL_TONE[report.riskLevel];
  const amount = order.price * order.quantity;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    // 모달 뒤 폼이 같이 스크롤되면 바텀시트가 화면 밖으로 밀린다
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      <button
        type="button"
        aria-label="개입 경고 닫기"
        onClick={onClose}
        className="absolute inset-0 bg-ink-950/80 backdrop-blur-sm"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="intervention-title"
        className="relative flex max-h-[92vh] w-full max-w-[480px] flex-col overflow-y-auto rounded-t-3xl border-t border-risk/40 bg-ink-950 pb-8"
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-ink-800 bg-ink-950 px-5 pb-4 pt-5">
          <div>
            <p className="label text-risk-soft">주문 실행 직전</p>
            <h2
              id="intervention-title"
              className="mt-1 text-xl font-bold text-ink-100"
            >
              {order.name}
              <span className="tabular ml-2 text-xs font-normal text-ink-500">
                {order.ticker}
              </span>
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="shrink-0 rounded-lg border border-ink-700 px-3 py-1.5 text-xs text-ink-300"
          >
            닫기
          </button>
        </div>

        <div className="tabular mx-5 mt-4 flex justify-between rounded-xl bg-ink-900 px-4 py-3 text-sm">
          <span className="text-ink-400">
            {SIDE_LABEL[side]} {order.quantity}주 ·{" "}
            {order.price.toLocaleString("ko-KR")}원
          </span>
          <span className="font-semibold text-ink-100">
            {formatWon(amount)}
          </span>
        </div>
        <p className="tabular mx-5 mt-2 text-right text-sm font-bold text-risk">
          기준 종가 대비 {report.order.changeRate > 0 ? "+" : ""}
          {report.order.changeRate}%
        </p>

        <section className="mt-4 flex flex-col items-center border-b border-ink-800 px-5 pb-6">
          <ArcGauge
            value={report.riskScore}
            tone={tone}
            caption={`이 거래의 위험도 · ${LEVEL_LABEL[report.riskLevel]}`}
            size={240}
          />
        </section>

        <section className="border-b border-ink-800 px-5 py-6">
          <h3 className="label">위험 점수는 이렇게 계산됐습니다</h3>
          <div className="mt-4">
            <WaterfallChart
              baseScore={report.baseScore}
              contributions={report.contributions}
              total={report.riskScore}
            />
          </div>
        </section>

        <section className="space-y-5 px-5 py-6">
          <WarningBox warning={report.warning} />
          <InterventionActions
            suggestions={report.suggestions}
            riskScore={report.riskScore}
            confirmLabel={`그래도 ${SIDE_LABEL[side]}`}
            onDecision={onDecision}
          />
        </section>
      </div>
    </div>
  );
}
