'''
역할 : 파이썬의 대표적인 데이터 분석 라이브러리인 Pandas를 가져옴. 보통 관례상 pd라는 
    축약어 사용.
코드 내 사용성 : 이 코드에서는 DB에서 가져온 주가 데이터를 표(테이블)형태의 객체인
    DataFrame으로 다룸. df.empty로 데이터가 비어있는지 확인하거나, pd.isna(v) 및
    pd.notnull(df)를 사용해 데이터의 구멍(결측치,NaN)을 체크하고 처리할때 사용.    
'''
import pandas as pd
'''
역할 : 웹 서버를 구축하기 위한 프레임워크인 Flask에서 핵심기능 3가지를 가져옴
- Blueprint : URL경로를 모듈화하여 관리하는 도구. 여기서는 대시보드 관련 주소들을 /api
    라는 그룹으로 묶는 역할을 함
- jsonify : 파이썬의 딕셔너리나 리스트 데이터를 웹브라우저(클라이언트)가 이해항 수 있는
    JSON형식의 응답 객체로 변환해줌
- request : 사용자가 보낸 HTTP요청 정보(URL파라미터, POST로 보낸 JSON본문 등)에 
    접근할 수 있게 해주는 객체. request.get_json()이나 request.args.get()형태로 사용.        
'''
from flask import Blueprint, jsonify, request

'''
프로젝트 내부모듈임포트(아키텍처구조)
- 직접 작성한 내부 소스코드 파일들(app/폴더 안의 모듈들)을 가져오는 부분
1. 설정관리(from app.config import config)
 - 역할 : 데이터베이스 젒고 정보,API키, 혹은 코드 내에서 사용된 config.DEFAULT_CODES
    (기본종목세트)와 같은 전역설정값들을 모아둔 객체. 시스템의 환경 변수나 공통 옵션을 안정
    하게 관리하기 위해 분리해 준 것임.
2. 데이터베이스접근(from app.db import repository)
 - 역할 : 리포지토리패턴(Repository Pattern)이 적용된 모듈. 실제 데이터베이스(OracleDB)
    에 SQL쿼리를 보내 데이터를 넣고 빼는 복잡한 로직을 이 repository내부에 숨겨둠
 - 코드 내 사용성 : API라우터는 SQL을 직접 알 필요없이 repository.get_watchlist(),
    repository.get_latest_snapshot(srtn_cd) 같은 직관적인 함수만 호출해서 데이터를
    깔끔하게 받아옴
3. 데이터 수집기(from app.services import collector)
 - 역할 : 외부 주식 시세 API(키움증권)로 부터 주가 데이터를 긁어와 (Scraping/Crawling)
    시스템에 적재하는 비즈니스로직을 담당.
 - 코드 내 사용성 : 대량의 과거 데이터를 쌓는 백필 작업(collector.start_backfill())이나
    하루 한번 실행되는 스케줄러 태스크(collector.run_daily_job())를 제어할 때 호출됨.
4. 주가예측엔진(from app.services.predictor import predict_future_prices)
 - 역할 : 특정 종목의 과거 주가 패턴을 분석하여 향후 주가가 어떻게 변할지 계산하는 예측 알고리즘
    (머신러닝/통계모델)모듈
 - 코드 내 사용성 : 대시보드API(GET / api/stock/<srtn_cd>)가 호출될 때 최신 주가와 함께 
    미래 예측치(predict_future_prices(srtncd))를 함께 결합하여 화면에 출력하기 위해 사용.
5. 기술적지표계산기(from app.services.indicators import recompute_all_indicators)
 - 역할 : 단순가격(종가, 시가 등)외에 투자 판단에 도움을 주는 수학적 보조지표들을 계산하는 모듈
 - 코드 내 사용성 : 이전 단계에서 생성했던 테이블 정의를 보면 ma_20(20일이동평균), bollinger_up/down
    (볼린저밴드)같은 컬럼이 있음. /force-updata를 통해 새로운 주가 데이터가 강제로 들어오면, 
    지표들도 새 가격에 맞춰 다시 계산해야 하므로 recompute_all_indicators()를 호출해 DB 갱신함.                       
'''
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
- 데이터가 존재하면, 해당 종목코드의 '미래 주가 예측치'(predict_future_prices)를 계산함.
- 데이터정체 : pandas의 NaN(결측치)값을 파이썬 표준인(None)으로 치환함.(치환하지 않으면
    JSON 반환 시 에러기 발생하거나 프론트엔드에서 처리가 곤란해짐)
- 최신 주가 데이터와 미래 예측 데이터를 하나로 합친(update)최종데이터를 반환         
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

'''
차트용주가 히스토리조회(GET /api/stock/<srtn_cd>/history)
- 특정 종목의 과거 주가 목록을 조회하여 차트(캔들차트 등)를 그릴 수 있게 해주는 API
- 쿼리스트링으로 ?days=30처럼 원하는 일수를 요청할 수 있으며, 주어지지 않으면 기본값으로
    최근 90일(default=90)데이터를 df.tail(days)로 잘라서 반환함.
- 마찬가지로 결측치 처리를 거친 후, 프론트엔드가 다루기 가장 좋은 배열형태
    (orient="records", 즉 [{날짜: ..., 종가: ...}, {...}])로 변환하여 출력     
'''
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

'''
수집강제실행API(/force-update 관련)
- 스케줄러(매일 특정 시간 실행)에 의해 작동할 데이터 수집 로직을 수동으로 즉시 실행하고
    싶을 때 호출하는 관리자용 주소.
- URL 뒤에 종목코드 명시 여부에 따라 다르게 동작함.
    1. 명시한 경우(/api/force-update/A005930): 해당 종목 하나만 새로 긁어온 뒤, 20일
        이동 평균선이나 볼린저 밴드 같은 보조지표를 다시 계산(recompute_all_indicators)함.
    2. 명시하지 않은 경우(/api/force-update): 등록된 전체 관심종목에 대한 일일 수집 태스크
        (run_daily_job)를 통째로 실행함.          
'''
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
