"""
앱 전역 설정.
.env 파일의 값을 한 곳에서만 읽어들여서, 다른 모듈들은
os.environ을 직접 건드리지 않고 이 Config 객체만 참조하도록 합니다.
"""
'''
운영체제(OS)의 기능에 접근할 수 있게 해주는 파이썬 표준 라이브러리. 여기서는 시스템 환경변수
(os.environ)를 조회하거나 컴퓨터 내부의 파일 경로를 계산할때 사용됨.
'''
import os
'''
외부 라이브러리인 python-dotenv에서 제공하는 함수. 프로젝트 루트 디렉터리에 작성된 .env
텍스트 파일을 읽어와 시스템 환경변수로 등록(load)해주는 핵심 도구
'''
from dotenv import load_dotenv

'''
파일경로 및 환경변수 로드뷰
- _BASE_DIR 계산 : 현재 파일(__file__)의 절대경로를 구한 뒤, dirname을 두 번 호출하여
    상위폴더(프로젝트의 루트 디렉터리)위치를 알아냄. 이렇게 하면 터미널에서 어느 폴더에 위치한
    채 프로그램을 실행하더라도, 항상 똑같은 기준점(루트)을 잡을 수 있어 안전
- load_dotenv(...) : 방금 구한 루트 폴더 내의 .env파일 경로를 조합(os.path.join)하여 명시적으로
    로드. 이제 이 아랫줄부터는 .env에 적힌 설정값들을 조회할 수 있게 됨    
'''
# 프로젝트 루트의 .env를 명시적으로 로드 (실행 위치와 무관하게 항상 같은 파일을 읽음)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BASE_DIR, ".env"))

'''
타입변환용 안전장치 함수(유틸리티 함수)
환경변수(os.environ)로 읽어온 값은 무조건 문자열(String)타입. .env에 FLASK_DEBUG=True나
ORACLE_POOL_MIN=2라고 적어두었어도 파이썬은 이를 글자 "True", "2"로 인식. 이를 실제 논리형(bool)
과 정수형(int)데이터 타입으로 안전하게 바꿔주는 헬퍼함수    
'''
'''
문자열을 논리형으로 변환(_get_bool)
- 환경 변수값을 가져와서 만약 비었다면(None)개발자가 지정한 기본값(default)을 반환
- 값이 존재한다면 양끝 공백을 제거(strip())하고 소문자로 통일(lower())을, 아니면 거짓(False)을 
    반환
'''
def _get_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")

'''
문자열을 정수형으로 변환(_get_int)
- 글자로 된 숫자(예: "4")를 파이썬의 정수형 숫자(4)로 변환
- 만약 .env에 실수로 숫자가 아닌 글자(예: "abc")를 적어도어 변환 오류(ValueError, TypeError)가
    발생하더라도, 서버가 뻗지 않고 안전하게 예외 처리(try-except)를 거쳐 지정해둔 기본값(defalut)
    을 반환하도록 방어적으로 설계
'''
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
