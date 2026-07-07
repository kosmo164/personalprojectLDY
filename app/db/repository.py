'''
데이터 접근 계층(Repository).
라우트/서비스 코드가 직접 SQL을 작성하지 않도록, 모든 쿼리를 이 모듈에 모아둠.
'''
import warnings
import pandas as pd
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
        cursor.execute('''
            MERGE INTO tb_stock_price t
            USING (
                SELECT
                    srtn_cd, bas_dt,
                    '''
                    
                    '''
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
