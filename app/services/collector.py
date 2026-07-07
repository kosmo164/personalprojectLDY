"""
[기능] 시세 수집

키움 REST API의 일봉차트(ka10081)는 종목 1개당 "과거 히스토리 전체"를
한 번의 요청(+연속조회)으로 돌려줍니다. 

- collect_stock(): 종목 1개의 히스토리를 가져와 DB에 upsert
- run_daily_job(): 스케줄러가 매일 호출하는 진입점 (관심종목 전체 갱신 + 지표 재계산)
- run_backfill(): 관심종목 전체에 대해 초기 적재를 수행하고 진행 상황을 backfill_status에 기록
"""

import os
import sys
import threading
import time

# 절대 경로 실행 시 ModuleNotFoundError 방지를 위한 시스템 경로 설정
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from app.config import config
from app.db import repository
from app.services.indicators import recompute_all_indicators
from app.services.kiwoom_client import kiwoom_client

# 프론트에서 폴링하여 진행률을 보여주기 위한 전역 상태
backfill_status = {
    "running": False,
    "done": 0,
    "total": 0,
    "current_code": None,  # 프론트엔드 연동용 기존 키 유지
    "last_message": None,
}


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


def start_backfill(codes: list = None):
    """관심종목(또는 지정된 종목 리스트) 전체에 대해 백그라운드로 초기 적재를 시작."""
    if backfill_status["running"]:
        return False
    codes = codes or repository.get_watchlist() or config.DEFAULT_CODES
    t = threading.Thread(target=_run_backfill_job, args=(codes,), daemon=True)
    t.start()
    return True
