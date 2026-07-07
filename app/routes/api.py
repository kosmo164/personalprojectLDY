import pandas as pd
from flask import Blueprint, jsonify, request

from app.config import config
from app.db import repository
from app.services import collector
from app.services.predictor import predict_future_prices
from app.services.indicators import recompute_all_indicators

api_bp = Blueprint("api", __name__, url_prefix="/api")


# --------------------------------------------------------
# 관심종목 / 빠른 선택
# --------------------------------------------------------
@api_bp.route("/codes")
def get_codes():
    return jsonify(repository.get_codes_for_quick_picks(config.DEFAULT_CODES))


@api_bp.route("/watchlist", methods=["GET"])
def get_watchlist():
    watchlist = repository.get_watchlist()
    return jsonify(watchlist if watchlist else config.DEFAULT_CODES)


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
@api_bp.route("/backfill/start", methods=["POST"])
def start_backfill():
    started = collector.start_backfill()
    if not started:
        return jsonify({"status": "already_running", **collector.backfill_status})
    return jsonify({"status": "started"})


@api_bp.route("/backfill/status")
def get_backfill_status():
    return jsonify(collector.backfill_status)


# --------------------------------------------------------
# 대시보드 데이터
# --------------------------------------------------------
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
