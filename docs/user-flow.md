# 사용자 흐름도

> `docs/spec.md` §2 에서 참조. 화면 4개 + API 5개. 실선 = 사용자 행동, 점선 = 시스템 동작.

## 1. 전체 흐름 (90초 데모 순서)

```mermaid
flowchart LR
    Start(("시작")) --> Choice{"거래내역<br/>있음?"}
    Choice -->|"예"| Upload["업로드<br/>/upload"]
    Choice -->|"아니오 (체험)"| Persona["합성 페르소나 데모<br/>?persona=chasing_prone"]
    Upload -->|"CSV·XLS 1개"| Parse[/"POST /api/upload<br/>파서 → 세션 발급"/]
    Parse -->|"세션 쿠키 bf_session"| Dash
    Persona --> Dash["진단 대시보드<br/>/dashboard"]
    Dash --> Trade["모의 주문창<br/>/trade"]
    Dash --> BT["백테스트<br/>/backtest"]
    Trade -->|"종목·수량·가격 입력"| Sim[/"POST /api/simulate-order<br/>브레이크 룰 판정"/]
    Sim -->|"개입 필요"| Popup["브레이크 팝업<br/>편향·근거·대안"]
    Sim -->|"통과"| Ok["주문 통과 안내"]
    Popup --> BT
    BT -->|"GET /api/backtest"| Result["회피 손실 − 놓친 이익<br/>워터폴"]
```

## 2. 화면별 상태

```mermaid
stateDiagram-v2
    [*] --> 로딩: 페이지 진입
    로딩 --> 정상: API 200
    로딩 --> 세션만료: 404 session
    로딩 --> 오류: 5xx / 연결 실패
    세션만료 --> 정상: 페르소나 폴백 + 배지 표시
    오류 --> 로딩: 다시 시도
    정상 --> 정상: 경고 배너 (과매도·종목코드 미해결)
```

- **로딩**: 스켈레톤(회색 카드). 서버 콜드스타트 대비.
- **세션만료**: 서버 재시작·50세션 초과로 세션이 사라지면 페르소나 데모로 폴백하고 배지로 알림.
- **오류**: `error.tsx` 안내 + 다시 시도 버튼.
- **합성 각주**: 출처가 페르소나일 때만 하단에 "실사용자 분포 아님" 표시.

## 3. 데이터 흐름 (요청 1건 기준)

```mermaid
sequenceDiagram
    participant U as 사용자
    participant W as Next.js (Vercel)
    participant A as FastAPI (Render)
    participant E as 엔진·지표·룰
    participant L as LLM (Haiku)

    U->>W: /trade 에서 주문 입력
    W->>A: POST /api/simulate-order?session=
    A->>E: 세션 거래내역 + 주문 → as_of 이전 정보만으로 판정
    E-->>A: 개입 여부 · 지배 편향 · evidence
    alt 개입 필요
        A->>L: 문구 생성 (2.5s 타임아웃, 숫자 화이트리스트)
        L-->>A: 문구 (실패 시 고정 템플릿)
    end
    A-->>W: InterventionReport (camelCase)
    W-->>U: 팝업 or 통과
```

원칙: 판정에 미래 가격 없음(AGENTS.md 규칙 1). 백테스트만 사후 가격으로 **평가**한다.
