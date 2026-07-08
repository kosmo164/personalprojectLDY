"""
키움증권 REST API 클라이언트.

- 앱키/시크릿으로 접근토큰을 발급받아 캐싱하고, 만료 전에만 재발급.
- 국내주식 일봉차트조회(TR: ka10081)로 종목별 일자별 시세를 가져옴.
"""
'''
- threading : 멀티스레드 환경에서 안전하게 토큰을 관리하기 위해 가져옴. 동시 요청이 들어올때 
    여러 스레드가 동시에 토큰을 재발급받으려고 충돌하는 것을 반지하는 락(Lock)장치에 쓰임
- time/datetime : 토큰 만료 시간 계산 및 연속 조회(페이지네이션)시 429에러(과도한 요청차단)
    를 피하기 위한 시간지연(time.sleep)연산에 사용
- requests : 키움증권 REST API API 서버에 실제 http요청(POST)을 보내기 위한 파이썬의 
    대표적인 HTTP통신 라이브러리임.        
'''
import os
import sys
import threading
import time
from datetime import datetime
import requests

# 절대 경로 실행 대비 경로 등록
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from app.config import config

_TOKEN_ENDPOINT = "/oauth2/token"
_CHART_ENDPOINT = "/api/dostk/chart"
_CHART_TR_ID = "ka10081"  # 주식일봉차트조회요청


class KiwoomAuthError(Exception):
    pass

'''
클래스 구조 및 초기화(__init__)
- 싱글턴스타일 : 앱전체에서 키움증권 서버와의 통로를 단 하나만 만들어 공유하도록 설계됨
- self._lock = threading.Lock() : 멀티스레드 세이프(Thread-Safe)를 보장하는 자물쇠임.
    토큰이 만료되어 갱신하는 순간에 단 하나의 스레드만 갱신작업을 수행하도록 통제함.
'''
class KiwoomClient:
    """앱 전체에서 하나만 생성해서 재사용하는 싱글턴 스타일 클라이언트."""

    def __init__(self, app_key: str, app_secret: str, base_url: str):
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_url = base_url.rstrip("/")
        self._token = None
        self._token_expires_at = 0  # epoch seconds
        self._lock = threading.Lock()
        self._logged_sample_keys = False  # 최초 1회만 응답 키를 로그로 남기기 위한 플래그

    # ----------------------------------------------------
    # 인증 — au10001 (접근토큰 발급)
    # ----------------------------------------------------
    '''
    스마트 토큰 발급 및 캐싱 시스템
    - secretkey 필드를 사용해 키움 서버에 토큰 발급 요청을 보냄
    - 토큰 발급이 성공하면 access_token을 가져오고, _parse_expires_dt함수를 통해 만료 시간을
        Epoch초(초 단위 유닉스 타임스탬프)로 변환해 메모리(self._token_expires_at)에 지정함.
        이때 네트워크 지연 등을 고려해 안전하게 만료 60초전(-60)을 기준으로 잡음.
    '''
    def _issue_token(self):
        if not self.app_key or not self.app_secret:
            raise KiwoomAuthError(
                "KIWOOM_APP_KEY / KIWOOM_APP_SECRET이 설정되지 않았습니다. .env를 확인 합니다."
            )

        url = f"{self.base_url}{_TOKEN_ENDPOINT}"

        # 💡 [수정]: 키움증권 au10001 공식 명세인 'secretkey'로 다시 변경.
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.app_secret,  # ➔ 기존 appsecretkey에서 복구
        }

        resp = requests.post(
            url,
            headers={"Content-Type": "application/json;charset=UTF-8"},
            json=payload,
            timeout=10,
        )

        if not resp.ok:
            raise KiwoomAuthError(
                f"토큰 발급 실패 (HTTP {resp.status_code}): {resp.text[:300]}"
            )

        data = resp.json()

        # 키움증권 엑세스 토큰 필드명인 'access_token'과 기존 'token'을 상호 보완 파싱 처리
        token = data.get("access_token") or data.get("token")
        if not token:
            raise KiwoomAuthError(
                f"토큰 발급 응답에 access_token 필드가 없습니다: {data}"
            )

        self._token = token
        # 키움 만료 필드명(expired_in 등)에 맞춰 안전 유효값 처리
        self._token_expires_at = self._parse_expires_dt(
            data.get("expires_dt") or data.get("expired_in")
        )
        return token

    @staticmethod
    def _parse_expires_dt(expires_dt) -> float:
        """expires_dt 처리기"""
        if expires_dt:
            try:
                dt = datetime.strptime(str(expires_dt), "%Y%m%d%H%M%S")
                return dt.timestamp() - 60
            except ValueError:
                pass
        return time.time() + (30 * 60) - 60

    '''
    호율적인자원관리 : 시세를 조회할 때마다 매번 토큰을 발급받으면 서버가 차단됨. 이 함수는
    메모리를 확인하여 "기존 토큰이 있고, 아직 만료 시간 전이라면"로그인을 건너뛰고 기존 토큰을
        그대로 재사용(캐싱)함. 락(with self._lock)덕분에 안전하게 보호됨.
    '''
    def _get_valid_token(self):
        """토큰을 무조건 새로 받아오지 않고 캐싱된 토큰을 안전하게 재사용합니다."""
        with self._lock:
            if self._token and time.time() < self._token_expires_at:
                return self._token
            return self._issue_token()

    # ----------------------------------------------------
    # 시세 조회
    # ----------------------------------------------------
    '''
    데이터 별칭 처리 및 정규화(Data Normalization)
    - 문제해결 : 키움 API는 버전에 따라, 혹은 실서버와 모의투자 서버에 따라 똑같은 '종가' 데이터를
        clpr로 주기도 하고 cur_prc나 close_pric로 주기도 하는 불일치 문제가 있음
    - 해결책 : 매핑 리스트를 정의해 두고 _first_present() 함수를 통해 리스트에 선언된 키 중 매칭되는
        첫 번째 값을 유연하게 추출하도록 만듬. 덕분에 외부 API규격이 조금 바뀌더라도 내부 시스템 코드가 
        에러로 터지는 것을 완벽하게 방어함.   
    '''
    _CHART_FIELD_ALIASES = {
        "date": ["dt", "date", "stk_dt", "trd_dt", "bas_dt"],
        "close": ["cur_prc", "clpr", "close_pric", "stk_prc"],
        "open": ["open_pric", "mkp", "opng_pric"],
        "high": ["high_pric", "hipr"],
        "low": ["low_pric", "lopr"],
        "volume": ["trde_qty", "trqu", "acml_vol"],
        "value": ["trde_prica", "tr_at", "acml_tr_pbmn"],
    }

    @staticmethod
    def _first_present(row: dict, keys: list):
        for k in keys:
            if k in row and row[k] not in (None, ""):
                return row[k]
        return None

    def _extract_chart_rows(self, raw_json: dict):
        candidate_list = None
        for value in raw_json.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                candidate_list = value
                break

        if candidate_list is None:
            return []

        if not self._logged_sample_keys:
            print(
                f"ℹ️ [Kiwoom] 일봉차트 응답 샘플 키: {list(candidate_list[0].keys())}"
            )
            self._logged_sample_keys = True

        normalized = []
        for row in candidate_list:
            date_val = self._first_present(row, self._CHART_FIELD_ALIASES["date"])
            close_val = self._first_present(row, self._CHART_FIELD_ALIASES["close"])
            if not date_val or close_val is None:
                continue
            normalized.append(
                {
                    "bas_dt": str(date_val).replace("-", "")[:8],
                    "clpr": abs(int(float(close_val))),
                    "mkp": abs(
                        int(
                            float(
                                self._first_present(
                                    row, self._CHART_FIELD_ALIASES["open"]
                                )
                                or 0
                            )
                        )
                    ),
                    "hipr": abs(
                        int(
                            float(
                                self._first_present(
                                    row, self._CHART_FIELD_ALIASES["high"]
                                )
                                or 0
                            )
                        )
                    ),
                    "lopr": abs(
                        int(
                            float(
                                self._first_present(
                                    row, self._CHART_FIELD_ALIASES["low"]
                                )
                                or 0
                            )
                        )
                    ),
                    "trqu": abs(
                        int(
                            float(
                                self._first_present(
                                    row, self._CHART_FIELD_ALIASES["volume"]
                                )
                                or 0
                            )
                        )
                    ),
                    "tr_at": abs(
                        int(
                            float(
                                self._first_present(
                                    row, self._CHART_FIELD_ALIASES["value"]
                                )
                                or 0
                            )
                        )
                    ),
                }
            )
        return normalized

    '''
    일봉차트연속조회(get_daily_chart)
    - 키움증권의 ka10081 TR을 사용하여 특정 종목의 일봉 데이터를 요청함. adjusted=True 세팅을
        통해 권리락이나 배당락이 반여왿ㄴ 수정주가를 가져옴
    - 연속조회알고리즘(Pagination) :
        1. 일봉 데이터는 한 번의 요청으로 과거 전체를 다 가져올 수 없으므로 여러 페이지로 쪼개져
            서 옵니다.
        2. 요청 후 응답 헤더(headers)를 열어보아 cont-yn(다음 페이지 존재 여부)값이 "Y"이고
            next-key가 존재하면, 그 값을 다음 요청 헤더에 실어서 끊임없이 다음 페이지를 요청
        3. 속도 제한 페치 : 루프를 돌며 연속 조회를 요청할 때, 키움 서버가 디도스로 오인하여 요청을
            거부하는 것을 막기 위해 2.5초의 대기시간(time.sleep(2.5))을 강제로 부여
        4. 수집된 개별 페이지 데이터들은 all_rows.extend()를 통해 하나의 거대한 리스트로 결합되어
            최종 반환됨            
    '''
    def get_daily_chart(
        self, srtn_cd: str, base_dt: str = "00000000", adjusted: bool = True
    ):
        """종목 하나의 일봉 데이터를 조회한다. 연속조회(페이지네이션)를 자동 처리."""
        token = self._get_valid_token()
        url = f"{self.base_url}{_CHART_ENDPOINT}"

        all_rows = []
        cont_yn = "N"
        next_key = ""
        max_pages = 10  # 무한루프 방지 안전장치

        for i in range(max_pages):
            # 💡 [핵심 패치]: 한 종목의 과거 데이터를 연속으로 가져올 때(페이지네이션),
            # 대기 시간을 2.5초로 늘려 429 에러를 완벽하게 차단합니다.
            if i > 0:
                time.sleep(2.5)

            headers = {
                "Content-Type": "application/json;charset=UTF-8",
                "authorization": f"Bearer {token}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "api-id": _CHART_TR_ID,
                "cont-yn": cont_yn,
                "next-key": next_key,
            }
            body = {
                "stk_cd": srtn_cd,
                "base_dt": base_dt,
                "upd_stkpc_tp": "1" if adjusted else "0",
            }

            resp = requests.post(url, headers=headers, json=body, timeout=15)

            if resp.status_code == 401:
                # 토큰 만료/무효 -> 1회 재발급 후 재시도
                token = self._issue_token()
                continue

            resp.raise_for_status()
            data = resp.json()

            return_code = data.get("return_code")
            if return_code is not None and return_code != 0:
                raise KiwoomAuthError(
                    f"[{srtn_cd}] 일봉차트 조회 실패: {data.get('return_msg', '알 수 없는 오류')} "
                    f"(return_code={return_code})"
                )

            all_rows.extend(self._extract_chart_rows(data))

            cont_yn = resp.headers.get("cont-yn", "N")
            next_key = resp.headers.get("next-key", "")
            if cont_yn != "Y" or not next_key:
                break

        return all_rows


# 앱 전체에서 설정에 기반해 공유하는 싱글턴 인스턴스
# .env 설정 키 구조(KIWOOM_APP_KEY, KIWOOM_APP_SECRET) 매핑 완료
'''
코드 최하단에서는 환경 설정 파일(config)의 KIWOOM_IS_MOCK 변수를 확인하여, 테스트 환경일 때는 
모의투자 api주소(mockapi)를 바라보고, 운영 환경일때는 실거래 API주소(api)를 자동으로 조준하도록 생성해줌
'''
kiwoom_client = KiwoomClient(
    app_key=config.KIWOOM_APP_KEY,
    app_secret=config.KIWOOM_APP_SECRET,
    base_url=(
        "https://mockapi.kiwoom.com"
        if getattr(config, "KIWOOM_IS_MOCK", True)
        else "https://api.kiwoom.com"
    ),
)

'''
해당 코드 모듈은 외부 증권사 API와 통신할 때 발생하는 가장 까다로운 세 가지 문제를 해결하는 보일러플레이트
(통신 뼈대)코드임

1. 인증처리 : 토큰 만료 시간을 체크하여 알아서 갱신하는 자동화
2. 속도제한 : time.sleep(2.5)를 통한 안정적인 트래픽 조절(DDoS 차단 방지)
3. 데이터 표준화 : 별칭(Aliases) 사전 구조를 통한 지저분한 API필드명의 소문자 정문화 및 형변환 기법 수립
'''


