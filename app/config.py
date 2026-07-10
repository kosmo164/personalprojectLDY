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

'''
중앙설정클래스정의(class Config)
- 시스템 모든 구성 요소를 그룹화하여 깔끔하게 정리해 둔 클래스임. 다른 모듈들은 이 클래스 하나만 바라보고 
    설정을 가져다 씀    
'''
'''
기본 및 Flask 설정
- SECRET_KEY : 세션암호화, 토스트 메시지나 보안 서명 등에 쓰이는 비밀키. 외부 노출을 막기 위해 환경 변수에서
    가져오되, 없을 경우 개발용 임시키("dev-secret-key")를 씀
- DEBUG : Flask의 디버그 모드 활성화 여부. 개발 중에는 오류 메시지를 상세히 보기 위해 True로 두지만, 실서버 배포
    시에는 .env를 통해 False로 바꿀 수 있게 유연성을 부여    
'''
class Config:
    BASE_DIR = _BASE_DIR

    # --- Flask ---
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")
    DEBUG = _get_bool("FLASK_DEBUG", True)

    '''
    오라클 데이터베이스 연결 설정
    - 데이터베이스 접속 정보와 주소(DSN)를 관리
    - 사용자가 몰릴 때 DB 연결 통로를 효율적으로 쪼개고 늘리기 위한 커넥션 풀(Connection Pool)옵션(MIN, MAX,
        INCREMENT)을 정수형으로 관리
    '''
    # --- Oracle DB ---
    ORACLE_USER = os.environ.get("ORACLE_USER", "")
    ORACLE_PASSWORD = os.environ.get("ORACLE_PASSWORD", "")
    ORACLE_DSN = os.environ.get("ORACLE_DSN", "localhost:1521/xe")
    ORACLE_POOL_MIN = _get_int("ORACLE_POOL_MIN", 2)
    ORACLE_POOL_MAX = _get_int("ORACLE_POOL_MAX", 12)
    ORACLE_POOL_INCREMENT = _get_int("ORACLE_POOL_INCREMENT", 2)

    '''
    키움증권 REST API 연동 및 도메인 스위칭 설정
    - API 인증에 필요한 앱 키와 시크릿 코드를 가져옴
    - 스위칭 로직 : KIWOOM_IS_MOCK 변수가 True(모의투자 모드)인지 False(실전투자 모드)인지에 따라 삼항 연산자
        를 통해 실제 키움증권 API요청을 보낼 목적지 주소(KIWOOM_BASE_URL)를 알아서 스위칭(전환)해 주는 영리한
        코드가 포함됨
    '''
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
    '''
    시스템 스케줄러 및 기본 데이터베이스 시딩 세팅
    - BACKFILL_WORKERS : 과거 데이터를 대량 적재할 때 동시처리를 수행할 백그라운드 일꾼(스레드/프로세스)의
        개수를 정의
    - DEFAULT_CODES : 대시보드가 처음 구동되어 데이터베이스가 비어있을때도 사용자가 즉시 채감해 볼 수
        있도록, 화면에 '빠른 선택 칩(Quick Picks)' 리스트와 DB 초기화 시 자동으로 채워넣을 국내 대표 
        우량주 5종의 코드와 이름 데이터를 하드코딩 형태로 안전 자산처럼 취급     
    '''
    DEFAULT_CODES = [
        {"srtn_cd": "005930", "itms_nm": "삼성전자"},
        {"srtn_cd": "000660", "itms_nm": "SK하이닉스"},
        {"srtn_cd": "035420", "itms_nm": "NAVER"},
        {"srtn_cd": "035720", "itms_nm": "카카오"},
        {"srtn_cd": "051910", "itms_nm": "LG화학"},
    ]

'''
인스턴스 생성 및 배포(config = Config())
- 청사진 역할을 Config클래스를 기반으로, 실제 메모리에 올린 단 하나의 설정 인스턴스 객체(config)를 생성
- 이제 다른 파이썬 파일에서는 복잡하게 환경 변수를 건드릴 필요없이 오직 from app.config import config
    문구하나만 실행하여 config.ORACLE_USER, config.KIWOOM_BASE_URL과 같이 마침표(.)하나로 모든
    세팅값에 깔끔하게 접근할 수 있게 됨
'''
config = Config()
