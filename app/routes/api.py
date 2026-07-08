import pandas as pd
from flask import Blueprint, jsonify, request

from app.config import config
from app.db import repository
from app.services import collector
from app.services.predictor import predict_future_prices
from app.services.indicators import recompute_all_indicators

'''
기반 설정 및 라우터 정의
- blueprint : Flask에서 라우트(URL경로)를 모듈화하여 관리할 수 있게 해주는 기능
- url_prefix="/api" : 파일에 정의된 모든 주소 앞에 /api가 자동으로 붙음.
'''
api_bp = Blueprint("api", __name__, url_prefix="/api")


# --------------------------------------------------------
# 관심종목 / 빠른 선택
# --------------------------------------------------------
'''
빠른 선택 목록 조회(GET /api/codes)
- 사용자가 화면에서 종목을 빠르게 선택할 수 있도록, 시스템이 제공하는 기본 종목 코드
    리스트(config.DEFALULT_CODES)를 기반으로 DB나 설정에서 데이터를 조회하여 JSON
    형태로 반환     
'''
@api_bp.route("/codes")
def get_codes():
    return jsonify(repository.get_codes_for_quick_picks(config.DEFAULT_CODES))

'''
관심종목목록조회(GET /api/watchlist)
- 사용자가 등록한 종목 리스트(watchlist)를 DB에서 가져옴
- 만약 DB에 등록된 관심 종목이 하나도 없다면(None 혹은 빈 값), 설정 파일에 지정된 기본
    종목세트(config.DEFAULT_CODES)를 대신 반환하는 안전장치 삽입 
'''
@api_bp.route("/watchlist", methods=["GET"])
def get_watchlist():
    watchlist = repository.get_watchlist()
    return jsonify(watchlist if watchlist else config.DEFAULT_CODES)

'''
관심종목추가(Post /api/watchlist)
- 사용자가 본내 JSON데이터에서 종목코드(srtn_cd)와 종목별(itms_nm)을 추출. silent=True
    덕분에 본문이 JSON형식이 아니어도 서버 에러(500)가 나지않고 빈 딕셔너리로 처리됨.
- 필수 값인 종목코드(srtn_cd)가 비어있다면 클라이언트 잘못이라는 의미로 400 Bad Request
    에러와 메시지를 반환함.
- 정상적이라면 DB저장소(repository)를 통해 관심종목 테이블에 추가함.          
'''
@api_bp.route("/watchlist", methods=["POST"])
def add_watchlist():
    payload = request.get_json(silent=True) or {}
    srtn_cd = (payload.get("srtn_cd") or "").strip()
    itms_nm = (payload.get("itms_nm") or "").strip() or None
    if not srtn_cd:
        return jsonify({"status": "error", "message": "srtn_cd는 필수입니다."}), 400
    repository.add_to_watchlist(srtn_cd, itms_nm)
    return jsonify({"status": "success", "srtn_cd": srtn_cd})


# --------------------------------------------------------
# 백필(초기 적재)
# --------------------------------------------------------
# 대령의 과거 주가 데이터를 가져오는 작업은 시간이 오래걸리므로, 비동기(Background) 혹은
# 상태 관리 방식으로 설계되어 있음.
'''
백필시작(POST /api/backfill/start)
- 수집기(collector)에게 과거 데이터 수집 시작 명령을 내림
- 이미 수집이 진행 중이라면 중목 실행하지 않고 {"status": "already_running"}과 함께
    현재 진행 상태(backfill_status)를 합쳐 반환함. 
'''
@api_bp.route("/backfill/start", methods=["POST"])
def start_backfill():
    started = collector.start_backfill()
    if not started:
        return jsonify({"status": "already_running", **collector.backfill_status})
    return jsonify({"status": "started"})

'''
백필상태조회(GET /api/backfill/status)
- 프론트엔드에서 현재 몇 % 적재되었나를 주기적으로 확인(폴링, Polling)할 수 있도록 현재 백필
    진행 상태를 그대로 반환
'''
@api_bp.route("/backfill/status")
def get_backfill_status():
    return jsonify(collector.backfill_status)


# --------------------------------------------------------
# 대시보드 데이터
# --------------------------------------------------------
'''
종목대시보드 스냅샷 및 예측데이터조회(GET /api/stock/<srtn_cd>)
- 가장 최신 주가 저보(스냅샷)를 Pandas DataFrame(df)형태로 DB에서 조회함. 만약 데이터가
    없다면 404 Not Found 에러를 출력함.
    
'''
@api_bp.route("/stock/<srtn_cd>")
def get_stock_dashboard_data(srtn_cd):
    try:
        df = repository.get_latest_snapshot(srtn_cd)
    except Exception as e:
        print(f"❌ DB 조회 중 SQL 에러 발생: {str(e)}")
        return jsonify({"status": "error", "message": f"DB 조회 중 에러가 발생했습니다: {str(e)}"}), 500

    if df.empty:
        return jsonify({
            "status": "no_data",
            "message": f"종목 코드({srtn_cd}) 데이터가 DB에 없습니다. 초기 데이터 적재를 먼저 실행해 주세요."
        }), 404

    predictions = predict_future_prices(srtn_cd)
    stock_info = df.iloc[0].to_dict()
    for k, v in stock_info.items():
        if pd.isna(v):
            stock_info[k] = None

    stock_info.update(predictions)
    stock_info["status"] = "ok"
    return jsonify(stock_info)


@api_bp.route("/stock/<srtn_cd>/history")
def get_stock_history(srtn_cd):
    try:
        df = repository.get_price_history(srtn_cd)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    days = request.args.get("days", default=90, type=int)
    df = df.tail(days)
    df = df.where(pd.notnull(df), None)
    return jsonify(df.to_dict(orient="records"))


@api_bp.route("/force-update")
@api_bp.route("/force-update/<srtn_cd>")
def force_update(srtn_cd=None):
    try:
        if srtn_cd:
            updated = collector.collect_stock(srtn_cd)
        else:
            collector.run_daily_job()
            updated = 1
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

    if updated:
        if srtn_cd:
            recompute_all_indicators()
        return jsonify({"status": "success", "message": f"{srtn_cd or '관심종목 전체'} 데이터가 성공적으로 적재되었습니다."})
    return jsonify({"status": "error", "message": "데이터 수집 실패. 콘솔 로그의 에러 내용을 확인하세요."})
