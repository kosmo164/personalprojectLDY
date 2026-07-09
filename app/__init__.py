'''
기반 설정 및 라이브러리 임포트(import)
- import os : 파일 시스템의 경로(폴더 위치)를 계산하고 조작하기 위한 파이썬 표준 라이브러리임.
- from flask import Flask : 웹서버의 본체가 되는 Flask프레임워크 클래스를 가져옴
- from flask_apscheduler import APScheduler :
    파이썬에서 정기적인 예약 작업(크론탭, 배치작업 등)을 처리해주는 APScheduer를 Flask와 연동하기 
    위해 가져옴
- from app.config import config : 앞서 UI코드 등에서 참조했던 환경 변수 및 글로벌 설정 파일
    (config.py)을 가져옴
- from app.db.schema import init_db :
    데이터베이스 구조(테이블)가 생성되어 있는지 확인하고 초기화하는 함수를 연동함.            
'''
import os
from flask import Flask
from flask_apscheduler import APScheduler

from app.config import config
from app.db.schema import init_db

# 전역에서 관리할 스케쥴러 객체를 미리 선언해둠 
scheduler = APScheduler()

'''
Flask 앱 인스턴스화 및 경로 지정
- base_dir : 현재 __file__(이 소스코드가 위치한 파일)의 절대경로를 파악함.
- 경로바인딩 : 앞서 우리가 살펴보았던 index.html이 담기는 templates폴더와
    style.css, app.js가 담기는 static폴더의 물리적 위치를 Flask엔진에 명확하게
    등록해 줌.
- 설정동기화 : config 객체에 정의된 데이터베이스 접속 정보, 키움API키 등의 세팅을 
    Flask앱 설정 환경(app.config)에 주입함.    
'''
def create_app():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    app = Flask(
        __name__,
        root_path=base_dir,
        template_folder=os.path.join(base_dir, "templates"),
        static_folder=os.path.join(base_dir, "static"),
    )
    app.config.from_object(config)

    # 라우트 등록
    from app.routes.views import views_bp
    from app.routes.api import api_bp
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp)

    # 테이블이 없으면 생성 + 기본 관심종목 시딩
    init_db(default_codes=config.DEFAULT_CODES)

    # 스케줄러: 매일 월-금 18시 자동 실행
    if not scheduler.running:
        from app.services.collector import run_daily_job
        scheduler.add_job(
            id="daily_stock_job",
            func=run_daily_job,
            trigger="cron",
            day_of_week="mon-fri",
            hour=18,
            minute=0,
        )
        scheduler.init_app(app)
        scheduler.start()

    return app
