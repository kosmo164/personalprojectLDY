'''
데이터 접근 계층(Repository).
라우트/서비스 코드가 직접 SQL을 작성하지 않도록, 모든 쿼리를 이 모듈에 모아둠.
'''
'''
- 역할 : HTTP 상태 코드 중 412 Precondition Failed(전체조건실패)를 나타내는 상수를 가져옴
- 특이사항 : 현재 레포지토리 코드 내에서는 직접 사용되고 있지 않고 향후 특정조건(데이터가 미리
    존재해야하는 조건 등)검증 실패 시 에러를 던지기 위해 선언해 둔 것    
'''
from http.client import PRECONDITION_FAILED
'''
- 역할 : 파이썬 프로그램 실행 중 발생하는 프로그램 구조적 경고(Warning)메세지를 제어하는
    표준 라이브러리.
- 코드 내 사용성 : 주석에 명시된 것처럼 Pandas가 SQLAlchemy가 아닌 순수 오라클 커넥션을
    사용할 때 뿜어내는 호환성 경고(UserWaring)를 콘솔창에 출력하지 않고 조용히 무시(ignore)
    하도록 필터링 설정을 적용하기 위해 가져옴    
'''
import warnings
'''
- 역할 : 대용량 테이블 데이터를 다루는 데 특화된 파이썬 최고의 데이터 분석 라이브러리
- 코드 내 사용성 : 오라클DB에 쿼리를 날려 받아온 원시(Raw)주가 데이터를 표 형태의 객체인 DataFrame
    으로 곧바로 변활할 때 pd.read_sql()함수를 사용함.
'''
import pandas as pd
'''
- 역할 : 프로젝트 내부 다른 모듈(app/db/pool.py)에서 정의된 커넥션풀(Connection Pool)관리 함수
- 코드 내 사용성 : 매번 DB에 무겁게 새로 로그인하는 대신 미리 만들어진 연결 통로를 get_connection()
    으로 빠르게 빌려와 SQL을 실행하고 작업이 끝나면 finally블록을 통해 커넥션을 다시 풀로 반납하는
    방식으로 시스템 자원을 효율적으로 관리
'''
from app.db.pool import get_connection

# pandas가 cx_Oracle 커넥션을 SQLAlchemy가 아니라는 이유로 매번 띄우는 경고.
# 동작에는 영향이 없으므로 콘솔을 깔끔하게 유지하기 위해 무시함.
'''
Pandas라이브러리는 원래 데이터베이스를 연결할 때 무겁고 고도화된 SQLAlchemy라는 도구를
쓰는 것을 권장함. 현재 코드처럼 순수 오라클 커넥션(cx_Oracle)을 넘기면 나중에 지원 중단
될 수 있으니 주의하라는 경고 메세지가 계속 출력되어 콘솔이 지저분해짐. 안전하게 작동하는
것을 확인 후 로그를 강제로 필터링(무시)하는 설정임.
'''
warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy connectable.*",
    category=UserWarning,
)

'''
오라클의 고유 틍징 해결
- 오라클 데이터베이스는 SQL 결과를 줄 때 컬럼명을 무조건 SRTN_CD, ITMS_NM 같이 대문자로 
    변환하여 반환함.
- 이를 그대로 파이썬 딕셔너리로 바꿈녀 프론트엔드나 서비스단에서 소문자 키(srtn_cd)로 값을
    찾을 때(KeyError)가 남. 이 함수는 쿼리를 실행한 즉시 모든 컴럼명을 소문자로 한번에
    청소해줌.     
'''
def _read_sql(query, conn, params=None) -> pd.DataFrame:
    '''pd.read_sql 래퍼.

    cx_Oracle은 컬럼명을 기본적으로 대문자(SRTN_CD 등)로 돌려주기 때문에,
    그대로 두면 df.to_dict()나 딕셔너리 접근에서 'srtn_cd' 같은 소문자 키를
    찾다가 KeyError가 납니다. 여기서 한 번에 소문자로 통일합니다.
    '''
    df = pd.read_sql(query, con=conn, params=params or {})
    df.columns = [str(c).lower() for c in df.columns]
    return df


# --------------------------------------------------------
# 관심종목(watchlist)
# --------------------------------------------------------
def get_watchlist():
    conn = get_connection()
    try:
        df = _read_sql(
            "SELECT srtn_cd, itms_nm FROM tb_watchlist ORDER BY itms_nm", conn
        )
        return df.to_dict(orient="records")
    finally:
        conn.close()


def add_to_watchlist(srtn_cd: str, itms_nm: str = None):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            '''
            MERGE INTO tb_watchlist t
            USING (SELECT :srtn_cd AS srtn_cd, :itms_nm AS itms_nm FROM dual) s
            ON (t.srtn_cd = s.srtn_cd)
            WHEN NOT MATCHED THEN
                INSERT (srtn_cd, itms_nm) VALUES (s.srtn_cd, s.itms_nm)
            WHEN MATCHED THEN
                UPDATE SET t.itms_nm = COALESCE(s.itms_nm, t.itms_nm)
            ''',
            {"srtn_cd": srtn_cd, "itms_nm": itms_nm},
        )
        conn.commit()
        cursor.close()
    finally:
        conn.close()


def get_codes_for_quick_picks(default_codes, limit=40):
    conn = get_connection()
    try:
        df = _read_sql(
            f'''
            SELECT DISTINCT srtn_cd, itms_nm FROM tb_stock_price
            WHERE itms_nm IS NOT NULL
            ORDER BY itms_nm
            FETCH FIRST {int(limit)} ROWS ONLY
            ''',
            conn,
        )
        records = df.to_dict(orient="records")
        return records if records else default_codes
    except Exception:
        return default_codes
    finally:
        conn.close()


# --------------------------------------------------------
# 시세 데이터 적재 (MERGE upsert)
# --------------------------------------------------------
'''
MERGE INTO(Upsert) : 주식 데이터 적재의 핵심임. 매일 수집되는 주가가 이미 DB에 존재하는 날짜/종목이면
    가격이나 거래량을 최신으로 수정(UPDATE)하고, 처음 보는 날짜/종목이면 새로 한줄 추가(INSERT)하는 쿼리문.
cursor.executemany(배치처리) : 수천 행의 추가 데이터를 파이썬 반복문(for)으로 한줄 씩 INSERT하면 네트워크
    트래픽때문에 데이터 적재가 느려짐. 이 함수는 오라클 서번에 대령의 리스트(rows)를 통째로 던져 한 번에 초고속
    처리하돌고 최적화된 기법.    
'''
def upsert_price_rows(rows: list):
    '''rows: dict 리스트. 각 dict는 아래 키를 가져야 함:
    srtn_cd, itms_nm, bas_dt(YYYYMMDD 문자열), clpr, vs, flt_rt, mkp, hipr, lopr, trqu, tr_at
    '''
    if not rows:
        return 0

    conn = get_connection()
    try:
        cursor = conn.cursor()
        sql = '''
            MERGE INTO tb_stock_price d
            USING (
                SELECT
                    :srtn_cd AS srtn_cd, :itms_nm AS itms_nm,
                    TO_DATE(:bas_dt, 'YYYYMMDD') AS bas_dt,
                    :clpr AS clpr, :vs AS vs, :flt_rt AS flt_rt,
                    :mkp AS mkp, :hipr AS hipr, :lopr AS lopr,
                    :trqu AS trqu, :tr_at AS tr_at
                FROM dual
            ) s
            ON (d.srtn_cd = s.srtn_cd AND d.bas_dt = s.bas_dt)
            WHEN MATCHED THEN
                UPDATE SET
                    d.itms_nm = NVL(s.itms_nm, d.itms_nm), d.clpr = s.clpr, d.vs = s.vs,
                    d.flt_rt = s.flt_rt, d.mkp = s.mkp, d.hipr = s.hipr, d.lopr = s.lopr,
                    d.trqu = s.trqu, d.tr_at = s.tr_at
            WHEN NOT MATCHED THEN
                INSERT (srtn_cd, itms_nm, bas_dt, clpr, vs, flt_rt, mkp, hipr, lopr, trqu, tr_at)
                VALUES (s.srtn_cd, s.itms_nm, s.bas_dt, s.clpr, s.vs, s.flt_rt, s.mkp, s.hipr, s.lopr, s.trqu, s.tr_at)
        '''
        cursor.executemany(sql, rows)
        conn.commit()
        count = cursor.rowcount
        cursor.close()
        return count
    finally:
        conn.close()


# --------------------------------------------------------
# 지표 일괄 재계산 (이동평균 20일 + 볼린저 밴드)
# Oracle 윈도우 함수로 "전 종목 x 전 기간"을 단 한 번의 SQL로 재계산
# --------------------------------------------------------
def recompute_all_indicators():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        '''
        PARTITION BY srtn_cd : 여러 종목이 섞여 있는 전체 테이블에서 종목별로 데이터를 그룹핑함.
        (주식끼리 데이터가 꼬이지 않게 처리)
        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW : 앞의 19일과 현재 1일을 합쳐 총 20일의 데이터
        범위를 뜻함. 주식시장이 열리는 알을 기준으로 완벽히 움직이는 윈도우 범위
                    
        이를 통해 20일 이동평균선(ma_20)과 표준편차(std_20)를 구하고, 하단에서 볼린저 밴드 공식인 $ma_20\
        pm(std_20\times2)$를 조립하여 tb_stock_price 테이블에 일괄 업데이트 함.
                    
        데이터가 부족한 상위1~19일 차 데이터는 조건절(s.cnt_20 = 20)을 통해 안전하게 계산에서 제외(null유지)시킴.    
        '''
        cursor.execute('''
            MERGE INTO tb_stock_price t
            USING (
                SELECT
                    srtn_cd, bas_dt,
                    AVG(clpr)    OVER (PARTITION BY srtn_cd ORDER BY bas_dt
                                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma_20,
                    STDDEV(clpr) OVER (PARTITION BY srtn_cd ORDER BY bas_dt
                                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS std_20,
                    COUNT(*)     OVER (PARTITION BY srtn_cd ORDER BY bas_dt
                                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS cnt_20
                FROM tb_stock_price
            ) s
            ON (t.srtn_cd = s.srtn_cd AND t.bas_dt = s.bas_dt AND s.cnt_20 = 20)
            WHEN MATCHED THEN UPDATE SET
                t.ma_20 = s.ma_20,
                t.bollinger_up = s.ma_20 + (s.std_20 * 2),
                t.bollinger_down = s.ma_20 - (s.std_20 * 2)
        ''')
        updated = cursor.rowcount
        conn.commit()
        cursor.close()
        return updated
    finally:
        conn.close()


# --------------------------------------------------------
# 조회
# --------------------------------------------------------
def get_latest_snapshot(srtn_cd: str) -> pd.DataFrame:
    conn = get_connection()
    try:
        '''
        ROW_NUMBER() OVER (...) : 기계학습(머신러닝)이나 수학적 선형 회귀 분석(Linear Regression)을 돌리려면 
        X축(독립 변수)역할로 쓸 연속된 숫자 시간축이 필요함.
        
        주식시장은 주말이나 공휴일에 쉬기 때문에 날짜 데이터를 타임스탬프로 쓰면 공백이 생겨 수학 계산이 틀어짐.
        날짜가 오래된 순서대로 정렬하여 1, 2, 3, 4...형태로 순차적인 주식 영업일 인덱스(day_seq)를 임의로 부여함
        '''
        query = '''
            SELECT * FROM (
                SELECT srtn_cd, itms_nm, TO_CHAR(bas_dt, 'YYYY-MM-DD') as bas_dt,
                       clpr, flt_rt, ma_20, bollinger_up, bollinger_down
                FROM tb_stock_price
                WHERE srtn_cd = :srtn_cd
                ORDER BY bas_dt DESC
            ) WHERE ROWNUM = 1
        '''
        return _read_sql(query, conn, {"srtn_cd": srtn_cd})
    finally:
        conn.close()


def get_price_history(srtn_cd: str) -> pd.DataFrame:
    conn = get_connection()
    try:
        query = '''
            SELECT TO_CHAR(bas_dt, 'YYYY-MM-DD') as bas_dt, clpr, ma_20, bollinger_up, bollinger_down
            FROM tb_stock_price
            WHERE srtn_cd = :srtn_cd
            ORDER BY bas_dt ASC
        '''
        return _read_sql(query, conn, {"srtn_cd": srtn_cd})
    finally:
        conn.close()


def get_close_series_for_regression(srtn_cd: str) -> pd.DataFrame:
    conn = get_connection()
    try:
        query = '''
            SELECT clpr, ROW_NUMBER() OVER (ORDER BY bas_dt ASC) as day_seq
            FROM tb_stock_price
            WHERE srtn_cd = :srtn_cd
            ORDER BY bas_dt ASC
        '''
        return _read_sql(query, conn, {"srtn_cd": srtn_cd})
    finally:
        conn.close()
