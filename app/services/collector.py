"""
[기능] 시세 수집

키움 REST API의 일봉차트(ka10081)는 종목 1개당 "과거 히스토리 전체"를
한 번의 요청(+연속조회)으로 돌려줍니다. 

- collect_stock(): 종목 1개의 히스토리를 가져와 DB에 upsert
- run_daily_job(): 스케줄러가 매일 호출하는 진입점 (관심종목 전체 갱신 + 지표 재계산)
- run_backfill(): 관심종목 전체에 대해 초기 적재를 수행하고 진행 상황을 backfill_status에 기록
"""
'''
기반 설정 및 임포트 구문(import)
- os/sys : 파이썬 실행 환경과 시스템 경로를 제어하는 표준 라이브러리
    sys.path.append(...) 구문을 통해 이 스크립트가 프로젝트 루트 외부나 테미널에서 단독 실행되더라도
    내부 패키지(app.config, app.db 등)를 찾지 못해 발생하는 ModuleNotFoundError를 원천 차단
- threading : 멀티스레딩을 지원. 대량의 과거 데이터를 가져오는 작업(백필)이 실행되는 동안 웹 서버가 멈추지
    않고 배경(Background)에서 비동기로 일하도록 새 스레드를 만들 때 사용함.
- time : 시간지연(time.sleep)을 주기 위해 가져옴. 증권사 API 서버에 짧은 시간 동안 너무 많은 요청을
    보내면 IP차단(429 Too Many Requests)을 당하므로, 중간중간 의도적인 휴식기를 주기 위함임.        
'''
import os
import sys
import threading
import time

# 절대 경로 실행 시 ModuleNotFoundError 방지를 위한 시스템 경로 설정
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

'''
프로젝트 내부의 전역 설정(config), DB접근 클래스(repository), 보조지표 계산기(recompute_all_indicators),
그리고 키움증원 서버와 실제 통신하여 raw 데이터를 가져오는 API클라이언트(kiwoom_client)를 연결함.
'''
from app.config import config
from app.db import repository
from app.services.indicators import recompute_all_indicators
from app.services.kiwoom_client import kiwoom_client

# 프론트에서 폴링하여 진행률을 보여주기 위한 전역 상태
'''
웹 프론트엔드 화면에서 "현재 과거 데이터 적재가 몇 % 진행 중인가?"를 실시간 프로그래스 바(Progress Bar)로
보여줄 수 있도록 상태를 기록하는 딕셔너리임. 
'''
backfill_status = {
    "running": False,
    "done": 0,
    "total": 0,
    "current_code": None,  # 프론트엔드 연동용 기존 키 유지
    "last_message": None,
}

'''
단일 종목 시세 수집 및 데이터 정제(collect_stock)
- 키움 API에서 한 종목의 과거 전체 데이터를 받아와 가공한 뒤 DB에 적재함
1. 데이터정렬 : 외부 API에서 주는 데이터는 날짜 순서가 뒤죽박죽일 수 있음. 대비(vs)와 등락률(fit_rt)을 
    정확히 계산하기 위해 날짜(bas_df 혹은 dt)를 기준으로 오래된 날짜부터 최신 날짜 순으로 정렬함.
2. 유연한 데이터 대응(Data Normalization) : API가 제공하는 키 이름이 clpr이든 cur_prc(현재가)이든,
    혹은 mkp이든 open_price(시가)이든 상관없이 양쪽 다 대응 할 수 있도록 get()예외 처리가 꼼꼼하게 되어 
    있음.
3. 안전한 숫자 변환 : 오라클DB 문자열 컬럼에 들어갈 수 있도록 부호나 소수점을 제거하기 위해 abs(int(float(...)))
    처리를 거침.
4. 파생변수계산 :
    - 당일 종가ㅇ서 직전 영업일 종가(prev_close)를 빼서 대비(vs)를 구함
    -계산된 대비를 바탕으로 등락률(flt_rt)을 소수점 둘째자리까지 계산함
5. 배치 적재 : 가공 완료된 딕셔너리 리스트(db_rows)를 통째로 repository.upsert_price_rows()에 넘겨
    대량으로 DB에 저장함(Upsert)
'''
def collect_stock(srtn_cd: str, itms_nm: str = None) -> int:
    """종목 하나의 전체 히스토리를 조회해서 upsert. 반환값: upsert된 행 수."""
    raw_rows = kiwoom_client.get_daily_chart(srtn_cd)
    if not raw_rows:
        return 0

    db_rows = []

    # 오래된 날짜 -> 최신 날짜 순 정렬 (정규화된 키 'bas_dt' 또는 키움 원본 키 'dt' 대응)
    try:
        raw_rows.sort(key=lambda r: r.get("bas_dt") or r.get("dt") or "")
    except Exception:
        pass

    prev_close = None

    for r in raw_rows:
        raw_date = r.get("bas_dt") or r.get("dt")
        if not raw_date:
            continue

        bas_dt = str(raw_date).replace("-", "")[:8]

        raw_clpr = (
            r.get("clpr") if r.get("clpr") is not None else r.get("cur_prc")
        )
        if raw_clpr is None:
            continue

        clpr = abs(int(float(raw_clpr)))

        vs = (clpr - prev_close) if prev_close else 0
        flt_rt = round((vs / prev_close) * 100, 2) if prev_close else 0.0

        db_rows.append(
            {
                "srtn_cd": srtn_cd,
                "itms_nm": itms_nm,
                "bas_dt": bas_dt,
                "clpr": clpr,
                "vs": vs,
                "flt_rt": flt_rt,
                "mkp": abs(
                    int(
                        float(
                            r.get("mkp")
                            if r.get("mkp") is not None
                            else r.get("open_pric", 0)
                        )
                    )
                ),
                "hipr": abs(
                    int(
                        float(
                            r.get("hipr")
                            if r.get("hipr") is not None
                            else r.get("high_pric", 0)
                        )
                    )
                ),
                "lopr": abs(
                    int(
                        float(
                            r.get("lopr")
                            if r.get("lopr") is not None
                            else r.get("low_pric", 0)
                        )
                    )
                ),
                "trqu": abs(
                    int(
                        float(
                            r.get("trqu")
                            if r.get("trqu") is not None
                            else r.get("trde_qty", 0)
                        )
                    )
                ),
                "tr_at": abs(
                    int(
                        float(
                            r.get("tr_at")
                            if r.get("tr_at") is not None
                            else r.get("trde_prica", 0)
                        )
                    )
                ),
            }
        )
        prev_close = clpr

    if not db_rows:
        return 0

    return repository.upsert_price_rows(db_rows)

'''
매일실행되는 자동배치 진입점(run_daily_job)
-스케쥴러(APScheduler, Cron)가 평일장이 마감된 밤에 자동으로 실행하는 함수
1. DB에서 사용자의 관심종목목록(watchlist)을 가져옴. 만약 비어있다면 시스템 기본 종목 리스트를 가져옴
2. 반복문을 돌며 한 종목씩 collect_stock() 을 실행해 오늘의 새로운 주가를 업데이트함.
3. 디도스(DDoS)오해 방지 : 과도한 트래픽으로 키움 서버에서 차단당하는 것을 막기 위해 종목당 3.0초의
    휴식시간(time.sleep(3.0))을 의도적으로 부여함
4. 모든 종목의 수집이 성공적으로 끄트나면, 전체 종목의 이동평균선과 불린저밴드를 새 주가에 맞게 일괄
    재계산(recompute_all_indicators())     
'''
def run_daily_job():
    """스케줄러(평일 장마감 후)가 호출하는 진입점: 관심종목 전체 갱신 + 지표 재계산."""
    watchlist = repository.get_watchlist() or config.DEFAULT_CODES
    ok_count = 0
    for item in watchlist:
        srtn_cd = item.get("srtn_cd") or item.get("SRTN_CD")
        itms_nm = item.get("itms_nm") or item.get("ITMS_NM")

        if not srtn_cd:
            continue

        # 로그 출력용 식별자 (종목명이 있으면 종목명, 없으면 코드)
        display_name = itms_nm if itms_nm else srtn_cd

        try:
            time.sleep(3.0)  # 429 차단 방지 대기
            if collect_stock(srtn_cd, itms_nm):
                ok_count += 1
        except Exception as e:
            print(f"❌ 일일 수집 실패({display_name}): {str(e)}")

    if ok_count:
        recompute_all_indicators()
    print(f"💾 일일 자동 갱신 완료: {ok_count}/{len(watchlist)}개 종목")

'''
- 백그라운드 스레드에서 실제로 돌아가는 백필 본체 함수
- 전역 변수 backfill_status의 running을 True로 바꾸고 전체 ㅈ오목 수를 세팅
- 루프를 도렴ㄴ서 현재 어떤 종목(current_code)을 수집하고 있는지 기록하고, 한 종목
    이 끝날 때 마다 완료 개수(done)를 1씩 올림
- 속도 최적화 패치 : 일일 배치는 하루 한 번이라 여유 있게 3초를 쉬었지만, 백필은 수백 종목을 
    채워야 하므로 대기시간을 1.5초(time.sleep(1.5))로 단축하여 세팅
- 모든 백필이 끝나면 역시 보조지표를 깔끔하게 재계산한 후 running 상태를 False로 종료        
'''
def _run_backfill_job(codes: list):
    global backfill_status
    backfill_status.update(
        {
            "running": True,
            "done": 0,
            "total": len(codes),
            "current_code": None,
            "last_message": None,
        }
    )

    ok_count = 0

    for item in codes:
        srtn_cd = item.get("srtn_cd") or item.get("SRTN_CD")
        itms_nm = item.get("itms_nm") or item.get("ITMS_NM")

        if not srtn_cd:
            backfill_status["done"] += 1
            continue

        display_name = itms_nm if itms_nm else srtn_cd
        backfill_status["current_code"] = display_name

        try:
            # 💡 [핵심 패치]: 종목이 바뀔 때의 딜레이는 1.5초로 세팅합니다.
            time.sleep(1.5)

            if collect_stock(srtn_cd, itms_nm):
                ok_count += 1
        except Exception as e:
            print(f"❌ 백필 중 오류({display_name}): {str(e)}")

        backfill_status["done"] += 1

    backfill_status["current_code"] = None
    backfill_status["last_message"] = (
        f"완료 · {len(codes)}개 종목 중 {ok_count}개 수집. 지표 재계산 중..."
    )
    recompute_all_indicators()
    backfill_status["last_message"] = (
        f"완료 · {len(codes)}개 종목 중 {ok_count}개 수집 + 지표 재계산 완료"
    )
    backfill_status["running"] = False

'''
대량 데이터 비동기 백필 함수(_run_backfill_job & start_backfill)
- 시스템을 처음 켜서 과거 몇 년 치의 추가 데이터를 통째로 채원 넣어야 할 때 사용하는 기능
- 만약 이미 백필이 돌고 있다면 중복 실행을 막기 위해 False를 반환
- 백필 작업은 수 분 이상 걸릴 수 있으므로, 메인 웹 서버 웹 요청 쓰레드가 지치지 않도록
    데몬 스레드(daemon=True)를 생성하여 백그라운드(뒷방)로 작업을 던져버리고 즉시 True를 반환 
'''
def start_backfill(codes: list = None):
    """관심종목(또는 지정된 종목 리스트) 전체에 대해 백그라운드로 초기 적재를 시작."""
    if backfill_status["running"]:
        return False
    codes = codes or repository.get_watchlist() or config.DEFAULT_CODES
    t = threading.Thread(target=_run_backfill_job, args=(codes,), daemon=True)
    t.start()
    return True
