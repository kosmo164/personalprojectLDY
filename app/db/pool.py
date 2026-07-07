"""
Oracle 커넥션 풀.

매 호출마다 cx_Oracle.connect()로 새 세션을 여는 대신 풀에서 빌려 씁.
빌린 커넥션의 close()는 실제 세션 종료가 아니라 "풀에 반납"으로 동작함.
"""
import cx_Oracle
from app.config import config

'''
해석 : 커넥션 풀 객체를 담아둘 전역 변수(_pool)를 선언하고 초기 상태로 None을 대입함
의도 : 프로그램이 켜진 후 최초 1회만 풀을 생성하고, 이후에는 이미 ㅁ나들어진 풀을 재사용(싱글턴패턴)
    하기 위한 깃발(Flag)역할을 함. 앞에 붙은 언더바(_)는 외부 모듈에서 접근하지 말고 제공된
    함수를 통해서만 사용하라는 파이썬의 관례(Private)임.
'''
_pool = None


def get_pool() -> cx_Oracle.SessionPool:
    # 함수 내부에서 함수밖에 있는 전ㅇ겨 변수_pool의 값을 수정하겠다고 선언 
    global _pool
    '''
    지연초기화(Lazy Initiallzation)패턴. 프로그램이 시작하자마자 무조건 풀을 만드는게 아닌 실제로 데이터베이스
    조회가 처음 필요해서 이 함수를 호출하는 순간 단 한번 풀을 생성함.
    '''
    if _pool is None:
        '''
        user,password,dns : 오라클 데이터베이스 계정 정보와 접속 주소(Data Source Name)를 설정파일(config)
            로부터 읽어와 연결함.
        min : 풀이 유지할 최소 커넥션 개수. 프로그램이 켜지자마자 미리 오라클 서버와 이 개수만큼 연결을 맺어두고 대기함
        max : 풀이 허용할 최대 커넥션 개수. 동시에 사용자가 몰려도 이 개수를 넘어서 세션을 생성하지 못하게 막아 오라클
            서버가 과부하로 에러나는 것을 방지함.
        increment : 미리 만들어둔 커넥션이 모두 사용 중일 때, 추가로 몇개씩 세션을 늘릴지 결정하는 단위.
        threaded=True : 멀티스레드 환경 안전성(Thread-Safety)활성화. 현재 백필(Backfill)작업이나 Flask 웹 서버가
        여러 스레드를 통해 동시에 이 풀에 접근하더라도 오류가 나지 않돌고 내부적으로 Lock을 걸어 동기화 시킴.         
        '''
        _pool = cx_Oracle.SessionPool(
            user=config.ORACLE_USER,
            password=config.ORACLE_PASSWORD,
            dsn=config.ORACLE_DSN,
            min=config.ORACLE_POOL_MIN,
            max=config.ORACLE_POOL_MAX,
            increment=config.ORACLE_POOL_INCREMENT,
            threaded=True,
        )
    return _pool


def get_connection():
    """풀에서 커넥션을 하나 빌려온다. 사용 후 반드시 close()로 반납할 것."""
    '''풀에서 빌려온 커넥션 객체는 사용자가 사용을 마치고 .close()를 호출하면, 실제로 오라클과의 연결이 끊어지는 것이 
    아니라 풀 안으로 다시 들어가 대기 상태(반납)가 됨. 만약 이를 누수(close를 안함)하면 풀에 자리가 없어 다음 사람
    이 데이터베이스를 쓰지못하고 무한 대기하는 '커넥션 누수(Connection Leak)' 장애가 발생하므로 반드시 자원을 반납해야 함'''
    return get_pool().acquire()
