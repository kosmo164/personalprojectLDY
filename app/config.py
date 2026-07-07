"""
앱 전역 설정.
.env 파일의 값을 한 곳에서만 읽어들여서, 다른 모듈들은
os.environ을 직접 건드리지 않고 이 Config 객체만 참조하도록 합니다.
"""
import os
from dotenv import load_dotenv

# 프로젝트 루트의 .env를 명시적으로 로드 (실행 위치와 무관하게 항상 같은 파일을 읽음)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BASE_DIR, ".env"))


def _get_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    BASE_DIR = _BASE_DIR

    # --- Flask ---
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")
    DEBUG = _get_bool("FLASK_DEBUG", True)

    # --- Oracle DB ---
    ORACLE_USER = os.environ.get("ORACLE_USER", "")
    ORACLE_PASSWORD = os.environ.get("ORACLE_PASSWORD", "")
    ORACLE_DSN = os.environ.get("ORACLE_DSN", "localhost:1521/xe")
    ORACLE_POOL_MIN = _get_int("ORACLE_POOL_MIN", 2)
    ORACLE_POOL_MAX = _get_int("ORACLE_POOL_MAX", 12)
    ORACLE_POOL_INCREMENT = _get_int("ORACLE_POOL_INCREMENT", 2)

    # --- 키움증권 REST API ---
    KIWOOM_IS_MOCK = _get_bool("KIWOOM_IS_MOCK", False)
    KIWOOM_APP_KEY = os.environ.get("KIWOOM_APP_KEY", "")
    KIWOOM_APP_SECRET = os.environ.get("KIWOOM_APP_SECRET", "")

    # KIWOOM_IS_MOCK=False(기본값) -> 실전 도메인, True -> 모의투자 도메인으로 자동 전환
    KIWOOM_BASE_URL = (
        "https://mockapi.kiwoom.com" if KIWOOM_IS_MOCK else "https://api.kiwoom.com"
    )

    # --- 백필/스케줄러 ---
    BACKFILL_WORKERS = _get_int("BACKFILL_WORKERS", 4)

    # 화면 "빠른 선택" 칩에 쓸 기본 종목 (DB가 비어있을 때도 무언가 보여주기 위함)
    DEFAULT_CODES = [
        {"srtn_cd": "005930", "itms_nm": "삼성전자"},
        {"srtn_cd": "000660", "itms_nm": "SK하이닉스"},
        {"srtn_cd": "035420", "itms_nm": "NAVER"},
        {"srtn_cd": "035720", "itms_nm": "카카오"},
        {"srtn_cd": "051910", "itms_nm": "LG화학"},
    ]


config = Config()
