# 매매 브레이크 — 핵심 플로우 시퀀스 다이어그램

> 목적: "게이지·워터폴·개입이 실제로 어떻게 동작하는가"를 시간 순서로 공유. D의 목 API 서버는 이 시퀀스의 canned 버전이며, 통합(9/4)은 목을 진짜 모듈로 교체하는 작업이다.
> 위치: 레포 `docs/sequences.md`

## ① 진단 플로우 — CSV 업로드 → 편향 건강검진 리포트

```mermaid
sequenceDiagram
    actor U as 사용자
    participant UI as 웹 UI (D)
    participant API as API 서버 (D)
    participant P as CSV 파서 (B)
    participant E as 재구성 엔진 (A)
    participant M as 지표 3종 (C·B)
    participant G as LLM 가드레일 (C)
    participant L as LLM API
    participant K as pykrx

    U->>UI: KB M-able CSV 업로드
    UI->>API: POST /upload
    API->>P: 원본 CSV
    P-->>API: 표준 거래내역 + 검증 리포트<br/>(건수·기간·스킵 행과 사유)
    API->>E: 표준 거래내역
    E->>K: 보유 종목 일봉 조회 (공유 캐시)
    K-->>E: 일봉 OHLCV
    E-->>API: 포지션 타임라인 + 에피소드
    API->>M: 타임라인 · 에피소드
    M-->>API: 지표 3종 {raw, score_0_100, evidence[]}
    API->>G: evidence JSON (context: report_summary)
    G->>L: 시스템 프롬프트 + evidence
    L-->>G: {headline, body} 종합 소견
    G->>G: 검증: 출력 숫자가 입력에 존재하는가 /<br/>금지어(추천·매수하세요·목표가 등) 없는가
    alt 검증 실패 또는 타임아웃(2~3초)
        G-->>API: 룰별 고정 템플릿 소견 (폴백)
    else 통과
        G-->>API: LLM 소견
    end
    API-->>UI: 리포트 JSON (지표 점수 + 백분위 + 소견)
    UI-->>U: 편향 건강검진 리포트 렌더
```

## ② 개입 플로우 — 모의 주문 → 게이지·워터폴 → 경고 팝업

```mermaid
sequenceDiagram
    actor U as 사용자
    participant UI as 모의 주문창 (D)
    participant API as API 서버 (D)
    participant R as 브레이크 룰 3종 (C)
    participant G as LLM 가드레일 (C)
    participant L as LLM API

    Note over U,API: 전제: 진단 완료 상태 — 개인 타임라인·지표 evidence 보유
    U->>UI: 종목·방향·수량 입력<br/>("이 종목을 지금 산다면")
    UI->>API: POST /simulate-order
    API->>R: 주문 컨텍스트 + 개인 이력<br/>※ 주문 시점에 알 수 있는 정보만 (룩어헤드 금지)
    R-->>API: 위험 점수 72 + 룰별 기여 + evidence
    API-->>UI: [즉시] 게이지 72/100 + 워터폴<br/>(0 → +38 추격매수 → +22 물타기 → +12 회전)
    Note over UI: 게이지·워터폴은 룰 계산이라 즉시 렌더.<br/>문구는 뒤이어 비동기 도착 — LLM 지연이 UX를 막지 않음
    API->>G: evidence JSON (context: order_intervention)
    G->>L: 프롬프트 + evidence
    L-->>G: {headline, body}
    G->>G: 숫자 화이트리스트 · 금지어 검증
    alt 검증 실패 또는 타임아웃
        G-->>API: 룰별 고정 템플릿 문구 (폴백)
    else 통과
        G-->>API: 개입 문구
    end
    API-->>UI: 경고 팝업 문구
    UI-->>U: "과거 12번과 같은 패턴입니다"<br/>+ 근거 수치 + 재확인 유도
    Note over U,UI: MVP의 개입 = 콘셉트 작동 증명.<br/>실시간 주문 개입은 채널 통합(B2B) 로드맵
```

## 읽는 법 · 킥오프 확인 포인트

- **판단과 언어의 분리가 시간축에 보인다**: 두 플로우 모두 점수·판정(룰)이 먼저 확정되고, LLM은 그 결과를 문구로 번역할 뿐 판단에 관여하지 않는다. 폴백이 발동해도 점수·게이지는 그대로 — 서비스 핵심 기능은 LLM 장애와 무관
- **데모 안정성 장치**: 시연용 페르소나 3종의 LLM 문구는 사전 생성·캐시 → 시연장에서 외부 API 실패 확률 0
- [ ] C: 룰 응답과 evidence JSON 구조가 api.md 초안과 일치하는지 확인
- [ ] D: 목 서버의 canned 응답을 이 시퀀스 순서 그대로 구성
- [ ] 전원: 자기 participant 구간의 입출력에 이견 없는지 확인
