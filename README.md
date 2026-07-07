# personalprojectLDY — 주가 예측 대시보드

키움증권 REST API(실전투자) + Oracle DB + Flask로 만든 주가 시세/예측 대시보드입니다.

## 폴더 구조

```
stock_dashboard/
├── .env                     # 실제 키/DB 접속정보 (git에 올리지 마세요)
├── .env.example             # 값이 비어있는 템플릿
├── requirements.txt
├── run.py                   # 앱 실행 진입점
└── app/
    ├── config.py             # .env를 읽어 한 곳에서 관리하는 설정 객체
    ├── __init__.py           # Flask 앱 팩토리 + 스케줄러 등록
    ├── db/
    │   ├── pool.py           # Oracle 커넥션 풀
    │   ├── schema.py         # 최초 실행 시 테이블 자동 생성
    │   └── repository.py     # 모든 SQL이 모여있는 데이터 접근 계층
    ├── services/
    │   ├── kiwoom_client.py  # 키움 REST API 토큰 발급/일봉차트 조회
    │   ├── collector.py      # 수집/백필 오케스트레이션
    │   ├── indicators.py     # 이동평균·볼린저 밴드 재계산
    │   └── predictor.py      # 선형회귀 기반 3/6/12개월 예측
    ├── routes/
    │   ├── views.py          # 화면(index) 라우트
    │   └── api.py            # JSON API 라우트
    ├── templates/
    │   └── index.html        # 마크업만 (CSS/JS 분리됨)
    └── static/
        ├── css/style.css      # 전체 스타일
        └── js/app.js          # 전체 프론트 로직
```

## 실행 방법

```bash
pip install -r requirements.txt
python run.py
```

`.env`에 전달해주신 앱키/시크릿과 Oracle 접속정보가 채워져 있고, `KIWOOM_IS_MOCK=False`로
설정되어 있어 **실전 도메인(`https://api.kiwoom.com`)** 을 사용합니다.

⚠️ 실전 도메인은 모의투자용으로 발급받은 앱키/시크릿을 받아주지 않을 수 있습니다.
키움 REST API 포털(https://openapi.kiwoom.com)에서 **실전투자용** 앱키/시크릿을 별도로
발급받아 `.env`의 `KIWOOM_APP_KEY` / `KIWOOM_APP_SECRET` 값을 교체해 주세요.

DB 계정(`c##Limdy`)에 접속 권한만 있으면, 처음 실행할 때 `tb_stock_price`, `tb_watchlist`
테이블이 자동으로 생성되고 기본 관심종목 5개(삼성전자, SK하이닉스, NAVER, 카카오, LG화학)가 시딩됩니다.

## 데이터 흐름이 원본과 달라진 점

기존 코드는 공공데이터포털 API(하루치 x 전종목)를 썼기 때문에 "날짜 하나씩 반복 호출"하는
구조였습니다. 키움 REST API의 일봉차트(`ka10081`)는 **종목 1개당 과거 히스토리 전체**를
한 번의 요청(+연속조회)으로 내려주므로, 이제는 "종목 하나씩" 반복 호출하는 구조로 바뀌었습니다.
그래서 화면의 "초기 데이터 적재"는 관심종목 개수만큼만 API를 호출하며, 훨씬 빠르게 끝납니다.

관심종목은 `/api/watchlist` (GET/POST)로 추가할 수 있고, 기본값은 `app/config.py`의
`DEFAULT_CODES`에 있습니다.

## 접근토큰 발급 (au10001) — 확정된 스펙 반영

- `POST {도메인}/oauth2/token`, `Content-Type: application/json;charset=UTF-8`
- 요청: `{"grant_type": "client_credentials", "appkey": ..., "secretkey": ...}`
- 응답: `{"expires_dt": "YYYYMMDDHHMMSS", "token_type": "bearer", "token": "...", "return_code": 0, "return_msg": "..."}`

`kiwoom_client.py`는 이 스펙에 맞춰 `return_code`가 0이 아니면 `return_msg`를 그대로 예외로
던지고, `expires_dt`를 실제 만료 시각으로 파싱해서 그 60초 전까지만 토큰을 재사용합니다.
(형식이 다르게 오면 안전하게 30분짜리로 간주하고 재발급합니다.) appkey/secretkey가 비어있거나
틀리면 여기서 바로 에러 메시지로 원인을 알 수 있습니다.

## ⚠️ 꼭 확인해 주세요 — 시세 조회(ka10081) 응답 필드명

키움 REST API는 최근에 새로 열린 인터페이스라, 공개된 문서만으로는 일봉차트 응답의
정확한 JSON 필드명을 100% 확정할 수 없었습니다. `app/services/kiwoom_client.py`의
`_CHART_FIELD_ALIASES`에 가능성이 높은 필드명 후보들을 넣어 방어적으로 파싱하도록
만들어 두었습니다.

앱을 처음 실행하고 "초기 데이터 적재"를 한 번 누르면, 콘솔에
```
ℹ️ [Kiwoom] 일봉차트 응답 샘플 키: [...]
```
로그가 한 번 찍힙니다. 여기 나온 실제 키 이름이 `_CHART_FIELD_ALIASES`의 후보 목록과
다르면, 그 목록에 실제 키를 추가해 주세요. (키움 개발자센터의 `ka10081` 상세 페이지에서도
정확한 필드명을 확인할 수 있습니다: https://openapi.kiwoom.com)

## 스케줄러

평일 18:00(장마감 후)에 관심종목 전체를 자동 갱신하고 지표를 재계산합니다.
(`app/__init__.py`의 `scheduler.add_job(...)` 부분에서 시간 조정 가능)
