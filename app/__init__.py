import os
from flask import Flask
from flask_apscheduler import APScheduler

from app.config import config
from app.db.schema import init_db

scheduler = APScheduler()


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
