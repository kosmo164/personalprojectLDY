"""
최초 실행 시 필요한 테이블을 자동으로 생성합니다.
테이블이 없으면 이후 모든 조회/적재가 조용히 실패하는 문제를 막기 위한 안전장치입니다.
"""
from app.db.pool import get_connection

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


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        "SELECT COUNT(*) FROM user_tables WHERE table_name = :t",
        {"t": table_name},
    )
    return cursor.fetchone()[0] > 0


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
