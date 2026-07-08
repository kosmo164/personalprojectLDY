"""
최초 실행 시 필요한 테이블을 자동으로 생성함.
테이블이 없으면 이후 모든 조회/적재가 조용히 실패하는 문제를 막기 위한 안전장치임.
"""
'''
from app.db.pool
- 프로젝트 내부 패키지 구조에서 app폴더 아래, 데이터베이스(db)관련 설정을 모아둔 폴더 내의 pool.py
    (혹은 pool/패키지)모듈을 가리킴
import get_connection
- 해당 모듈로부터 커넥션 풀을 제어하여 DB 연결 객체를 꺼내오는 함수인 get_connection을 현재
    스크립트로 가져옴    
'''
from app.db.pool import get_connection
'''
TB_STOCK_PRICE (시세 데이터 테이블)
- TB_STOCK_PRICE (시세 데이터 테이블) : 표준 종목코드(예: A005930)를 저장하기 위한 문자열 컬럼임.
- bas_dt DATE : 주가의 기준 일자입니다. 오라클의 DATE 타입은 날짜와 시분초를 모두 가짐.
- clpr ~ bollinger_down NUMBER : 종가, 대비, 등락률, 시가, 고가, 저가, 거래량, 거래대금, 그리고
    20일 이동평균선과 볼린저 밴드 상/하단까지 모두 오라클의 가변 정밀도 숫자 타입인 NUMBER로 설계됨.
- CONSTRAINT pk_tb_stock_price PRIMARY KEY (srtn_cd, bas_dt) :
    매우 중요한 복합 기본키(Composite Primary Key)설정임. 주식데이터는 같은 종목이어도 날짜가 다르면
    여러 행이 존재하므로,[종목코드+날짜]가 묶여서 유일한 한 행을 식별하게 만듬. 이로 인해 같은 종목의
    같은 날짜 데이터가 중복으로 들어오는 것을 원천 차단함.        
TB_WATCHLIST (관심종목 테이블)
- srtn_cd VARCHAR2(12) : 관심 종목의 코드가 들어가며, 이 테이블의 기본키(Primary Key). 즉, 관심종목
    리스트에는 동일한 종목이 중복으로 등록될 수 없음.
- created_at DATE DEFAULT SYSDATE : 관심종목 등록 시간이며, 별도 값을 주지 ㅇ낳으면 오라클의 현재
    시간(SYSDATE)이 자동으로 입력됨.     
-     
'''
_TABLES = {
    "TB_STOCK_PRICE": """
        CREATE TABLE tb_stock_price (
            srtn_cd        VARCHAR2(12)  NOT NULL,
            itms_nm        VARCHAR2(100),
            bas_dt         DATE          NOT NULL,
            clpr           NUMBER,
            vs             NUMBER,
            flt_rt         NUMBER,
            mkp            NUMBER,
            hipr           NUMBER,
            lopr           NUMBER,
            trqu           NUMBER,
            tr_at          NUMBER,
            ma_20          NUMBER,
            bollinger_up   NUMBER,
            bollinger_down NUMBER,
            CONSTRAINT pk_tb_stock_price PRIMARY KEY (srtn_cd, bas_dt)
        )
    """,
    "TB_WATCHLIST": """
        CREATE TABLE tb_watchlist (
            srtn_cd    VARCHAR2(12) NOT NULL,
            itms_nm    VARCHAR2(100),
            created_at DATE DEFAULT SYSDATE,
            CONSTRAINT pk_tb_watchlist PRIMARY KEY (srtn_cd)
        )
    """,
}

'''
- 오라클 데이터베이스의 메타데이터 뷰인 user_tables에서 현재 접속한 사용자가 가지고 있는
    테이블 줄 table_name과 일치하는 테이블이 있는지 개수(COUNT)를 셈.
- 개수가 0보다 크면 True(존재함), 0이면 False(존재하지 않음)를 반환함. 이미 존재하는
    테이블을 다시 만들려고 할 때 발생하는 에러를 예방하는 안전장치     
'''
def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        "SELECT COUNT(*) FROM user_tables WHERE table_name = :t",
        {"t": table_name},
    )
    return cursor.fetchone()[0] > 0

'''
주요 로직 흐름
1. 안전한 연결 관리 : try...except...finally 구조를 사용하여, 작업 중 에러가 발생하더라도
    finally블록을 통해 무조건 conn.close()가 실행되도도록 하여 DB연결 자원 누수(Memory Leak)
    를 방지
2. 멱등성(Idempotency)보장 : 함수를 여러번 실행하더라도 이미 테이블이 있거나 이미 데이터가 있다면
    기존 데이터를 해치지 않고 조용히 넘어가므로, 시스템 향상 안정적인 상태를 유지하게 함.
3. 성능 최적화 : 기본 종목 리스트를 넣을 때 execute를 반복문으로 돌리지 않고 executemany를 
    사용하여 한번에 네트워크 타임아웃이나 부하없이 효율적으로 데이터를 다량 삽입(Bulk Insert)함.     
'''
def init_db(default_codes=None):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for table_name, ddl in _TABLES.items():
            if not _table_exists(cursor, table_name):
                cursor.execute(ddl)
                conn.commit()
                print(f"✅ {table_name} 테이블을 새로 생성했습니다.")

        if default_codes:
            cursor.execute("SELECT COUNT(*) FROM tb_watchlist")
            if cursor.fetchone()[0] == 0:
                cursor.executemany(
                    """
                    INSERT INTO tb_watchlist (srtn_cd, itms_nm)
                    VALUES (:srtn_cd, :itms_nm)
                    """,
                    default_codes,
                )
                conn.commit()
                print(f"✅ 기본 관심종목 {len(default_codes)}개를 등록했습니다.")

        cursor.close()
    except Exception as e:
        print(f"❌ 테이블 초기화 중 오류: {str(e)}")
    finally:
        conn.close()
