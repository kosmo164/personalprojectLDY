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

    '''
    블루프린트(Blueprint)를 통한 라우트 등록
    - 순수 HTML화면을 보여주는 뷰라우터(views_bp)와, app.js와 통신하며 데이터를 주고 받는
        Ajax용 REST API라우터(api_bp)를 가져와 앱에 등록함.
    - 코드 중간에 임포트(from...)를 배치하여 순환참조(Circular Import)에러를 원천 차단하는
        안전한 구조를 채택함.    
    '''
    # 라우트 등록
    from app.routes.views import views_bp
    from app.routes.api import api_bp
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp)

    '''
    데이터베이스 초기 세팅 및 데이터 시딩(Seeding)
    - 앱이 켜질때 오라클 DB에 접속하여 주가 테이블, 관심종목 테이블 등이 없으면 자동으로 최초 1회
        생성(CREATE TABLE)함.
    - 동시에 설저 파일에 적어둔 기본 관심 종목 리스트(config.DEFAULT_CODES)를 DB에 기본값으로
        적재(시딩)해둠.    
    '''
    # 테이블이 없으면 생성 + 기본 관심종목 시딩
    init_db(default_codes=config.DEFAULT_CODES)

    '''
    크론(Cron)탭 기반 자동 수집 스케줄러 설정
    해당 대시보드의 핵심 기능 중 하나로, 사람이 직접 수집 버튼을 누르지 않아도 시스템이 스스로 데이터를
    모아오게 만드는 영역
    1. if not scheduler.running : Flask가 디버그 모드로 켜질때 앱이 두번 실행됨녀서 스케쥴러가 중복
        가동되는 현상을 막아주는 방어 코드
    2. scheduler.add_job(...) : 주기적으로 실행할 규칙(Job)을 예약함
        - func=run_daily_job : 실행할 대상 함수(키움증권 API를 호출해 오늘자 시세를 긁어오고 불린저 
            밴드를 재계산하는 무거운 배치함수)
        - trigger="cron" : 리눅스의 크론탭터럼 특정 시각을 지정하는 방식
        - day_of_week="mon-fri", hour=18, minute=0
            주식시장이 열리는 원요일부터 금요일까지, 장이 마감되고 정리가 끝난 매일 오후 6시(18:00)정각에
            이 수집 로직을 자동으로 실행하는 설정.
    3. scheduler.start() : 타이머 엔진을 가동하여 백그라운드 스레드에서 초 단위로 시간을 감시하게 만듬                 
    '''
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
