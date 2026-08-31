# 데이터 계약 (schema)

> **상태: §6 확정됨 (2026-08-31)**
> 소유: A · 초안 작성 2026-08-27 (파서 구현 중 필요해서 B 가 먼저 씀)
> `architecture.md` 와 `sequences.md` 가 계속 이 문서를 참조하는데 실체가 없어서
> 아무도 코딩을 시작할 수 없었다. 일단 구현 가능한 최소 형태로 박아둔다.
> §6 미결 3개는 A 가 B 에게 결정을 위임해서 B 제안대로 확정 — `core/engine`
> 구현(`test-jw` → `dev`)에 그대로 반영됨.

이 문서에 적힌 것만 유효하다. 바꾸려면 **코드가 아니라 이 문서부터 PR.**

---

## 1. 표준 거래내역 (`trades`)

파서의 출력이자 엔진의 입력. 증권사가 몇 곳이든 화면이 몇 개든 전부 이 표가 된다.
엔진 이후는 원본 포맷을 전혀 모른다.

코드: `core/schema.py` · `TRADE_COLUMNS`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `trade_id` | str | 행 고유 ID. `{파일}:{시트}:{행}` |
| `traded_at` | date | 체결일 |
| `ticker` | str \| None | 종목코드 6자리. 화면에 없으면 None → `resolve_tickers()` |
| `name` | str | 종목명 (원본 표기 그대로) |
| `side` | `"BUY"` \| `"SELL"` | |
| `quantity` | int | 체결수량, 항상 양수 |
| `price` | float | 체결단가 |
| `amount` | float | **정산금액.** 실제 현금 흐름 (거래금액 아님) |
| `fee` | float \| None | 수수료 |
| `tax` | float \| None | 제세금 합계 (거래세+농특세+소득세+지방소득세+양도세) |
| `source` | str | 원본 파일명 |
| `source_row` | int | 원본 행 번호 (역추적용) |
| `note` | str | 원본 거래종류/매매구분 텍스트 (판정 근거) |

### 1.1 ⚠ `fee` / `tax` 의 `None` 과 `0`

| 값 | 의미 |
|---|---|
| `None` | **그 화면이 수수료를 안 알려준다.** → 실현손익이 gross |
| `0` | 실제로 0원이었다 |

`fillna(0)` 하지 말 것. 이 구분을 뭉개면 지표·백테스트 수치가 조용히 틀어진다.

### 1.2 `amount` 는 정산금액이지 거래금액이 아니다

```
매수:  정산금액 = 거래금액 + 수수료
매도:  정산금액 = 거래금액 − 수수료 − 제세금
```

`price × quantity`(거래금액)와 `amount`(정산금액)는 다르다.
`schema.validate()` 가 0.5% 넘게 어긋나면 경고를 띄운다 — 정상 동작이다.

---

## 2. 포지션 타임라인 (`timeline`)

엔진(A)의 출력. `(일자, 종목)` 단위.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `date` | date | 거래일 (영업일만) |
| `ticker` | str | |
| `name` | str | |
| `quantity` | int | 그날 종가 기준 보유수량 |
| `avg_cost` | float | 평단가 — **매입가중 이동평균, 매도 시 불변** |
| `close` | float | 종가 (pykrx) |
| `unrealized_pnl` | float | 평가손익 (원) = `(close − avg_cost) × quantity` |
| `unrealized_pct` | float | 평가손익률 = `close / avg_cost − 1` |
| `realized_pnl` | float | 그날 실현손익. 매도 없으면 0 |
| `holding_days` | int | 현재 에피소드 진입일로부터 경과 영업일 |
| `episode_id` | str | `{ticker}:{진입일}` |

**규칙**

- 보유수량 0 인 (일자, 종목)은 행을 만들지 않는다
- 평단가에 **수수료·세금을 포함한다** (v1). §5.1 확정 대기
- 거래정지·상장폐지로 종가가 없는 날은 **직전 종가를 캐리포워드**하고 경고를 남긴다

---

## 3. 포지션 에피소드 (`episodes`)

진입(수량 0 → 양수)부터 청산(양수 → 0)까지가 한 에피소드.
**전량 청산 후 재진입하면 새 에피소드**다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `episode_id` | str | `{ticker}:{진입일}` |
| `ticker` / `name` | str | |
| `opened_at` | date | 진입일 |
| `closed_at` | date \| None | 청산일. 미청산이면 None |
| `realized_pnl` | float | 에피소드 총 실현손익 |
| `max_unrealized_loss` | float | 기간 중 최대 평가손실 (음수) |
| `max_unrealized_loss_pct` | float | 위의 비율 |
| `add_buy_count` | int | 진입 후 추가매수 횟수 |
| `holding_days` | int | 보유 영업일수 |
| `is_open` | bool | 미청산 여부 |

---

## 4. 지표 출력

C 가 확립하고 B 가 ②③에서 복제하는 표준 형태.

```python
def compute(timeline, trades, episodes) -> MetricResult
```

```python
@dataclass
class MetricResult:
    key: str              # "disposition_effect" | "averaging_down" | "chasing"
    raw: float            # 원래 스케일의 값 (예: DE = PGR − PLR)
    score_0_100: float    # 정규화 점수. 높을수록 편향이 강함
    evidence: list[dict]  # 판정에 쓰인 거래 목록 — 워터폴·코칭 문구의 재료
```

`evidence[]` 의 각 항목은 최소한 `trade_id`, `date`, `name`, `detail`(사람이 읽는 한 줄)을 갖는다.
**LLM 은 이 evidence 안의 숫자만 쓸 수 있다** (가드레일의 숫자 화이트리스트).

---

## 5. 원시 시세 (B 제공)

`core/engine` 이전에도 종목의 원시 일봉 종가가 필요한 곳이 있다 — 예: `core/metrics/chasing.py`
가 신규 진입 매수의 추격 여부를 판정하려면 진입일 이전 종가가 있어야 하는데, `timeline`(§2)의
`close` 는 **포지션을 들고 있는 동안만** 존재해서 신규 진입 시점엔 비교할 값이 없다
(`core/metrics/chasing.py` 자체 TODO에 명시돼 있었음).

```python
from core.synth.prices import get_daily_close, as_pairs

get_daily_close(ticker: str, start: date, end: date) -> pd.Series
    # index=Timestamp(영업일만), name=ticker, 값=종가(원)
as_pairs(series: pd.Series) -> list[tuple[date, float]]
    # pandas 없이 쓰고 싶을 때
```

내부에서 pykrx 를 호출하고 `data/cache/prices/{ticker}.parquet` 에 캐싱한다(캐시는 커밋 대상 —
`.gitignore` 참조, 데모 당일 KRX 장애 대비). `core/synth` 가 합성 거래 가격을 실제 시세에
묶기 위해 먼저 만들었고, `core/metrics` 등 다른 모듈도 그대로 가져다 쓰면 된다.

---

## 6. 확정 — A 가 B 에게 위임 (2026-08-31)

> A 가 시간 부족으로 결정을 B 에게 위임했다("알아서 해"). 아래 세 항목은 B 가
> 2026-08-29 에 제안한 대로 확정됐고, `core/engine`(`test-jw` → `dev`) 구현에
> 이미 반영돼 있다. 근거는 그대로 남겨둔다 — 나중에 실 거래내역으로 반증되면
> 그때 다시 열면 된다.

### 6.1 평단가에 수수료·세금을 포함하는가 — **확정**

**`amount`(정산금액) 기준으로 계산한다.** `fee`/`tax` 를 따로 더하지 않는다.

```
avg_cost = 누적(BUY.amount) / 누적(BUY.quantity)
```

`amount` 는 §1.2 정의상 이미 수수료·세금이 반영된 값이라("매수 = 거래금액 + 수수료")
결과적으로 "포함" 이 되면서, 애초 리스크였던 "`fee`/`tax` 가 `None` 인 화면에서는
계산 불가" 문제가 아예 사라진다 — `amount` 는 화면과 무관하게 항상 채워지는 값이라서다.
`price`(체결단가)는 참고용(예: 전일 종가 대비 등락률 계산)으로만 쓰고 평단가 계산엔
안 쓴다. 구현: `core/engine/engine.py` 전체.

### 6.2 `traded_at` 의 기준 — 체결일인가 결제일인가 — **확정**

**체결일 그대로 쓰고 T+2 보정 안 한다.**

`fixtures/`(kbsec.com 웹 거래내역 실측 헤더 기준, `tests/conftest.py` 의 `LEDGER_ROWS`)를
보면 매수 당일 `예수금잔액`이 이미 전액 차감된 채로 찍힌다(2026-08-04 매수 체결 즉시
725,120원이 그날 잔액에서 바로 빠짐 — T+2 라면 08-06 에 빠져야 함). 화면 자체가
"즉시반영" 방식으로 잔액을 보여준다는 뜻이라, `거래일` 을 결제일로 다시 보정할 근거가
없다. **이건 화면 구조로부터의 추론이다** — 실 거래내역으로 반증되면(예: 정말 이틀
밀려서 찍히는 사례가 나오면) 재검토한다.

### 6.3 동일일 다중 체결 처리 — **확정**

**안 1 — 합치지 않고 그대로 둔다.**

웹 거래내역(ledger) 화면은 원래 주문 단위가 아니라 체결·정산 단위로 한 줄씩 찍히는
것으로 보이고(0112 처럼 한 주문의 부분체결을 한 화면 안에서 다시 합쳐 보여주는 화면이
아님), 그렇다면 같은 날 같은 종목이 두 줄이면 그건 정말 "따로 두 번 산" 것에 가깝다.
합쳐버리면 같은 날 두 번 결정한 사람과 한 번만 결정한 사람이 구분 안 된다 — 이쪽이
더 큰 손실이라고 판단했다. **다만 이후 0112 실데이터로 "한 주문이 여러 체결로 쪼개져
같은 날 여러 줄로 찍히는" 사례가 확인되면 재검토** — 그 경우엔 합치는 쪽(안 2)이
맞다. 구현: `core/engine/engine.py` 의 `by_day` 처리(`source_row` 순서대로 전부 적용).

---

## 7. 변경 이력

| 날짜 | 내용 |
|---|---|
| 2026-08-27 | 초안. B 가 파서 구현하면서 작성. §1 은 파서·테스트 30개로 이미 고정됨 |
| 2026-08-28 | §5 원시 시세 인터페이스(`core/synth/prices.py`) 추가 — `core/metrics/chasing.py` 의 신규진입 판정 TODO 를 이게 푼다. `core/synth` 도 이걸로 합성 거래 가격을 실제 종가에 묶음 |
| 2026-08-29 | §6 의 미결 3개에 B 제안 추가 — core/engine 착수를 기다리게 하지 않으려는 목적. 결정은 여전히 A 몫 |
| 2026-08-31 | A 가 §6 결정을 B 에게 위임 → B 제안대로 확정. `core/engine` 이 `test-jw` 에서 `dev` 로 병합됨 |
