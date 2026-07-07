"""
키움증권 REST API 클라이언트.

- 앱키/시크릿으로 접근토큰을 발급받아 캐싱하고, 만료 전에만 재발급합니다.
- 국내주식 일봉차트조회(TR: ka10081)로 종목별 일자별 시세를 가져옵니다.
"""

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
    def _issue_token(self):
        if not self.app_key or not self.app_secret:
            raise KiwoomAuthError(
                "KIWOOM_APP_KEY / KIWOOM_APP_SECRET이 설정되지 않았습니다. .env를 확인해주세요."
            )

        url = f"{self.base_url}{_TOKEN_ENDPOINT}"

        # 💡 [수정]: 키움증권 au10001 공식 명세인 'secretkey'로 다시 변경합니다.
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

    def _get_valid_token(self):
        """토큰을 무조건 새로 받아오지 않고 캐싱된 토큰을 안전하게 재사용합니다."""
        with self._lock:
            if self._token and time.time() < self._token_expires_at:
                return self._token
            return self._issue_token()

    # ----------------------------------------------------
    # 시세 조회
    # ----------------------------------------------------
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
kiwoom_client = KiwoomClient(
    app_key=config.KIWOOM_APP_KEY,
    app_secret=config.KIWOOM_APP_SECRET,
    base_url=(
        "https://mockapi.kiwoom.com"
        if getattr(config, "KIWOOM_IS_MOCK", True)
        else "https://api.kiwoom.com"
    ),
)
